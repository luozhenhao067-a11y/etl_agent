from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.deps import envelope, get_actor, get_container, get_version_or_404
from app.container import Container
from app.core.errors import ApiError
from app.core.masking import sanitize_log_line
from app.core.security import Actor
from app.schemas.common import ERROR_RESPONSES, Envelope
from app.schemas.studio import DesignData

router = APIRouter(tags=["API-11"])


@router.get(
    "/api/v1/versions/{version_id}/design",
    response_model=Envelope[DesignData],
    responses=ERROR_RESPONSES,
    summary="API-11 get generated design",
)
async def get_design(
    request: Request,
    version_id: str,
    actor: Actor = Depends(get_actor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    _version, _project_id = get_version_or_404(container, actor, version_id)
    design = container.state.designs.get(version_id)
    if design is None:
        raise ApiError(409, "API-409", "design not ready", {"version_id": version_id})

    data = DesignData(
        etl_plan_json=design["etl_plan_json"],
        hocon_text=sanitize_log_line(design["hocon_text"]),
        dag=design["dag"],
        quality_contract=design["quality_contract"],
        gate_result=design["gate_result"],
        diff=design.get("diff"),
        masking=design.get("masking"),
    )
    return envelope(request, data.model_dump())
