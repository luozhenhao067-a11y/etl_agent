from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import envelope, get_actor, get_container, get_version_or_404
from app.container import Container
from app.core.errors import ApiError
from app.core.idempotency import (
    body_digest,
    optional_idempotency_key,
    remember_success,
    replay_if_present,
    require_idempotency_key,
)
from app.core.masking import contains_secret_material
from app.core.security import Actor, require_role
from app.core.utils import digest_of, new_id, now_iso
from app.schemas.common import ERROR_RESPONSES, Envelope
from app.schemas.studio import (
    AnswersData,
    AnswersRequest,
    GenerationData,
    GenerationRequest,
)

router = APIRouter(tags=["API-09", "API-10"])

_QUESTION_ID = "create_target"
_QUESTION_TEXT = "目标表不存在，是否创建？"


def _build_design(
    source_profile_ref: str,
    target_profile_ref: str,
    prompt_digest: str,
) -> dict[str, Any]:
    # The design is a synthetic, already-masked candidate produced by the mock
    # state machine. No gate has run, so gate_result is not reported as passed.
    return {
        "etl_plan_json": {
            "source_profile_ref": source_profile_ref,
            "target_profile_ref": target_profile_ref,
            "prompt_digest": prompt_digest,
            "mappings": [],
        },
        "hocon_text": (
            'source { host = "***" user = "***" }\n'
            'sink { table = "***" }'
        ),
        "dag": {"nodes": ["source", "transform", "sink"], "edges": []},
        "quality_contract": {"rules": []},
        "gate_result": {
            "syntax": "not_run",
            "schema": "not_run",
            "masking": "not_run",
            "budget": "not_run",
        },
        "diff": None,
        "masking": {},
    }


@router.post(
    "/api/v1/versions/{version_id}/generation",
    response_model=Envelope[GenerationData],
    responses=ERROR_RESPONSES,
    status_code=201,
    summary="API-09 start agent generation",
)
async def start_generation(
    request: Request,
    version_id: str,
    payload: GenerationRequest,
    response: Response,
    actor: Actor = Depends(get_actor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    version, project_id = get_version_or_404(container, actor, version_id)
    require_role(actor, {"maker"})
    if version.get("is_immutable"):
        raise ApiError(
            409,
            "GEN-409",
            "generation is not allowed on an immutable version",
            {"version_id": version_id},
        )
    if contains_secret_material(payload.prompt):
        raise ApiError(
            422,
            "GEN-422",
            "prompt must not contain secret material",
            {"field": "prompt"},
        )

    key = require_idempotency_key(request)
    digest = body_digest(payload.model_dump())
    scope = f"generation:{actor.user_id}:{version_id}"
    replayed = replay_if_present(
        container.idempotency, scope, key, digest, "GEN-409", request
    )
    if replayed is not None:
        response.status_code = replayed.status_code
        return replayed  # type: ignore[return-value]

    thread_id = payload.thread_id or new_id("thread")
    running = container.repository.get_agent_run_by_thread(version_id, thread_id)
    if running is not None and running["status"] in {"running", "interrupted"}:
        raise ApiError(
            409,
            "GEN-409",
            "generation already running for thread",
            {"thread_id": thread_id},
        )

    agent_run_id = new_id("agent")
    now = now_iso()
    # Rows stay exactly on the Spec 10.1 columns; run-scoped runtime fields
    # (prompt_digest, provider, created_by) live in MemoryState so both the
    # in-memory and SQL backends behave identically.
    container.repository.create_agent_run(
        {
            "id": agent_run_id,
            "version_id": version_id,
            "thread_id": thread_id,
            "prompt": None,
            "status": "interrupted",
            "step_count": 1,
            "error_message": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    container.state.agent_states[agent_run_id] = {
        "thread_id": thread_id,
        "version_id": version_id,
        "actor_id": actor.user_id,
        "created_by": actor.user_id,
        "provider": payload.provider,
        "question_id": _QUESTION_ID,
        "required_fields": [_QUESTION_ID],
        "answered": False,
        "source_profile_ref": payload.source_profile_ref,
        "target_profile_ref": payload.target_profile_ref,
        "prompt_digest": digest_of(payload.prompt),
    }

    await container.record_audit(
        project_id=project_id,
        actor_id=actor.user_id,
        event_type="agent.run.started",
        resource_type="agent_run",
        resource_id=agent_run_id,
        payload={
            "agent_run_id": agent_run_id,
            "version_id": version_id,
            "thread_id": thread_id,
            "provider": payload.provider,
        },
    )
    await container.record_audit(
        project_id=project_id,
        actor_id=actor.user_id,
        event_type="agent.run.interrupted",
        resource_type="agent_run",
        resource_id=agent_run_id,
        payload={"agent_run_id": agent_run_id, "question_id": _QUESTION_ID},
    )

    data = {
        "agent_run_id": agent_run_id,
        "thread_id": thread_id,
        "status": "interrupted",
        "interrupt": {
            "question": _QUESTION_TEXT,
            "fields": [{"name": _QUESTION_ID, "type": "boolean"}],
        },
        "design_digest": None,
    }
    remember_success(container.idempotency, scope, key, digest, 201, data)
    return envelope(request, data)


@router.post(
    "/api/v1/agent-runs/{run_id}/answers",
    response_model=Envelope[AnswersData],
    responses=ERROR_RESPONSES,
    summary="API-10 submit clarification answers",
)
async def submit_answers(
    request: Request,
    run_id: str,
    payload: AnswersRequest,
    response: Response,
    actor: Actor = Depends(get_actor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    repo = container.repository
    run = repo.get_agent_run(run_id)
    if run is None:
        raise ApiError(404, "API-404", "agent run not found", {})
    state = container.state.agent_states.get(run_id, {})
    _version, project_id = get_version_or_404(container, actor, run["version_id"])
    require_role(actor, {"maker"})
    if state.get("created_by") != actor.user_id:
        raise ApiError(
            403,
            "ROLE-403",
            "only the run initiator may answer",
            {"reason": "not_run_initiator"},
        )
    if payload.thread_id != run["thread_id"]:
        raise ApiError(
            422,
            "GEN-422",
            "thread_id does not match the agent run",
            {"field": "thread_id"},
        )

    key = optional_idempotency_key(request)
    digest = body_digest(payload.model_dump())
    scope = f"answers:{actor.user_id}:{run_id}"
    if key is not None:
        replayed = replay_if_present(
            container.idempotency, scope, key, digest, "GEN-409", request
        )
        if replayed is not None:
            response.status_code = replayed.status_code
            return replayed  # type: ignore[return-value]

    if run["status"] != "interrupted":
        raise ApiError(
            409,
            "GEN-409",
            "agent run is not waiting for answers",
            {"status": run["status"]},
        )
    required = state.get("required_fields", [_QUESTION_ID])
    missing = [field for field in required if field not in payload.answers]
    if missing:
        raise ApiError(
            422,
            "GEN-422",
            "answer does not match current question",
            {"field": "answers", "missing": missing},
        )
    if not isinstance(payload.answers.get(_QUESTION_ID), bool):
        raise ApiError(
            422,
            "GEN-422",
            "answer type does not match the question field",
            {"field": "answers"},
        )

    now = now_iso()
    repo.update_agent_run(
        run_id,
        {"status": "completed", "step_count": run.get("step_count", 1) + 1, "updated_at": now},
    )
    state["answered"] = True

    design = _build_design(
        state.get("source_profile_ref", "profile://mock/source"),
        state.get("target_profile_ref", "profile://mock/target"),
        state.get("prompt_digest", ""),
    )
    container.state.designs[run["version_id"]] = design
    repo.update_version(
        run["version_id"],
        {
            "etl_plan_json": design["etl_plan_json"],
            "hocon_text": design["hocon_text"],
            "artifact_digest": digest_of(design["etl_plan_json"]),
            "updated_at": now,
        },
    )

    checkpoint_ref = new_id("ckpt")
    await container.record_audit(
        project_id=project_id,
        actor_id=actor.user_id,
        event_type="agent.run.resumed",
        resource_type="agent_run",
        resource_id=run_id,
        payload={
            "agent_run_id": run_id,
            "thread_id": run["thread_id"],
            "answer_digest": digest_of(payload.answers),
        },
    )

    data = {
        "status": "completed",
        "next_question": None,
        "design_ready": True,
        "checkpoint_ref": checkpoint_ref,
    }
    if key is not None:
        remember_success(container.idempotency, scope, key, digest, 200, data)
    return envelope(request, data)
