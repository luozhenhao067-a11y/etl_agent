from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from app.api.deps import envelope, get_actor
from app.core.security import Actor
from app.core.utils import now_iso
from app.schemas.common import ERROR_RESPONSES, Envelope
from app.schemas.health import ComponentStatus, HealthData

router = APIRouter(tags=["API-01"])


def _component(name: str, status: str, latency_ms: int) -> ComponentStatus:
    return ComponentStatus(name=name, status=status, latency_ms=latency_ms)


@router.get(
    "/health",
    response_model=Envelope[HealthData],
    responses=ERROR_RESPONSES,
    summary="API-01 health check",
)
async def health(request: Request, actor: Actor = Depends(get_actor)) -> dict:
    """Report each wired dependency's real status — never fake readiness.

    Kernel mode probes the control-plane database with ``SELECT 1``; the
    harness/secret/engine components reflect what the composition root
    actually wired (kernel vs stub). In memory/stub mode the unwired
    dependencies keep reporting ``not_configured`` / ``not_implemented`` —
    that is still deliberate honesty, just of the current delivery.
    """

    container = request.app.state.container
    components: list[ComponentStatus] = [
        _component("api", "ok", 0),
    ]

    db_status = "not_configured"
    if container.session_factory is not None:
        started = time.perf_counter()
        try:
            session = container.session_factory()
            try:
                session.execute(text("SELECT 1"))
            finally:
                session.close()
            db_status = "ok"
        except Exception:  # noqa: BLE001 — health must not raise
            db_status = "unavailable"
        components.append(
            _component("database", db_status, int((time.perf_counter() - started) * 1000))
        )
    else:
        components.append(_component("database", db_status, 0))

    kernel_mode = container.commit is not None
    components.append(_component("harness", "ok" if kernel_mode else "not_implemented", 0))
    components.append(
        _component(
            "secret_provider",
            "ok" if kernel_mode else "not_implemented",
            0,
        )
    )
    engine_kind = type(container.exec).__name__
    engine_status = "not_implemented" if engine_kind == "StubExecAdapter" else "ok"
    components.append(_component("execution_engine", engine_status, 0))

    overall = (
        "ok"
        if kernel_mode and db_status == "ok" and engine_status == "ok"
        else ("degraded" if kernel_mode else "degraded")
    )
    data = HealthData(
        status=overall,
        components=components,
        version=container.settings.api_version,
        time=now_iso(),
    )
    return envelope(request, data.model_dump())
