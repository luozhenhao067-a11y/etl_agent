"""In-process asynchronous execution engine adapter (managed simulated jobs).

Production binds this Port to Celery + SeaTunnel; until that engine exists in
the environment this adapter is the real ExecPort implementation: it runs one
``asyncio`` task per submitted job through the same managed lifecycle
(SUBMITTED → RUNNING → SUCCEEDED/FAILED), honours cancellation, and reports
deterministic aggregate metrics derived from the managed artifact digest —
no metrics are invented per call, the same artifact always yields the same
numbers. The simulated nature is declared in every report (``simulated``)
and in the ``engine`` field, so a caller can never mistake it for SeaTunnel.

Fail-closed rules are kept from the stub:

- a command without a non-empty managed artifact (HOCON plan) is refused
  (EXEC-422) — nothing is executed without the immutable plan;
- an unknown ``engine_job_id`` on cancel/query is an honest EXEC-404;
- a job whose plan carries the ``# exec-engine:fail`` marker ends FAILED
  (EXEC-500) so failure paths stay exercisable end to end.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from app.core.harness.errors import HarnessError
from app.core.harness.models import Clock, isoformat, utcnow
from app.core.utils import digest_of, new_id

# Wire format is uppercase, mirroring SeaTunnel REST job states that the
# Worker's supervision layer normalises (worker.poll_run lowercases).
_STATUS_SUBMITTED = "SUBMITTED"
_STATUS_RUNNING = "RUNNING"
_STATUS_SUCCEEDED = "SUCCEEDED"
_STATUS_FAILED = "FAILED"
_STATUS_CANCELLED = "CANCELLED"

_TERMINAL_STATUSES = {_STATUS_SUCCEEDED, _STATUS_FAILED, _STATUS_CANCELLED}

# Plan marker that forces the simulated job to fail (deterministic failure
# injection for the run.failed / rollback paths).
_FAILURE_MARKER = "# exec-engine:fail"

_ENGINE_NAME = "local-async-sim"


class LocalAsyncExecAdapter:
    """ExecPort backed by in-process asyncio jobs (one task per submission)."""

    def __init__(
        self,
        *,
        duration_seconds: float = 1.5,
        clock: Clock = utcnow,
    ) -> None:
        self._duration = max(0.0, duration_seconds)
        self._clock = clock
        # engine_job_id -> mutable job record; the asyncio task handle lives
        # here so cancel_job can stop a non-terminal job.
        self._jobs: dict[str, dict[str, Any]] = {}

    # -- ExecPort ---------------------------------------------------------------

    async def submit_job(self, command: dict[str, Any]) -> dict[str, Any]:
        run_id = str(command.get("execution_run_id") or "").strip()
        hocon = command.get("hocon")
        if not run_id:
            raise HarnessError(422, "EXEC-422", "command is missing execution_run_id")
        if not isinstance(hocon, str) or not hocon.strip():
            # No managed artifact: refuse instead of executing unverified text.
            raise HarnessError(
                422, "EXEC-422", "command is missing the managed HOCON artifact"
            )

        engine_job_id = new_id("eng")
        record: dict[str, Any] = {
            "engine_job_id": engine_job_id,
            "execution_run_id": run_id,
            "artifact_digest": command.get("artifact_digest"),
            "status": _STATUS_SUBMITTED,
            "submitted_at": isoformat(self._clock()),
            "started_at": None,
            "finished_at": None,
            "metrics": {},
            "error_code": None,
            "cancel_reason": None,
            "task": None,
        }
        self._jobs[engine_job_id] = record
        record["task"] = asyncio.create_task(
            self._run_job(engine_job_id, record, hocon),
            name=f"exec-engine:{engine_job_id}",
        )
        return {"engine_job_id": engine_job_id, "status": record["status"]}

    async def cancel_job(self, engine_job_id: str, reason: str) -> dict[str, Any]:
        record = self._require_job(engine_job_id)
        if record["status"] not in _TERMINAL_STATUSES:
            task: asyncio.Task | None = record["task"]
            if task is not None and not task.done():
                task.cancel()
            record["status"] = _STATUS_CANCELLED
            record["finished_at"] = isoformat(self._clock())
            record["cancel_reason"] = str(reason or "")[:200]
        return {
            "engine_job_id": engine_job_id,
            "status": record["status"],
            "cancel_reason": record["cancel_reason"],
        }

    async def query_status(self, engine_job_id: str) -> dict[str, Any]:
        record = self._require_job(engine_job_id)
        report: dict[str, Any] = {
            "engine": _ENGINE_NAME,
            "simulated": True,
            "engine_job_id": engine_job_id,
            "execution_run_id": record["execution_run_id"],
            "status": record["status"],
            "submitted_at": record["submitted_at"],
            "started_at": record["started_at"],
            "finished_at": record["finished_at"],
            **record["metrics"],
        }
        if record["error_code"]:
            report["error_code"] = record["error_code"]
        if record["cancel_reason"]:
            report["cancel_reason"] = record["cancel_reason"]
        return report

    # -- lifecycle ----------------------------------------------------------------

    async def _run_job(
        self, engine_job_id: str, record: dict[str, Any], hocon: str
    ) -> None:
        phase = self._duration / 4.0 if self._duration > 0 else 0.0
        try:
            if phase:
                await asyncio.sleep(phase)  # SUBMITTED → RUNNING
            record["status"] = _STATUS_RUNNING
            record["started_at"] = isoformat(self._clock())
            if phase:
                await asyncio.sleep(self._duration - phase)  # RUNNING → terminal

            if _FAILURE_MARKER in hocon:
                record["status"] = _STATUS_FAILED
                record["error_code"] = "EXEC-500"
            else:
                record["status"] = _STATUS_SUCCEEDED
                record["metrics"] = self._planned_metrics(record, hocon)
            record["finished_at"] = isoformat(self._clock())
        except asyncio.CancelledError:
            # cancel_job already recorded the CANCELLED transition; the
            # cancelled task itself must not overwrite it.
            raise

    def _planned_metrics(self, record: dict[str, Any], hocon: str) -> dict[str, int]:
        """Deterministic aggregate metrics for the simulated run.

        Seeded from the immutable binding (execution_run_id + artifact digest
        + plan text) so re-running the same artifact yields the same numbers;
        nothing here is sampled from real data movement.
        """

        seed = digest_of(
            {
                "execution_run_id": record["execution_run_id"],
                "artifact_digest": record["artifact_digest"],
                "plan": hocon,
            }
        )
        # Four 32-bit lanes from the digest keep the derivation readable.
        lanes = [int(seed[i * 8 : (i + 1) * 8], 16) for i in range(4)]
        input_records = 1_000 + lanes[0] % 9_000
        error_records = lanes[1] % 50
        return {
            "input_records": input_records,
            "output_records": input_records - error_records,
            "error_records": error_records,
            "bytes_processed": (lanes[2] % 5_000 + 1) * 1_024 + len(hocon),
        }

    # -- helpers ------------------------------------------------------------

    def _require_job(self, engine_job_id: str) -> dict[str, Any]:
        record = self._jobs.get(str(engine_job_id or "").strip())
        if record is None:
            raise HarnessError(
                404, "EXEC-404", f"engine job does not exist: {engine_job_id}"
            )
        return record

    async def aclose(self) -> None:
        """Cancel still-running jobs (application shutdown)."""

        for record in self._jobs.values():
            task: asyncio.Task | None = record["task"]
            if task is not None and not task.done():
                task.cancel()


__all__ = ["LocalAsyncExecAdapter"]
