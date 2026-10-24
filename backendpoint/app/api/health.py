from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import envelope, get_actor
from app.core.security import Actor
from app.core.utils import now_iso
from app.schemas.common import ERROR_RESPONSES, Envelope
from app.schemas.health import ComponentStatus, HealthData

router = APIRouter(tags=["API-01"])


@router.get(
    "/health",
    response_model=Envelope[HealthData],
    responses=ERROR_RESPONSES,
    summary="API-01 health check",
)
async def health(request: Request, actor: Actor = Depends(get_actor)) -> dict:
    # This delivery has no PostgreSQL, Redis, Harness, SecretProvider or
    # execution engine. Reporting them as unavailable is deliberate; health
    # must not fake dependency readiness.
    components = [
        ComponentStatus(name="api", status="ok", latency_ms=0),
        ComponentStatus(name="database", status="not_configured", latency_ms=0),
        ComponentStatus(name="harness", status="not_implemented", latency_ms=0),
        ComponentStatus(name="secret_provider", status="not_implemented", latency_ms=0),
        ComponentStatus(name="execution_engine", status="not_implemented", latency_ms=0),
    ]
    data = HealthData(
        status="degraded",
        components=components,
        version=request.app.state.container.settings.api_version,
        time=now_iso(),
    )
    return envelope(request, data.model_dump())
