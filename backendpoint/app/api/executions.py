from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import (
    dependency_unavailable,
    envelope,
    get_actor,
    get_container,
    get_execution_run_or_404,
    harness_error_to_api,
)
from app.container import Container
from app.core.errors import ApiError
from app.core.harness.errors import HarnessError
from app.core.idempotency import (
    body_digest,
    remember_error,
    replay_if_present,
    require_idempotency_key,
)
from app.core.masking import sanitize_log_line
from app.core.security import Actor, require_role
from app.core.utils import digest_of
from app.schemas.common import ERROR_RESPONSES, Envelope
from app.schemas.runtime import (
    CancelData,
    CancelRequest,
    ExecutionRunData,
    Metrics,
    QualityReport,
    RollbackData,
    RollbackRequest,
    Supervision,
)

router = APIRouter(tags=["API-15", "API-16", "API-17"])

_TERMINAL = {"succeeded", "failed", "cancelled"}
_ROLLBACK_ALLOWED = {"failed", "cancelled"}


@router.get(
    "/api/v1/execution-runs/{id}",
    response_model=Envelope[ExecutionRunData],
    responses=ERROR_RESPONSES,
    summary="API-15 get execution run",
)
async def get_execution_run(
    request: Request,
    id: str,
    actor: Actor = Depends(get_actor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    run_id = id
    run, _version, _project_id = get_execution_run_or_404(container, actor, run_id)
    extras = container.state.run_extras.get(run_id, {})

    quality = extras.get("quality_report")
    supervision = extras.get("supervision")
    data = ExecutionRunData(
        status=run["status"],
        engine_job_id=run.get("engine_job_id"),
        metrics=Metrics(
            input_records=run.get("input_records", 0),
            output_records=run.get("output_records", 0),
            error_records=run.get("error_records", 0),
            bytes_processed=run.get("bytes_processed", 0),
            duration_seconds=extras.get("duration_seconds"),
        ),
        quality_report=QualityReport(**quality) if quality else None,
        supervision=Supervision(**supervision) if supervision else None,
        started_at=run.get("started_at"),
        finished_at=run.get("finished_at"),
        recent_logs=[sanitize_log_line(line) for line in extras.get("recent_logs", [])],
    )
    return envelope(request, data.model_dump())


@router.post(
    "/api/v1/execution-runs/{id}/cancel",
    response_model=Envelope[CancelData],
    responses=ERROR_RESPONSES,
    summary="API-16 cancel an execution run",
)
async def cancel_execution_run(
    request: Request,
    id: str,
    payload: CancelRequest,
    response: Response,
    actor: Actor = Depends(get_actor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    if not actor.is_project_member:
        raise ApiError(403, "AUTH-403", "project access denied", {"reason": "not_project_member"})
    require_role(actor, {"ops"}, code="OPS-403")
    run_id = id
    run, _version, _project_id = get_execution_run_or_404(container, actor, run_id)

    key = require_idempotency_key(request)
    if payload.idempotency_key != key:
        raise ApiError(
            422,
            "OPS-422",
            "idempotency_key does not match the Idempotency-Key header",
            {"field": "idempotency_key"},
        )
    digest = body_digest(payload.model_dump())
    scope = f"cancel:{actor.user_id}:{run_id}"
    replayed = replay_if_present(
        container.idempotency, scope, key, digest, "OPS-409", request
    )
    if replayed is not None:
        response.status_code = replayed.status_code
        return replayed  # type: ignore[return-value]

    if run["status"] in _TERMINAL:
        raise ApiError(
            409,
            "OPS-409",
            "run is already in terminal state",
            {"status": run["status"]},
        )

    try:
        await container.harness.replay_guard_check(key, scope)
    except HarnessError as exc:
        error = harness_error_to_api(exc)
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None
    except NotImplementedError:
        error = dependency_unavailable(
            "OPS-503", "harness", "replay guard is unavailable"
        )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None

    # run.cancel is a Tool Broker tool (Spec 3.6): the registered adapter owns
    # the control-plane cancel transaction and its ledger events. The route
    # never mutates the run or calls SeaTunnel directly.
    intent = {
        "tool": "run.cancel",
        "actor_id": actor.user_id,
        "project_id": project_id,
        "environment": container.settings.data_environment,
        "resource_scope": {
            "execution_run_id": run_id,
            "reason_digest": digest_of(payload.reason),
        },
    }
    try:
        decision = await container.harness.pdp_decide(intent)
        result = await container.harness.execute_tool(
            intent, policy_decision=decision, idempotency_key=key
        )
    except HarnessError as exc:
        error = harness_error_to_api(exc)
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None
    except NotImplementedError:
        error = dependency_unavailable(
            "OPS-503", "harness", "run.cancel tool is not available"
        )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None
    if result["status"] != "SUCCEEDED":
        error = dependency_unavailable(
            "OPS-503", "harness", "run.cancel tool did not complete"
        )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error

    output = result["output"] or {}
    data = CancelData(
        status=output["status"],
        cancelled_at=output.get("cancelled_at"),
        external_ref=output.get("external_ref"),
    )
    remember_success(container.idempotency, scope, key, digest, 200, data.model_dump())
    return envelope(request, data.model_dump())


@router.post(
    "/api/v1/execution-runs/{id}/rollback",
    response_model=Envelope[RollbackData],
    responses=ERROR_RESPONSES,
    summary="API-17 rollback shadow resources",
)
async def rollback_execution_run(
    request: Request,
    id: str,
    payload: RollbackRequest,
    actor: Actor = Depends(get_actor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    if not actor.is_project_member:
        raise ApiError(403, "AUTH-403", "project access denied", {"reason": "not_project_member"})
    require_role(actor, {"ops"}, code="OPS-403")
    run_id = id
    run, _version, _project_id = get_execution_run_or_404(container, actor, run_id)

    key = require_idempotency_key(request)
    if payload.idempotency_key != key:
        raise ApiError(
            422,
            "OPS-422",
            "idempotency_key does not match the Idempotency-Key header",
            {"field": "idempotency_key"},
        )
    digest = body_digest(payload.model_dump())
    scope = f"rollback:{actor.user_id}:{run_id}"
    replayed = replay_if_present(
        container.idempotency, scope, key, digest, "OPS-409", request
    )
    if replayed is not None:
        return replayed  # type: ignore[return-value]

    if run["status"] not in _ROLLBACK_ALLOWED:
        raise ApiError(
            409,
            "OPS-409",
            "rollback is only allowed for failed or cancelled runs",
            {"status": run["status"]},
        )

    try:
        await container.harness.replay_guard_check(key, scope)
    except HarnessError as exc:
        error = harness_error_to_api(exc)
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None
    except NotImplementedError:
        error = dependency_unavailable(
            "OPS-503", "harness", "replay guard is unavailable"
        )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None

    # shadow.rollback must run through the Tool Broker (Spec 3.6): the
    # registered adapter owns the cleanup transaction and its ledger events,
    # and never touches shadow or production tables directly from the route.
    intent = {
        "tool": "shadow.rollback",
        "actor_id": actor.user_id,
        "project_id": project_id,
        "environment": container.settings.data_environment,
        "resource_scope": {
            "execution_run_id": run_id,
            "reason_digest": digest_of(payload.reason),
        },
    }
    try:
        decision = await container.harness.pdp_decide(intent)
        result = await container.harness.execute_tool(
            intent, policy_decision=decision, idempotency_key=key
        )
    except HarnessError as exc:
        error = harness_error_to_api(exc)
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None
    except NotImplementedError:
        error = dependency_unavailable(
            "OPS-503", "harness", "shadow.rollback tool is not available"
        )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None
    if result["status"] != "SUCCEEDED":
        error = dependency_unavailable(
            "OPS-503", "harness", "shadow.rollback tool did not complete"
        )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error

    output = result["output"] or {}
    data = RollbackData(
        rollback_status=output["rollback_status"],
        ledger_event_id=output["ledger_event_id"],
        finished_at=output["finished_at"],
    )
    remember_success(container.idempotency, scope, key, digest, 200, data.model_dump())
    return envelope(request, data.model_dump())
