"""Operations tool adapters: ``benchmark.run``, ``run.cancel``, ``shadow.rollback``.

These tools run only in kernel mode. ``run.cancel`` and ``shadow.rollback``
own the SQL transaction that records the control-plane fact together with its
ledger events (same boundary as the Commit orchestrator). A run that was
actually dispatched to the engine (``engine_job_id`` set) requires an engine
adapter this deployment does not ship yet — those fail closed (TB-503), so a
cancel/rollback can never silently skip the engine kill.

Outbox note (Spec 3.8): the Transactional Outbox carries only
``execution.command`` events from the Commit path. Cancel/rollback/benchmark
are Tool Broker operations, not outbox commands.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.harness.broker import ToolUnavailableError
from app.core.harness.errors import HarnessError
from app.core.harness.models import isoformat, utcnow
from app.core.utils import digest_of, new_id
from app.models.tables import ExecutionRun

Clock = Callable[[], datetime]

_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


def _require_scope_value(scope: dict[str, Any], field: str) -> str:
    value = scope.get(field)
    if not isinstance(value, str) or not value.strip():
        raise HarnessError(400, "TB-400", f"{field} is required")
    return value.strip()


def make_benchmark_run_handler(*, clock: Clock = utcnow) -> Any:
    """``benchmark.run``: record the accepted evaluation run.

    The evaluation engine is an external service (评测服务, Spec: Celery 评测
    任务); the tool records the accepted run so the platform can enforce the
    same-suite concurrency rule. ``benchmark.run.started`` is appended by the
    connection service via the gateway; ``benchmark.run.completed`` and any
    metrics belong to the evaluation service — none of it is fabricated here.
    """

    async def handler(intent: dict[str, Any]) -> dict[str, Any]:
        scope = intent["resource_scope"]
        _require_scope_value(scope, "suite_id")
        _require_scope_value(scope, "layer")
        _require_scope_value(scope, "dataset_version")
        now = clock()
        return {
            "benchmark_run_id": new_id("bench"),
            "status": "running",
            "started_at": isoformat(now),
        }

    return handler


def make_run_cancel_handler(
    *, session_factory: Any, ledger: Any, clock: Clock = utcnow
) -> Any:
    """``run.cancel``: control-plane cancel of a never-dispatched run.

    Writes ``status=cancelled`` + ``run.cancel_requested`` / ``run.cancelled``
    ledger events in one transaction. With a dispatched engine job the worker
    would kill the job first and write ``run.cancelled`` itself; until an
    engine adapter exists that path fails closed.
    """

    async def handler(intent: dict[str, Any]) -> dict[str, Any]:
        scope = intent["resource_scope"]
        run_id = _require_scope_value(scope, "execution_run_id")
        reason_digest = scope.get("reason_digest")
        actor_id = intent.get("actor_id") or intent.get("sub") or "system"
        project_id = intent.get("project_id") or ""
        now = clock()

        session = session_factory()
        try:
            row = session.execute(
                select(ExecutionRun).where(ExecutionRun.id == run_id)
            ).scalar_one_or_none()
            if row is None:
                raise HarnessError(
                    409,
                    "OPS-409",
                    "execution run is not persisted",
                    {"reason": "NOT_PERSISTED"},
                )
            if row.status.lower() in _TERMINAL_STATUSES:
                raise HarnessError(
                    409,
                    "OPS-409",
                    "run is already in terminal state",
                    {"status": row.status},
                )
            if row.engine_job_id:
                raise ToolUnavailableError(
                    "no engine adapter is available to kill a dispatched run"
                )
            row.status = "cancelled"
            row.finished_at = now
            row.updated_at = now
            await ledger.append(
                session,
                {
                    "project_id": project_id,
                    "actor_id": actor_id,
                    "event_type": "run.cancel_requested",
                    "resource_type": "execution_run",
                    "resource_id": run_id,
                    "payload_digest": digest_of(
                        {"execution_run_id": run_id, "reason_digest": reason_digest}
                    ),
                },
            )
            await ledger.append(
                session,
                {
                    "project_id": project_id,
                    "actor_id": actor_id,
                    "event_type": "run.cancelled",
                    "resource_type": "execution_run",
                    "resource_id": run_id,
                    "payload_digest": digest_of(
                        {"execution_run_id": run_id, "cancel_scope": "control_plane"}
                    ),
                },
            )
            session.commit()
        except HarnessError:
            session.rollback()
            raise
        except ToolUnavailableError:
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            session.rollback()
            raise HarnessError(503, "OPS-503", "cancel transaction failed") from exc
        finally:
            session.close()

        return {"status": "cancelled", "cancelled_at": isoformat(now), "external_ref": None}

    return handler


def make_shadow_rollback_handler(
    *, session_factory: Any, ledger: Any, clock: Clock = utcnow
) -> Any:
    """``shadow.rollback``: clean a failed/cancelled run's shadow resources.

    A run that was never dispatched has no shadow resources; the cleanup
    completes control-plane-side with an empty scope and the full event trail
    (``run.rollback_requested`` / ``run.rolled_back`` / ``run.cleaned``).
    Production tables are never touched.
    """

    async def handler(intent: dict[str, Any]) -> dict[str, Any]:
        scope = intent["resource_scope"]
        run_id = _require_scope_value(scope, "execution_run_id")
        reason_digest = scope.get("reason_digest")
        actor_id = intent.get("actor_id") or intent.get("sub") or "system"
        project_id = intent.get("project_id") or ""
        now = clock()

        session = session_factory()
        try:
            row = session.execute(
                select(ExecutionRun).where(ExecutionRun.id == run_id)
            ).scalar_one_or_none()
            if row is None:
                raise HarnessError(
                    409,
                    "OPS-409",
                    "execution run is not persisted",
                    {"reason": "NOT_PERSISTED"},
                )
            if row.status.lower() not in {"failed", "cancelled"}:
                raise HarnessError(
                    409,
                    "OPS-409",
                    "rollback is only allowed for failed or cancelled runs",
                    {"status": row.status},
                )
            if row.engine_job_id:
                raise ToolUnavailableError(
                    "no shadow resource adapter is available for a dispatched run"
                )
            requested = await ledger.append(
                session,
                {
                    "project_id": project_id,
                    "actor_id": actor_id,
                    "event_type": "run.rollback_requested",
                    "resource_type": "execution_run",
                    "resource_id": run_id,
                    "payload_digest": digest_of(
                        {"execution_run_id": run_id, "reason_digest": reason_digest}
                    ),
                },
            )
            rolled_back = await ledger.append(
                session,
                {
                    "project_id": project_id,
                    "actor_id": actor_id,
                    "event_type": "run.rolled_back",
                    "resource_type": "execution_run",
                    "resource_id": run_id,
                    "payload_digest": digest_of(
                        {
                            "execution_run_id": run_id,
                            "cleanup_scope": "none",
                            "result": "run was never dispatched",
                        }
                    ),
                },
            )
            await ledger.append(
                session,
                {
                    "project_id": project_id,
                    "actor_id": actor_id,
                    "event_type": "run.cleaned",
                    "resource_type": "execution_run",
                    "resource_id": run_id,
                    "payload_digest": digest_of(
                        {
                            "execution_run_id": run_id,
                            "cleanup_scope": "none",
                            "result": "nothing to clean",
                        }
                    ),
                },
            )
            session.commit()
        except HarnessError:
            session.rollback()
            raise
        except ToolUnavailableError:
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            session.rollback()
            raise HarnessError(503, "OPS-503", "rollback transaction failed") from exc
        finally:
            session.close()

        return {
            "rollback_status": "completed",
            "ledger_event_id": rolled_back["id"],
            "finished_at": isoformat(now),
        }

    return handler


__all__ = [
    "make_benchmark_run_handler",
    "make_run_cancel_handler",
    "make_shadow_rollback_handler",
]
