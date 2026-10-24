"""Managed execution Worker (Spec 5.5 steps 5-10, Spec 5.6 state machine).

One ``execution.command`` at a time:

5. validates the task binding — the run row exists, is still dispatchable
   (``queued``, or ``dispatched`` after a crashed delivery), and the token
   digest matches the unique digest recorded at Commit;
6. verifies the capability through the Capability service (signature, TTL,
   issuance record);
7. delegates replay protection (atomic jti + digest reservation) to the Tool
   Broker — reserving here as well would double-consume the token;
8. re-evaluates the PDP for the exact intent at execution time and lets the
   broker re-check the decision binding;
9. executes the ``etl.execute`` tool, whose handler submits the managed
   command to the ExecPort;
10. writes the result back — status transitions plus the legal audit events
    (``run.started`` / ``run.succeeded`` / ``run.failed``, Spec 12.2).

Failure policy is fail-closed: a rejected command marks the run ``failed``
with the domain error code and never retries. A single-use token that was
rejected (undelivered, expired, wrong binding) can only be replaced by a new
Prepare → Approve → Commit cycle (Spec 5.1). Redelivered commands whose run
already left the dispatchable states are acked as duplicates without any
mutation (Spec 5.5 step 10 — 重复投递被拒绝且不重复执行).
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.harness.errors import HarnessError
from app.core.harness.kernel import HarnessKernel
from app.core.harness.models import utcnow
from app.core.utils import digest_of
from app.models.tables import ExecutionRun, Pipeline, PipelineVersion
from harness.core.ledger_sql import SqlLedger
from harness.services.gateway import SessionFactory
from harness.worker.etl_execute import make_etl_execute_handler

Clock = Callable[..., Any]

# Wire format is lowercase, matching the contract examples ("queued",
# "running") and the API terminal sets; Spec 4.7 uses the same names in
# uppercase prose.
_STATUS_DISPATCHED = "dispatched"
_STATUS_RUNNING = "running"
_STATUS_FAILED = "failed"

# ``dispatched`` re-enters the flow deliberately: a crashed delivery leaves
# the row claimed, and the re-attempt then fails honestly at the broker
# (the single-use token is already consumed — Spec 5.1: 失败不返还令牌).
_DISPATCHABLE_STATUSES = {"queued", "dispatched"}

# audit_events.actor_id references users, so the Worker writes its ledger
# events under the seeded svc_harness_worker service account.
_WORKER_ACTOR = "svc_harness_worker"

_METRIC_KEYS = (
    "input_records",
    "output_records",
    "error_records",
    "bytes_processed",
)


def resolve_run_project(session: Session, run_row: ExecutionRun) -> str | None:
    """Project attribution for audit events (run rows carry no project)."""

    pipeline_id = session.execute(
        select(PipelineVersion.pipeline_id).where(PipelineVersion.id == run_row.version_id)
    ).scalar_one_or_none()
    if pipeline_id is None:
        return None
    return session.execute(
        select(Pipeline.project_id).where(Pipeline.id == pipeline_id)
    ).scalar_one_or_none()


class ExecutionWorker:
    """Consumes ``execution.command`` events on behalf of the engine."""

    def __init__(
        self,
        *,
        kernel: HarnessKernel,
        session_factory: SessionFactory,
        ledger: SqlLedger,
        exec_port: Any,
        clock: Clock = utcnow,
    ) -> None:
        self._kernel = kernel
        self._session_factory = session_factory
        self._ledger = ledger
        self._exec = exec_port
        self._clock = clock
        # The managed execution tool is registered here: only a verified
        # single-use execution context may reach the engine (Spec 5.5).
        kernel.broker.register_handler(
            "etl.execute",
            make_etl_execute_handler(
                exec_port=exec_port, session_factory=session_factory, clock=clock
            ),
        )

    # -- Spec 5.5 steps 5-10 ---------------------------------------------------

    async def handle_command(
        self, event: dict[str, Any], *, capability_token: str | None = None
    ) -> dict[str, Any]:
        """Consume one command; never raises for business rejections.

        Returns ``{"result": "executed" | "rejected" | "duplicate", ...}``.
        All three are delivery successes for the dispatcher (the command was
        processed); only unexpected exceptions propagate as transport
        failures. ``project_id`` is included for the dispatcher's audit.
        """
        run_id = event.get("aggregate_id")
        if not isinstance(run_id, str) or not run_id:
            return {"result": "rejected", "failure_code": "OBX-422", "project_id": None}

        row = self._load_run(run_id)
        if row is None:
            return {"result": "rejected", "failure_code": "OBX-422", "project_id": None}

        if (row.status or "").lower() not in _DISPATCHABLE_STATUSES:
            # Redelivery of an already-dispatched/terminal run: ack without
            # mutating — duplicates never re-execute (Spec 5.5 step 10).
            return {
                "result": "duplicate",
                "status": row.status,
                "project_id": self._project_of(run_id),
            }

        if not capability_token:
            # The handoff store lost the entry (restart or TTL): the token
            # can never be re-issued for this run, so fail it instead of
            # leaving it queued forever (fail closed).
            await self._mark_failed(
                run_id, "CAP-403", "capability token was not delivered to the worker"
            )
            return {"result": "rejected", "failure_code": "CAP-403", "project_id": None}

        try:
            # Step 5 binding checks are local: the SHA256 of the delivered
            # bytes must equal the unique digest recorded at Commit. Signature
            # verification, replay reservation and consumption (steps 6-7) are
            # the broker's job — a Worker-side verify would present the
            # single-use capability twice and fail it (CAP-409).
            token_digest = hashlib.sha256(capability_token.encode("utf-8")).hexdigest()
            if token_digest != row.capability_token_digest:
                raise HarnessError(
                    403, "CAP-403", "capability token does not belong to this run"
                )
            claims = self._kernel.capability.decode_claims(capability_token)
            if claims.get("execution_run_id") != run_id:
                raise HarnessError(
                    403, "CAP-403", "capability token is bound to another run"
                )
        except HarnessError as exc:
            await self._mark_failed(run_id, exc.error_code, exc.message)
            return {
                "result": "rejected",
                "failure_code": exc.error_code,
                "project_id": self._project_of(run_id),
            }

        # Spec 5.6: QUEUED → DISPATCHED once verification passed.
        await self._mark_dispatched(run_id)

        # The intent is rebuilt from the verified claims, so the broker's
        # claim binding (step 8) re-checks exactly what was approved.
        intent = {
            "tool": "etl.execute",
            "actor_id": claims.get("sub"),
            "project_id": claims.get("project_id"),
            "environment": claims.get("environment"),
            "resource_scope": claims.get("resource_scope"),
            "artifact_digest": claims.get("artifact_digest"),
            "preparation_id": claims.get("preparation_id"),
            "execution_run_id": claims.get("execution_run_id"),
        }
        try:
            decision = self._kernel.pdp.decide(intent)
            outcome = await self._kernel.broker.execute(
                intent, policy_decision=decision, capability_token=capability_token
            )
        except HarnessError as exc:
            # Broker rejections are already audited as tool.call.rejected by
            # the broker; here the run itself fails closed.
            await self._mark_failed(run_id, exc.error_code, exc.message)
            return {
                "result": "rejected",
                "failure_code": exc.error_code,
                "project_id": claims.get("project_id"),
            }

        if outcome.get("status") != "SUCCEEDED":
            # UNKNOWN (TB-424/504) means the side effect may have happened —
            # the run fails honestly with that code; supervision reconciles.
            code = outcome.get("error_code") or "TB-500"
            await self._mark_failed(run_id, code, "tool broker did not execute the command")
            return {
                "result": "rejected",
                "failure_code": code,
                "project_id": claims.get("project_id"),
            }

        engine_job_id = (outcome.get("output") or {}).get("external_ref")
        if not isinstance(engine_job_id, str) or not engine_job_id:
            await self._mark_failed(run_id, "WKR-500", "engine returned no job reference")
            return {
                "result": "rejected",
                "failure_code": "WKR-500",
                "project_id": claims.get("project_id"),
            }

        await self._mark_running(run_id, engine_job_id, claims)
        return {
            "result": "executed",
            "status": _STATUS_RUNNING,
            "engine_job_id": engine_job_id,
            "project_id": claims.get("project_id"),
        }

    # -- supervision (Spec 8.10 refresh) ---------------------------------------

    async def poll_run(self, run_id: str) -> dict[str, Any]:
        """Refresh one running run from the engine and close it out."""

        row = self._load_run(run_id)
        if row is None:
            return {"result": "missing"}
        if (row.status or "").lower() != _STATUS_RUNNING or not row.engine_job_id:
            return {"result": "skipped", "status": row.status}
        try:
            report = await self._exec.query_status(row.engine_job_id)
        except NotImplementedError:
            # No engine wired: an honest no-op, never a fabricated state.
            return {"result": "unavailable"}
        except HarnessError:
            # The engine rejected the lookup (unknown job, engine outage):
            # stay honest — the run keeps its state, supervision reconciles.
            return {"result": "unavailable"}
        engine_status = str(report.get("status") or "").lower()
        metrics = {
            key: report[key]
            for key in _METRIC_KEYS
            if isinstance(report.get(key), int) and not isinstance(report[key], bool)
            and report[key] >= 0
        }
        if engine_status == "succeeded":
            await self._complete(run_id, "succeeded", metrics)
            return {"result": "completed", "status": "succeeded"}
        if engine_status == "failed":
            await self._complete(
                run_id, "failed", metrics, str(report.get("error_code") or "EXEC-500")
            )
            return {"result": "completed", "status": "failed"}
        return {"result": "running", "engine_status": report.get("status")}

    async def supervise_running(self, limit: int = 50) -> dict[str, int]:
        """One supervision pass (Spec 8.10 ``supervision_tick``).

        Refreshes every ``running`` run from the engine; runs whose engine
        has reached a terminal state are closed out by :meth:`poll_run`.
        Returns the per-outcome summary. Without an engine adapter this is
        an honest no-op per run (``unavailable``) — never a fabricated state.
        """

        session = self._session_factory()
        try:
            run_ids = (
                session.execute(
                    select(ExecutionRun.id)
                    .where(ExecutionRun.status == _STATUS_RUNNING)
                    .order_by(ExecutionRun.updated_at)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
        finally:
            session.close()
        summary = {"completed": 0, "running": 0, "unavailable": 0, "skipped": 0}
        for run_id in run_ids:
            outcome = await self.poll_run(run_id)
            result = outcome.get("result")
            if result in summary:
                summary[result] += 1
            elif result == "missing":
                summary["skipped"] += 1
        return summary

    # -- state transitions (each one transaction, run + audit atomically) ------

    async def _mark_dispatched(self, run_id: str) -> None:
        session = self._session_factory()
        try:
            row = self._require_run(session, run_id)
            if row.status.lower() not in _DISPATCHABLE_STATUSES:
                raise HarnessError(409, "WKR-409", "run is no longer dispatchable")
            row.status = _STATUS_DISPATCHED
            row.updated_at = self._clock()
            session.commit()
        except HarnessError:
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            session.rollback()
            raise HarnessError(503, "WKR-503", "execution run update failed") from exc
        finally:
            session.close()

    async def _mark_running(
        self, run_id: str, engine_job_id: str, claims: dict[str, Any]
    ) -> None:
        session = self._session_factory()
        try:
            row = self._require_run(session, run_id)
            if row.status.lower() != _STATUS_DISPATCHED:
                raise HarnessError(409, "WKR-409", "run is not in dispatched state")
            row.status = _STATUS_RUNNING
            row.engine_job_id = engine_job_id
            row.started_at = self._clock()
            row.updated_at = row.started_at
            await self._ledger.append(
                session,
                {
                    "project_id": claims.get("project_id")
                    or resolve_run_project(session, row),
                    "actor_id": _WORKER_ACTOR,
                    "event_type": "run.started",
                    "resource_type": "execution_run",
                    "resource_id": run_id,
                    "payload_digest": digest_of(
                        {"execution_run_id": run_id, "engine_job_id": engine_job_id}
                    ),
                },
            )
            session.commit()
        except HarnessError:
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            session.rollback()
            raise HarnessError(503, "WKR-503", "execution run update failed") from exc
        finally:
            session.close()

    async def _mark_failed(self, run_id: str, failure_code: str, message: str) -> None:
        session = self._session_factory()
        try:
            row = session.get(ExecutionRun, run_id)
            project_id = None
            if row is not None and row.status.lower() in _DISPATCHABLE_STATUSES | {
                _STATUS_RUNNING
            }:
                row.status = _STATUS_FAILED
                row.finished_at = self._clock()
                row.updated_at = row.finished_at
                project_id = resolve_run_project(session, row)
            if project_id:
                await self._ledger.append(
                    session,
                    {
                        "project_id": project_id,
                        "actor_id": _WORKER_ACTOR,
                        "event_type": "run.failed",
                        "resource_type": "execution_run",
                        "resource_id": run_id,
                        "payload_digest": digest_of(
                            {
                                "execution_run_id": run_id,
                                "failure_code": failure_code,
                                "reason_digest": digest_of(message),
                            }
                        ),
                    },
                )
            session.commit()
        except HarnessError:
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            session.rollback()
            raise HarnessError(503, "WKR-503", "execution run update failed") from exc
        finally:
            session.close()

    async def _complete(
        self,
        run_id: str,
        terminal_status: str,
        metrics: dict[str, int],
        failure_code: str | None = None,
    ) -> None:
        session = self._session_factory()
        try:
            row = self._require_run(session, run_id)
            if row.status.lower() != _STATUS_RUNNING:
                raise HarnessError(409, "WKR-409", "only a running run can complete")
            for key in _METRIC_KEYS:
                setattr(row, key, metrics.get(key, 0))
            row.status = terminal_status
            row.finished_at = self._clock()
            row.updated_at = row.finished_at
            project_id = resolve_run_project(session, row)
            if failure_code is None:
                event_type, payload = "run.succeeded", {"metrics": metrics}
            else:
                event_type = "run.failed"
                payload = {"failure_code": failure_code, "metrics": metrics}
            await self._ledger.append(
                session,
                {
                    "project_id": project_id,
                    "actor_id": _WORKER_ACTOR,
                    "event_type": event_type,
                    "resource_type": "execution_run",
                    "resource_id": run_id,
                    "payload_digest": digest_of({"execution_run_id": run_id, **payload}),
                },
            )
            session.commit()
        except HarnessError:
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            session.rollback()
            raise HarnessError(503, "WKR-503", "execution run update failed") from exc
        finally:
            session.close()

    # -- helpers ---------------------------------------------------------------

    def _load_run(self, run_id: str) -> ExecutionRun | None:
        session = self._session_factory()
        try:
            return session.get(ExecutionRun, run_id)
        finally:
            session.close()

    def _require_run(self, session: Session, run_id: str) -> ExecutionRun:
        row = session.get(ExecutionRun, run_id)
        if row is None:
            raise HarnessError(404, "WKR-404", "execution run does not exist")
        return row

    def _project_of(self, run_id: str) -> str | None:
        session = self._session_factory()
        try:
            row = session.get(ExecutionRun, run_id)
            if row is None:
                return None
            return resolve_run_project(session, row)
        finally:
            session.close()


__all__ = ["ExecutionWorker", "resolve_run_project"]
