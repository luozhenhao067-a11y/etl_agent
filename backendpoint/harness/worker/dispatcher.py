"""Outbox dispatcher (Spec 5.5 step 4, Spec 3.8 state machine).

Delivers committed ``execution.command`` events to the Worker with at-least-
once semantics:

- ``begin_dispatch`` claims an atomic lease (PENDING/RETRYING only);
- the plaintext capability token is popped from the in-process handoff store
  (``PendingCommandStore``) — the Outbox row itself carries the digest only;
- the Worker outcome decides the write path: executed / rejected / duplicate
  are all delivery successes → PUBLISHED → CONSUMED plus the legal audit
  events ``outbox.event.published`` and ``outbox.event.consumed`` (Spec 12.2);
- transport-level failures (broker unavailable, database down) go through
  ``mark_failed`` → RETRYING with lease expiry, or DEAD_LETTER once the
  attempt budget is spent, audited as ``outbox.event.failed``.

Business rejections are deliberately NOT retried: the Worker has already
failed the run (fail-closed); a redelivery could never re-execute it because
the single-use token is consumed (Spec 5.1).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from sqlalchemy.exc import SQLAlchemyError

from app.core.harness.errors import HarnessError
from app.core.harness.models import utcnow
from app.core.utils import digest_of
from app.models.tables import ExecutionRun
from harness.core.ledger_sql import SqlLedger
from harness.core.outbox_sql import SqlOutbox
from harness.services.gateway import SessionFactory
from harness.worker.commands import PendingCommandStore
from harness.worker.worker import ExecutionWorker, resolve_run_project

Clock = Callable[..., Any]

# audit_events.actor_id references users, so the dispatcher writes its
# ledger events under the seeded svc_harness_outbox service account.
_OUTBOX_ACTOR = "svc_harness_outbox"

_logger = logging.getLogger("etl.dispatch")

# A delivery (worker handling + ack) must finish inside this budget: a hung
# step must never stall the whole dispatch beat — the lease expires and the
# next tick retries the event instead.
_DELIVERY_TIMEOUT_SECONDS = 20.0


class OutboxDispatcher:
    """Claims, delivers and closes out ``execution.command`` events."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        outbox: SqlOutbox,
        ledger: SqlLedger,
        worker: ExecutionWorker,
        commands: PendingCommandStore,
        clock: Clock = utcnow,
        batch_size: int = 20,
        lease_seconds: int = 60,
        delivery_timeout_seconds: float = _DELIVERY_TIMEOUT_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._outbox = outbox
        self._ledger = ledger
        self._worker = worker
        self._commands = commands
        self._clock = clock
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._delivery_timeout = delivery_timeout_seconds

    async def dispatch_pending(self) -> dict[str, int]:
        """One dispatch pass; returns a per-outcome summary."""
        summary = {
            "delivered": 0,
            "rejected": 0,
            "duplicate": 0,
            "failed": 0,
            "skipped": 0,
        }
        session = self._session_factory()
        try:
            records = self._outbox.list_dispatchable(
                session, limit=self._batch_size
            )
        finally:
            session.close()
        for record in records:
            if record.get("event_type") != "execution.command":
                # Spec 3.8: the Outbox carries execution commands only —
                # anything else is a schema violation, left for inspection.
                summary["skipped"] += 1
                continue
            try:
                summary[await self._deliver(record)] += 1
            except (HarnessError, SQLAlchemyError) as exc:
                # One poisoned event must not stall the batch; the lease
                # expires and the next tick retries it.
                _logger.warning(
                    "outbox delivery failed: event_id=%s code=%s",
                    record.get("event_id"),
                    getattr(exc, "error_code", "OBX-503"),
                    exc_info=True,
                )
                summary["failed"] += 1
            except asyncio.TimeoutError:
                _logger.warning(
                    "outbox delivery timed out: event_id=%s (retry on next tick)",
                    record.get("event_id"),
                )
                summary["failed"] += 1
        return summary

    # -- one event -------------------------------------------------------------

    async def _deliver(self, record: dict[str, Any]) -> str:
        event_id = record["event_id"]
        lease = await asyncio.wait_for(
            self._claim(event_id), timeout=self._delivery_timeout
        )
        if lease is None:
            return "skipped"  # leased elsewhere or no longer dispatchable

        lease_id = lease["lease_id"]
        token = self._commands.pop(record.get("aggregate_id") or "")
        try:
            outcome = await asyncio.wait_for(
                self._worker.handle_command(record, capability_token=token),
                timeout=self._delivery_timeout,
            )
        except HarnessError as exc:
            self._restore(record, token)
            await self._fail(
                event_id,
                lease_id,
                retryable=True,
                code=exc.error_code,
                reason=exc.message,
            )
            return "failed"
        except SQLAlchemyError as exc:
            self._restore(record, token)
            await self._fail(
                event_id, lease_id, retryable=True, code="OBX-503", reason=str(exc)
            )
            return "failed"
        except asyncio.TimeoutError:
            # A hung delivery step must not dead-letter the command nor stall
            # the beat: the run state is unknown, so restore the token and
            # let the lease expiry retry (the Worker's status gate keeps
            # redelivery idempotent — Spec 5.5 step 10).
            self._restore(record, token)
            await self._fail(
                event_id, lease_id, retryable=True, code="OBX-504", reason="delivery timed out"
            )
            return "failed"
        except Exception as exc:  # unexpected bug: dead-letter, never spin
            # No restore: a dead-lettered command is never redelivered.
            await self._fail(
                event_id, lease_id, retryable=False, code="WKR-500", reason=str(exc)
            )
            return "failed"

        try:
            await asyncio.wait_for(
                self._ack(record, lease_id, outcome), timeout=self._delivery_timeout
            )
        except HarnessError:
            # The run may already be running; redelivery is idempotent (the
            # Worker's status gate acks duplicates without mutation). The
            # token goes back so the retry can actually deliver it.
            self._restore(record, token)
            await self._fail(
                event_id, lease_id, retryable=True, code="OBX-503", reason="ack failed"
            )
            return "failed"
        except asyncio.TimeoutError:
            self._restore(record, token)
            await self._fail(
                event_id, lease_id, retryable=True, code="OBX-504", reason="ack timed out"
            )
            return "failed"

        return {
            "executed": "delivered",
            "rejected": "rejected",
            "duplicate": "duplicate",
        }.get(outcome.get("result"), "failed")

    def _restore(self, record: dict[str, Any], token: str | None) -> None:
        """Return an undelivered token to the handoff store for the retry.

        The store TTL restarts, but that is only the mirror: the broker's
        verify enforces the token's real ``exp`` and rejects an expired one
        (CAP-410), so an over-stored token still fails closed.
        """
        if token is not None:
            self._commands.put(record.get("aggregate_id") or "", token)

    async def _claim(self, event_id: str) -> dict[str, Any] | None:
        session = self._session_factory()
        try:
            lease = await self._outbox.begin_dispatch(
                session, event_id, lease_seconds=self._lease_seconds
            )
            # The lease is only real once committed; an uncommitted claim
            # would roll back on close and every mark_* call would fail its
            # lease check.
            session.commit()
            return lease
        except HarnessError:
            session.rollback()
            return None
        except SQLAlchemyError:
            session.rollback()
            # No lease to mark_failed with; the next tick retries.
            raise
        finally:
            session.close()

    async def _ack(
        self, record: dict[str, Any], lease_id: str, outcome: dict[str, Any]
    ) -> None:
        """PUBLISHED → CONSUMED with the two legal audit events."""

        event_id = record["event_id"]
        run_id = record.get("aggregate_id")
        session = self._session_factory()
        try:
            await self._outbox.mark_published(session, event_id, lease_id)
            # The state machine must advance even when the project cannot be
            # attributed (broken data) — the audit events are then skipped,
            # never guessed.
            project_id = outcome.get("project_id")
            if project_id:
                await self._ledger.append(
                    session,
                    {
                        "project_id": project_id,
                        "actor_id": _OUTBOX_ACTOR,
                        "event_type": "outbox.event.published",
                        "resource_type": "outbox_event",
                        "resource_id": event_id,
                        "payload_digest": digest_of(
                            {"event_id": event_id, "attempts": record.get("attempts", 0)}
                        ),
                    },
                )
            await self._outbox.consume(session, event_id)
            if project_id:
                await self._ledger.append(
                    session,
                    {
                        "project_id": project_id,
                        "actor_id": _OUTBOX_ACTOR,
                        "event_type": "outbox.event.consumed",
                        "resource_type": "outbox_event",
                        "resource_id": event_id,
                        "payload_digest": digest_of(
                            {"event_id": event_id, "execution_run_id": run_id}
                        ),
                    },
                )
            session.commit()
        except HarnessError:
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            session.rollback()
            raise HarnessError(503, "OBX-503", "outbox consume failed") from exc
        finally:
            session.close()

    async def _fail(
        self,
        event_id: str,
        lease_id: str,
        *,
        retryable: bool,
        code: str,
        reason: str,
    ) -> None:
        session = self._session_factory()
        try:
            record = await self._outbox.mark_failed(
                session, event_id, lease_id, retryable=retryable, reason=reason
            )
            project_id = None
            run_row = session.get(ExecutionRun, record.get("aggregate_id") or "")
            if run_row is not None:
                project_id = resolve_run_project(session, run_row)
            if project_id:
                await self._ledger.append(
                    session,
                    {
                        "project_id": project_id,
                        "actor_id": _OUTBOX_ACTOR,
                        "event_type": "outbox.event.failed",
                        "resource_type": "outbox_event",
                        "resource_id": event_id,
                        "payload_digest": digest_of(
                            {
                                "event_id": event_id,
                                "attempts": record.get("attempts", 0),
                                "reason_code": code,
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
            raise HarnessError(503, "OBX-503", "outbox failure recording failed") from exc
        finally:
            session.close()


__all__ = ["OutboxDispatcher"]
