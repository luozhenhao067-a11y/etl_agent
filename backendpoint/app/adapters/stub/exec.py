"""Celery / SeaTunnel stub. Never fabricates job IDs or metrics."""

from __future__ import annotations

from typing import Any

_NOT_READY = "EXEC_ENGINE_NOT_READY"


class StubExecAdapter:
    async def submit_job(self, command: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(_NOT_READY)

    async def cancel_job(self, engine_job_id: str, reason: str) -> dict[str, Any]:
        raise NotImplementedError(_NOT_READY)

    async def query_status(self, engine_job_id: str) -> dict[str, Any]:
        raise NotImplementedError(_NOT_READY)
