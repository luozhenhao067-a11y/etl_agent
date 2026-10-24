from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import (
    dependency_unavailable,
    envelope,
    get_actor,
    get_container,
    get_preparation_or_404,
    get_version_or_404,
    harness_error_to_api,
)
from app.container import Container
from app.core.errors import ApiError
from app.core.harness.errors import HarnessError
from app.core.idempotency import (
    body_digest,
    remember_error,
    remember_success,
    replay_if_present,
    require_idempotency_key,
)
from app.core.security import Actor, ensure_project_access, require_role
from app.core.utils import digest_of, now_iso
from app.schemas.common import ERROR_RESPONSES, Envelope
from app.schemas.runtime import (
    CommitData,
    CommitRequest,
    DecisionData,
    DecisionRequest,
    PrepareData,
    PrepareRequest,
)

router = APIRouter(tags=["API-12", "API-13", "API-14"])

_SLOT_ROLE = {"data_checker": "checker1", "security_checker": "checker2"}


@router.post(
    "/api/v1/versions/{version_id}/prepare",
    response_model=Envelope[PrepareData],
    responses=ERROR_RESPONSES,
    status_code=201,
    summary="API-12 prepare a version",
)
async def prepare_version(
    request: Request,
    version_id: str,
    payload: PrepareRequest,
    actor: Actor = Depends(get_actor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    version, project_id = get_version_or_404(container, actor, version_id)
    require_role(actor, {"maker"})
    if not version.get("is_immutable"):
        raise ApiError(
            409,
            "PREP-409",
            "version is not immutable",
            {"version_id": version_id},
        )

    design = container.state.designs.get(version_id)
    if design is None:
        raise ApiError(
            422,
            "PREP-422",
            "deterministic gate has not passed",
            {"reason": "design_not_ready"},
        )
    gate_result = design.get("gate_result", {})
    if any(value != "passed" for value in gate_result.values()):
        raise ApiError(
            422,
            "PREP-422",
            "deterministic gate has not passed",
            {"reason": "gate_not_passed"},
        )

    key = require_idempotency_key(request)
    digest = body_digest(payload.model_dump())
    fingerprint = f"sha256:{digest_of({'artifact_digest': version.get('artifact_digest'), **payload.model_dump()})}"
    scope = f"prepare:{actor.user_id}:{version_id}"
    replayed = replay_if_present(
        container.idempotency, scope, key, digest, "PREP-409", request
    )
    if replayed is not None:
        return replayed  # type: ignore[return-value]

    # The PDP evaluates the execution intent this preparation would freeze
    # (Spec 4.2): tool etl.execute scoped to the immutable version. The API
    # contract carries no environment fact, so the deployment-configured data
    # environment is used; the budget enters as the PDP requested_budget.
    try:
        decision = await container.harness.pdp_decide(
            {
                "tool": "etl.execute",
                "actor_id": actor.user_id,
                "project_id": project_id,
                "environment": container.settings.data_environment,
                "resource_scope": {
                    "version_id": version_id,
                    "pipeline_id": version.get("pipeline_id"),
                },
                "artifact_digest": version.get("artifact_digest"),
                "requested_budget": {
                    budget_key: budget_value
                    for budget_key, budget_value in payload.budget.items()
                    if isinstance(budget_value, (int, float))
                    and not isinstance(budget_value, bool)
                },
            }
        )
    except HarnessError as exc:
        error = harness_error_to_api(exc)
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None
    except NotImplementedError:
        error = dependency_unavailable(
            "API-503", "harness", "PDP dependency is unavailable"
        )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None

    if container.prepare is None:
        # HARNESS=stub: no kernel is wired, so no preparation_id or approval
        # slots may be invented.
        error = dependency_unavailable(
            "API-503", "harness", "Preparation orchestration is not available"
        )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error

    try:
        result = await container.prepare.create(
            version=version,
            project_id=project_id,
            applicant_id=actor.user_id,
            fingerprint=fingerprint,
            request_facts=payload.model_dump(),
            decision=decision,
        )
    except HarnessError as exc:
        error = harness_error_to_api(exc)
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None

    preparation = result["preparation"]
    # Memory read model for approve/commit; the SQL row is the durable record
    # and commit fails closed when it is missing.
    container.state.preparations[preparation["preparation_id"]] = preparation

    data = {
        "preparation_id": preparation["preparation_id"],
        "fingerprint": preparation["fingerprint"],
        "risk_level": preparation["risk_level"],
        "approval_slots": result["approval_slots"],
        "rollback_plan": preparation["rollback_plan"],
        "status": preparation["status"],
    }
    remember_success(container.idempotency, scope, key, digest, 201, data)
    return envelope(request, data)


@router.post(
    "/api/v1/approval-requests/{approval_id}/decisions",
    response_model=Envelope[DecisionData],
    responses=ERROR_RESPONSES,
    summary="API-13 record an approval decision",
)
async def decide_approval(
    request: Request,
    approval_id: str,
    payload: DecisionRequest,
    response: Response,
    actor: Actor = Depends(get_actor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    repo = container.repository
    approval = repo.get_approval(approval_id)
    if approval is None:
        raise ApiError(404, "API-404", "approval request not found", {})
    preparation = container.state.preparations.get(approval["preparation_id"])
    if preparation is None:
        raise ApiError(404, "API-404", "preparation not found", {})
    ensure_project_access(container, actor, preparation["project_id"])

    if actor.user_id == preparation["applicant_id"]:
        await container.record_audit(
            project_id=preparation["project_id"],
            actor_id=actor.user_id,
            event_type="approval.self_approval_blocked",
            resource_type="approval_request",
            resource_id=approval_id,
            payload={
                "approval_id": approval_id,
                "actor_id": actor.user_id,
                "error_code": "APR-403",
            },
        )
        raise ApiError(
            403,
            "APR-403",
            "self approval forbidden",
            {"reason": "SELF_APPROVAL_FORBIDDEN"},
        )

    key = require_idempotency_key(request)
    if payload.idempotency_key != key:
        raise ApiError(
            422,
            "APR-422",
            "idempotency_key does not match the Idempotency-Key header",
            {"field": "idempotency_key"},
        )
    digest = body_digest(payload.model_dump())
    scope = f"approval:{actor.user_id}:{approval_id}"
    replayed = replay_if_present(
        container.idempotency, scope, key, digest, "APR-409", request
    )
    if replayed is not None:
        response.status_code = replayed.status_code
        return replayed  # type: ignore[return-value]

    siblings = [
        row
        for row in repo.list_approvals(preparation["preparation_id"])
        if row["id"] != approval_id
    ]
    if any(row.get("approver_id") == actor.user_id and row["status"] == "APPROVED" for row in siblings):
        raise ApiError(
            409,
            "APR-409",
            "role slot conflict",
            {"reason": "ROLE_SLOT_CONFLICT"},
        )

    required_role = approval["required_role"]
    expected_actor_role = _SLOT_ROLE.get(required_role)
    if (
        expected_actor_role is None
        or actor.role != expected_actor_role
        or required_role not in actor.role_slots
    ):
        raise ApiError(
            403,
            "APR-403",
            "approval role grant missing",
            {"reason": "ROLE_GRANT_MISSING"},
        )

    if approval["status"] != "PENDING":
        raise ApiError(
            409,
            "APR-409",
            "approval decision is immutable",
            {"reason": "DECISION_IMMUTABLE", "status": approval["status"]},
        )

    decided_at = now_iso()
    new_status = "APPROVED" if payload.decision == "approve" else "REJECTED"
    repo.update_approval(
        approval_id,
        {
            "status": new_status,
            "decision": payload.decision,
            "approver_id": actor.user_id,
            "decided_at": decided_at,
            "updated_at": decided_at,
        },
    )

    all_approvals = repo.list_approvals(preparation["preparation_id"])
    statuses = [row["status"] for row in all_approvals]
    if new_status == "REJECTED" or "REJECTED" in statuses:
        preparation["status"] = "REJECTED"
    elif statuses and all(status == "APPROVED" for status in statuses):
        preparation["status"] = "APPROVED"
    else:
        preparation["status"] = "PARTIAL_APPROVED"

    if container.prepare is not None:
        # Kernel mode: sync the durable preparation row with the decision.
        # A memory-only demo preparation has no row and is skipped by design.
        await container.prepare.record_status(
            preparation["preparation_id"], preparation["status"]
        )

    next_slot_status = siblings[0]["status"] if len(siblings) == 1 else None

    await container.record_audit(
        project_id=preparation["project_id"],
        actor_id=actor.user_id,
        event_type="approval.decision.recorded",
        resource_type="approval_request",
        resource_id=approval_id,
        payload={
            "approval_id": approval_id,
            "decision": payload.decision,
            "approver_id": actor.user_id,
            "opinion_digest": digest_of(payload.opinion) if payload.opinion else None,
        },
    )

    # Contract 9.1 / Spec 12.2: when the last of the 2/2 approvals lands, the
    # approval process itself completes as one auditable step.
    if preparation["status"] == "APPROVED":
        await container.record_audit(
            project_id=preparation["project_id"],
            actor_id=actor.user_id,
            event_type="approval.completed",
            resource_type="preparation",
            resource_id=preparation["preparation_id"],
            payload={
                "preparation_id": preparation["preparation_id"],
                "approval_ids": [row["id"] for row in all_approvals],
                "approver_ids": [row["approver_id"] for row in all_approvals],
            },
        )

    data = {
        "approval_id": approval_id,
        "status": new_status,
        "decided_at": decided_at,
        "next_slot_status": next_slot_status,
    }
    remember_success(container.idempotency, scope, key, digest, 200, data)
    return envelope(request, data)


@router.post(
    "/api/v1/preparations/{preparation_id}/commit",
    response_model=Envelope[CommitData],
    responses=ERROR_RESPONSES,
    status_code=201,
    summary="API-14 commit a preparation",
)
async def commit_preparation(
    request: Request,
    preparation_id: str,
    payload: CommitRequest,
    actor: Actor = Depends(get_actor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    if not actor.is_project_member:
        raise ApiError(
            403,
            "AUTH-403",
            "project access denied",
            {"reason": "not_project_member"},
        )
    require_role(actor, {"ops"}, code="CMT-403")
    preparation = get_preparation_or_404(container, actor, preparation_id)

    key = require_idempotency_key(request)
    if payload.idempotency_key != key:
        raise ApiError(
            422,
            "API-422",
            "idempotency_key does not match the Idempotency-Key header",
            {"field": "idempotency_key"},
        )
    digest = body_digest(payload.model_dump())
    scope = f"commit:{actor.user_id}:{preparation_id}"
    replayed = replay_if_present(
        container.idempotency, scope, key, digest, "CMT-409", request
    )
    if replayed is not None:
        return replayed  # type: ignore[return-value]

    if preparation.get("commit") is not None:
        raise ApiError(
            409,
            "CMT-409",
            "preparation is already committed",
            {"reason": "ALREADY_COMMITTED"},
        )
    if preparation["status"] != "APPROVED":
        missing = [
            row["required_role"]
            for row in container.repository.list_approvals(preparation_id)
            if row["status"] != "APPROVED"
        ]
        raise ApiError(
            409,
            "CMT-409",
            "approval incomplete",
            {"reason": "APPROVAL_INCOMPLETE", "missing_slots": missing},
        )

    approvals = container.repository.list_approvals(preparation_id)
    approved = [row for row in approvals if row["status"] == "APPROVED"]
    approver_ids = {row.get("approver_id") for row in approved}
    if (
        len(approved) < 2
        or len(approver_ids) < 2
        or preparation["applicant_id"] in approver_ids
        or None in approver_ids
    ):
        raise ApiError(
            409,
            "CMT-409",
            "approval facts violate duty separation",
            {
                "reason": "APPROVAL_INCOMPLETE",
                "approved_count": len(approved),
                "distinct_approvers": len(approver_ids),
            },
        )

    if container.commit is None:
        # HARNESS=stub: no kernel is wired, so no capability, ExecutionRun or
        # Outbox event may be fabricated.
        error = dependency_unavailable(
            "CMT-503", "harness", "commit orchestration is not available"
        )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error

    version, _version_project_id = get_version_or_404(
        container, actor, preparation["version_id"]
    )
    try:
        result = await container.commit.commit(
            preparation=preparation,
            version=version,
            approvals=approved,
            actor_id=actor.user_id,
        )
    except HarnessError as exc:
        error = harness_error_to_api(exc)
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None

    data = {
        "execution_run_id": result["execution_run_id"],
        "status": result["status"],
        "committed_at": result["committed_at"],
        "capability_digest": result["capability_digest"],
    }
    # Memory-side commit record: duplicate commits read it for CMT-409. The
    # token plaintext never leaves the orchestrator; only the digest returns.
    preparation["commit"] = {**data, "committed_by": actor.user_id}
    preparation["status"] = "COMMITTED"
    remember_success(container.idempotency, scope, key, digest, 201, data)
    return envelope(request, data)
