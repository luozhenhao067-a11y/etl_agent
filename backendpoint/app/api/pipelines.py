from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import envelope, get_actor, get_container
from app.container import Container
from app.core.errors import ApiError
from app.core.idempotency import (
    body_digest,
    remember_success,
    replay_if_present,
    require_idempotency_key,
)
from app.core.masking import contains_secret_material
from app.core.security import Actor, ensure_project_access, require_role
from app.core.utils import new_id, now_iso
from app.schemas.common import ERROR_RESPONSES, Envelope
from app.schemas.studio import PipelineCreateData, PipelineCreateRequest

router = APIRouter(tags=["API-08"])


@router.post(
    "/api/v1/pipelines",
    response_model=Envelope[PipelineCreateData],
    responses=ERROR_RESPONSES,
    status_code=201,
    summary="API-08 create pipeline",
)
async def create_pipeline(
    request: Request,
    payload: PipelineCreateRequest,
    response: Response,
    actor: Actor = Depends(get_actor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    ensure_project_access(container, actor, payload.project_id)
    if payload.project_id != actor.project_id:
        raise ApiError(
            403,
            "AUTH-403",
            "project access denied",
            {"reason": "project_context_mismatch"},
        )
    require_role(actor, {"maker"})
    if payload.description and contains_secret_material(payload.description):
        raise ApiError(
            422,
            "API-422",
            "description must not contain secret material",
            {"field": "description"},
        )

    key = require_idempotency_key(request)
    digest = body_digest(payload.model_dump())
    scope = f"pipeline:create:{actor.user_id}:{payload.project_id}"
    replayed = replay_if_present(
        container.idempotency, scope, key, digest, "API-409", request
    )
    if replayed is not None:
        response.status_code = replayed.status_code
        return replayed  # type: ignore[return-value]

    existing = container.repository.get_pipeline_by_code(payload.project_id, payload.code)
    if existing is not None:
        raise ApiError(409, "API-409", "pipeline code already exists", {"field": "code"})

    pipeline_id = new_id("pipe")
    created_at = now_iso()
    container.repository.create_pipeline(
        {
            "id": pipeline_id,
            "project_id": payload.project_id,
            "name": payload.name,
            "code": payload.code,
            "description": payload.description,
            "status": "draft",
            "created_at": created_at,
            "updated_at": created_at,
        }
    )

    # pipeline.created is in the Spec 12.2 catalog (Spec 9.2/12.2).
    await container.record_audit(
        project_id=payload.project_id,
        actor_id=actor.user_id,
        event_type="pipeline.created",
        resource_type="pipeline",
        resource_id=pipeline_id,
        payload={"pipeline_id": pipeline_id, "code_digest": digest},
    )

    data = {
        "pipeline_id": pipeline_id,
        "status": "draft",
        "created_at": created_at,
    }
    remember_success(container.idempotency, scope, key, digest, 201, data)
    return envelope(request, data)
