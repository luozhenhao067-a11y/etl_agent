"""Execution boundary (Celery / SeaTunnel in production)."""

from __future__ import annotations

from typing import Any, Protocol


class ExecPort(Protocol):
    async def submit_job(self, command: dict[str, Any]) -> dict[str, Any]:
        """Submit a managed SeaTunnel job."""
        ...

    async def cancel_job(self, engine_job_id: str, reason: str) -> dict[str, Any]:
        """Cancel a managed SeaTunnel job."""
        ...

    async def query_status(self, engine_job_id: str) -> dict[str, Any]:
        """Query managed job status and metrics."""
        ...
