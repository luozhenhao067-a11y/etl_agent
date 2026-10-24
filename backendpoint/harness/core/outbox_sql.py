"""PostgreSQL Transactional Outbox (Spec 3.8 / 5.3).

Durable counterpart of ``app.core.harness.outbox.InMemoryOutbox``: identical
state-machine and validation semantics, but events persist in the
``outbox_events`` table created by migration 0002 (P-06 confirmed 2026-10-24).

Every method takes the caller's SQLAlchemy ``Session`` and never commits:
``enqueue`` joins the same transaction as the business fact (for Commit that
is ``execution_runs`` plus the audit event), so the command cannot survive
without the fact or vice versa (Spec 4.4). Dispatch transitions (batch 2
dispatcher) own their own session boundaries.

A duplicate ``event_id`` or ``idempotency_key`` raises ``OBX-409``. The
pre-check SELECT keeps the common case exception-free; a concurrent commit
that wins the unique-index race aborts the transaction with IntegrityError,
mapped here to ``OBX-409`` — the caller must roll back and retry the whole
business transaction.

``begin_dispatch`` claims a lease with one guarded ``UPDATE`` (status still
dispatchable AND no active lease), so two dispatchers cannot hold the same
event. Expired leases are taken over; the stale holder's ``mark_*`` call then
fails its lease check (``OBX-409``/``OBX-410``), matching the in-memory
adapter.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.harness.errors import HarnessError
from app.core.harness.models import (
    OUTBOX_CONSUMED,
    OUTBOX_DEAD_LETTER,
    OUTBOX_PENDING,
    OUTBOX_PUBLISHED,
    OUTBOX_RETRYING,
    Clock,
    assert_no_secret_material,
    is_digest,
    isoformat,
    require_nonempty,
    utcnow,
)
from harness.models.outbox import OutboxEvent


def to_utc_datetime(value: str | datetime, field: str) -> datetime:
    """Parse an ISO-8601 string (or pass a datetime through) as aware UTC.

    Shared by the SQL harness adapters so every stored timestamp is timezone
    aware regardless of the caller's format. Naive values are taken as UTC,
    matching the in-memory harness adapters.
    """

    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class SqlOutbox:
    def __init__(
        self,
        *,
        clock: Clock = utcnow,
        max_attempts: int = 5,
        lease_seconds: int = 30,
    ) -> None:
        self._clock = clock
        self._max_attempts = max_attempts
        self._lease_seconds = lease_seconds

    # -- write side (Commit transaction) -------------------------------------

    async def enqueue(self, session: Session, event: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(event, dict):
            raise HarnessError(422, "OBX-422", "outbox event must be an object")
        if "payload" in event:
            raise HarnessError(
                422,
                "OBX-422",
                "outbox stores payload_digest only, not payload",
                {"field": "payload"},
            )
        try:
            assert_no_secret_material(event)
            event_type = event.get("event_type", "execution.command")
            if event_type != "execution.command":
                raise ValueError("event_type must be execution.command")
            aggregate_id = require_nonempty(event.get("aggregate_id"), "aggregate_id")
            idempotency_key = require_nonempty(
                event.get("idempotency_key"), "idempotency_key"
            )
            if not is_digest(event.get("payload_digest")):
                raise ValueError(
                    "payload_digest must be a 64-character lowercase SHA256"
                )
            event_id = str(event.get("event_id") or f"obx_{uuid.uuid4().hex[:16]}")
            require_nonempty(event_id, "event_id")
            available_at = to_utc_datetime(
                event.get("available_at") or isoformat(self._clock()), "available_at"
            )
            created_at = to_utc_datetime(
                event.get("created_at") or isoformat(self._clock()), "created_at"
            )
        except ValueError as exc:
            raise HarnessError(422, "OBX-422", str(exc)) from None

        duplicate = session.execute(
            select(OutboxEvent.event_id).where(
                (OutboxEvent.event_id == event_id)
                | (OutboxEvent.idempotency_key == idempotency_key)
            )
        ).first()
        if duplicate is not None:
            raise HarnessError(409, "OBX-409", "outbox event already exists")

        row = OutboxEvent(
            event_id=event_id,
            event_type=event_type,
            aggregate_id=aggregate_id,
            payload_digest=event["payload_digest"],
            idempotency_key=idempotency_key,
            status=OUTBOX_PENDING,
            attempts=0,
            available_at=available_at,
            created_at=created_at,
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            # The unique index on idempotency_key aborted the transaction;
            # the caller must roll back and retry the business transaction.
            raise HarnessError(409, "OBX-409", "outbox event already exists") from exc
        return self._record(row)

    # -- dispatch side (dispatcher sessions) ---------------------------------

    async def begin_dispatch(
        self, session: Session, event_id: str, *, lease_seconds: int | None = None
    ) -> dict[str, Any]:
        event_id = self._require_event_id(event_id)
        now = self._now()
        seconds = lease_seconds if lease_seconds is not None else self._lease_seconds
        if seconds <= 0:
            raise HarnessError(422, "OBX-422", "outbox lease must be positive")
        lease_id = f"lease_{uuid.uuid4().hex[:16]}"
        lease_until = now + timedelta(seconds=seconds)

        # One guarded UPDATE claims the lease atomically: the winner is the
        # only transaction whose WHERE still matched.
        result = session.execute(
            update(OutboxEvent)
            .where(
                OutboxEvent.event_id == event_id,
                OutboxEvent.status.in_({OUTBOX_PENDING, OUTBOX_RETRYING}),
                or_(
                    OutboxEvent.lease_until.is_(None),
                    OutboxEvent.lease_until <= now,
                ),
            )
            .values(lease_id=lease_id, lease_until=lease_until)
        )
        if result.rowcount != 1:
            row = self._get(session, event_id)
            if row.status not in {OUTBOX_PENDING, OUTBOX_RETRYING}:
                raise HarnessError(409, "OBX-409", "outbox event is not dispatchable")
            raise HarnessError(409, "OBX-409", "outbox event already has an active lease")
        return {
            "event_id": event_id,
            "lease_id": lease_id,
            "lease_until": isoformat(lease_until),
            "status": self._get(session, event_id).status,
        }

    async def mark_published(
        self, session: Session, event_id: str, lease_id: str
    ) -> dict[str, Any]:
        row = self._get(session, self._require_event_id(event_id))
        self._validate_lease(row, lease_id)
        if row.status not in {OUTBOX_PENDING, OUTBOX_RETRYING}:
            raise HarnessError(
                409, "OBX-409", "outbox event cannot transition to PUBLISHED"
            )
        row.status = OUTBOX_PUBLISHED
        row.published_at = self._now()
        self._clear_lease(row)
        session.flush()
        return self._record(row)

    async def mark_failed(
        self,
        session: Session,
        event_id: str,
        lease_id: str,
        *,
        retryable: bool = True,
        reason: str = "dispatch failed",
    ) -> dict[str, Any]:
        row = self._get(session, self._require_event_id(event_id))
        self._validate_lease(row, lease_id)
        if row.status not in {OUTBOX_PENDING, OUTBOX_RETRYING}:
            raise HarnessError(
                409, "OBX-409", "outbox event cannot transition to retry"
            )
        row.attempts = (row.attempts or 0) + 1
        row.last_error = str(reason)[:200]
        if not retryable or row.attempts >= self._max_attempts:
            row.status = OUTBOX_DEAD_LETTER
            row.dead_lettered_at = self._now()
        else:
            row.status = OUTBOX_RETRYING
        self._clear_lease(row)
        session.flush()
        return self._record(row)

    async def consume(self, session: Session, event_id: str) -> dict[str, Any]:
        row = self._get(session, self._require_event_id(event_id))
        if row.status != OUTBOX_PUBLISHED:
            raise HarnessError(
                409, "OBX-409", "only a published event can be consumed"
            )
        row.status = OUTBOX_CONSUMED
        row.consumed_at = self._now()
        session.flush()
        return self._record(row)

    async def dead_letter(
        self, session: Session, event_id: str, reason: str
    ) -> dict[str, Any]:
        row = self._get(session, self._require_event_id(event_id))
        if row.status == OUTBOX_CONSUMED:
            raise HarnessError(
                409, "OBX-409", "consumed event cannot be dead-lettered"
            )
        row.status = OUTBOX_DEAD_LETTER
        row.last_error = str(reason)[:200]
        row.dead_lettered_at = self._now()
        session.flush()
        return self._record(row)

    # -- read side ------------------------------------------------------------

    def get(self, session: Session, event_id: str) -> dict[str, Any] | None:
        row = session.execute(
            select(OutboxEvent).where(OutboxEvent.event_id == event_id)
        ).scalar_one_or_none()
        return self._record(row) if row is not None else None

    def list_dispatchable(
        self, session: Session, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Events ready for ``begin_dispatch`` (no active lease), oldest first."""

        now = self._now()
        rows = (
            session.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.status.in_({OUTBOX_PENDING, OUTBOX_RETRYING}),
                    or_(
                        OutboxEvent.lease_until.is_(None),
                        OutboxEvent.lease_until <= now,
                    ),
                )
                .order_by(OutboxEvent.available_at)
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [self._record(row) for row in rows]

    # -- helpers --------------------------------------------------------------

    def _get(self, session: Session, event_id: str) -> OutboxEvent:
        row = session.execute(
            select(OutboxEvent).where(OutboxEvent.event_id == event_id)
        ).scalar_one_or_none()
        if row is None:
            raise HarnessError(422, "OBX-422", "outbox event does not exist")
        return row

    @staticmethod
    def _require_event_id(event_id: str) -> str:
        try:
            return require_nonempty(event_id, "event_id")
        except ValueError as exc:
            raise HarnessError(422, "OBX-422", str(exc)) from None

    def _validate_lease(self, row: OutboxEvent, lease_id: str) -> None:
        current = row.lease_id
        if not current or current != lease_id:
            raise HarnessError(409, "OBX-409", "outbox dispatch lease does not match")
        if row.lease_until is None or self._now() > to_utc_datetime(
            row.lease_until, "time"
        ):
            raise HarnessError(410, "OBX-410", "outbox dispatch lease has expired")

    @staticmethod
    def _clear_lease(row: OutboxEvent) -> None:
        row.lease_id = None
        row.lease_until = None

    def _now(self) -> datetime:
        return to_utc_datetime(self._clock(), "clock")

    @staticmethod
    def _record(row: OutboxEvent) -> dict[str, Any]:
        record: dict[str, Any] = {
            "event_id": row.event_id,
            "event_type": row.event_type,
            "aggregate_id": row.aggregate_id,
            "payload_digest": row.payload_digest,
            "idempotency_key": row.idempotency_key,
            "attempts": row.attempts,
            "available_at": isoformat(row.available_at),
            "created_at": isoformat(row.created_at),
            "status": row.status,
        }
        for field in ("published_at", "consumed_at", "dead_lettered_at"):
            value = getattr(row, field)
            if value is not None:
                record[field] = isoformat(value)
        if row.last_error is not None:
            record["last_error"] = row.last_error
        return record


__all__ = ["SqlOutbox", "to_utc_datetime"]
