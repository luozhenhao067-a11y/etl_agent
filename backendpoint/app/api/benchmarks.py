from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.deps import (
    dependency_unavailable,
    envelope,
    get_actor,
    get_container,
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
from app.core.utils import digest_of
from app.core.security import Actor, require_checker2
from app.schemas.common import ERROR_RESPONSES, Envelope
from app.schemas.runtime import BenchmarkData, BenchmarkRequest

router = APIRouter(tags=["API-18"])


@router.post(
    "/api/v1/benchmarks/run",
    response_model=Envelope[BenchmarkData],
    responses=ERROR_RESPONSES,
    status_code=201,
    summary="API-18 trigger benchmark run",
)
async def run_benchmark(
    request: Request,
    payload: BenchmarkRequest,
    actor: Actor = Depends(get_actor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    if not actor.is_project_member:
        raise ApiError(403, "AUTH-403", "project access denied", {"reason": "not_project_member"})
    require_checker2(actor)

    key = require_idempotency_key(request)
    if payload.idempotency_key != key:
        raise ApiError(
            422,
            "BENCH-422",
            "idempotency_key does not match the Idempotency-Key header",
            {"field": "idempotency_key"},
        )
    digest = body_digest(payload.model_dump())
    # Contract §8: the scope is the benchmark target itself
    # (suite_id + layer + dataset_version), not the actor. The same key on a
    # different target is a fresh request; within one target the key replays
    # the first result or conflicts on payload mismatch.
    scope = f"benchmark:{payload.suite_id}:{payload.layer}:{payload.dataset_version}"
    replayed = replay_if_present(
        container.idempotency, scope, key, digest, "BENCH-409", request
    )
    if replayed is not None:
        return replayed  # type: ignore[return-value]

    for row in container.state.benchmark_runs.values():
        if (
            row["suite_id"] == payload.suite_id
            and row["layer"] == payload.layer
            and row["dataset_version"] == payload.dataset_version
            and row["status"] == "running"
        ):
            raise ApiError(
                409,
                "BENCH-409",
                "benchmark already running for suite, layer and dataset",
                {"suite_id": payload.suite_id, "layer": payload.layer},
            )

    try:
        await container.harness.replay_guard_check(key, scope)
    except HarnessError as exc:
        error = harness_error_to_api(exc)
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None
    except NotImplementedError:
        error = dependency_unavailable(
            "BENCH-503", "harness", "benchmark service is unavailable"
        )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None

    # benchmark.run is a Tool Broker tool (Spec 3.6/8.13): the registered
    # adapter records the accepted evaluation run. No evaluation metrics are
    # invented here — they belong to the external evaluation service.
    intent = {
        "tool": "benchmark.run",
        "actor_id": actor.user_id,
        "project_id": actor.project_id or "",
        "environment": container.settings.data_environment,
        "resource_scope": {
            "suite_id": payload.suite_id,
            "layer": payload.layer,
            "dataset_version": payload.dataset_version,
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
            "BENCH-503", "harness", "benchmark.run tool is not available"
        )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None
    if result["status"] != "SUCCEEDED":
        error = dependency_unavailable(
            "BENCH-503", "harness", "benchmark.run tool did not complete"
        )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error

    output = result["output"] or {}
    benchmark_run_id = output["benchmark_run_id"]
    container.state.benchmark_runs[benchmark_run_id] = {
        "benchmark_run_id": benchmark_run_id,
        "suite_id": payload.suite_id,
        "layer": payload.layer,
        "dataset_version": payload.dataset_version,
        "status": output["status"],
        "started_at": output["started_at"],
    }
    await container.harness.append_ledger(
        {
            "project_id": actor.project_id or "",
            "actor_id": actor.user_id,
            "event_type": "benchmark.run.started",
            "resource_type": "benchmark_run",
            "resource_id": benchmark_run_id,
            "payload_digest": digest_of(
                {
                    "benchmark_run_id": benchmark_run_id,
                    "suite_id": payload.suite_id,
                    "layer": payload.layer,
                }
            ),
        }
    )

    data = BenchmarkData(
        benchmark_run_id=benchmark_run_id,
        status=output["status"],
        started_at=output["started_at"],
    )
    if container.evaluation is not None:
        # The evaluation runs asynchronously (契约 §6 API-18: 异步执行); the
        # service closes the run out and records benchmark.run.completed.
        container.evaluation.start(
            benchmark_run_id=benchmark_run_id,
            suite_id=payload.suite_id,
            layer=payload.layer,
            dataset_version=payload.dataset_version,
            project_id=actor.project_id or "",
            actor_id=actor.user_id,
        )
    remember_success(container.idempotency, scope, key, digest, 201, data.model_dump())
    return envelope(request, data.model_dump())
