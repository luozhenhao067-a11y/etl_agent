"""Transactional Outbox state machine (Spec 3.8 / 5.3).

Physical atomicity is not implementable until P-06 defines the Outbox table.
This adapter provides a fail-closed, in-memory state machine for kernel tests
and for the later commit orchestrator. It must not be presented as durable
delivery.
"""

from __future__ import annotations

import asyncio
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

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


class InMemoryOutbox:
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
        self._events: dict[str, dict[str, Any]] = {}
        self._idempotency_keys: set[str] = set()
        self._lock = asyncio.Lock()

    async def enqueue(self, event: dict[str, Any]) -> dict[str, Any]:
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
                raise ValueError("payload_digest must be a 64-character lowercase SHA256")
            event_id = str(event.get("event_id") or f"obx_{uuid.uuid4().hex[:16]}")
            require_nonempty(event_id, "event_id")
            available_at = event.get("available_at") or isoformat(self._clock())
            if not isinstance(available_at, str):
                raise ValueError("available_at must be an ISO-8601 string")
            created_at = event.get("created_at") or isoformat(self._clock())
            if not isinstance(created_at, str):
                raise ValueError("created_at must be an ISO-8601 string")
        except ValueError as exc:
            raise HarnessError(422, "OBX-422", str(exc)) from None

        async with self._lock:
            if event_id in self._events or idempotency_key in self._idempotency_keys:
                raise HarnessError(409, "OBX-409", "outbox event already exists")
            record = {
                "event_id": event_id,
                "event_type": event_type,
                "aggregate_id": aggregate_id,
                "payload_digest": event["payload_digest"],
                "idempotency_key": idempotency_key,
                "attempts": 0,
                "available_at": available_at,
                "created_at": created_at,
                "status": OUTBOX_PENDING,
            }
            self._events[event_id] = record
            self._idempotency_keys.add(idempotency_key)
            return self._safe_record(record)

    async def begin_dispatch(
        self, event_id: str, *, lease_seconds: int | None = None
    ) -> dict[str, Any]:
        async with self._lock:
            record = self._get_locked(event_id)
            if record["status"] not in {OUTBOX_PENDING, OUTBOX_RETRYING}:
                raise HarnessError(409, "OBX-409", "outbox event is not dispatchable")
            now = _as_utc(self._clock())
            lease_until = record.get("_lease_until")
            if lease_until is not None:
                lease_until = _as_utc(lease_until)
                if now <= lease_until:
                    raise HarnessError(409, "OBX-409", "outbox event already has an active lease")
                # An expired lease may be taken over by a new dispatcher. The
                # old dispatcher's mark_published/mark_failed will still fail
                # its lease-id check.
                self._clear_lease(record)
            seconds = (
                lease_seconds if lease_seconds is not None else self._lease_seconds
            )
            if seconds <= 0:
                raise HarnessError(422, "OBX-422", "outbox lease must be positive")
            record["_lease_id"] = f"lease_{uuid.uuid4().hex[:16]}"
            record["_lease_until"] = now + timedelta(seconds=seconds)
            return {
                "event_id": record["event_id"],
                "lease_id": record["_lease_id"],
                "lease_until": isoformat(record["_lease_until"]),
                "status": record["status"],
            }

    async def mark_published(self, event_id: str, lease_id: str) -> dict[str, Any]:
        async with self._lock:
            record = self._get_locked(event_id)
            self._validate_lease_locked(record, lease_id)
            if record["status"] not in {OUTBOX_PENDING, OUTBOX_RETRYING}:
                raise HarnessError(409, "OBX-409", "outbox event cannot transition to PUBLISHED")
            record["status"] = OUTBOX_PUBLISHED
            record["published_at"] = isoformat(self._clock())
            self._clear_lease(record)
            return self._safe_record(record)

    async def mark_failed(
        self,
        event_id: str,
        lease_id: str,
        *,
        retryable: bool = True,
        reason: str = "dispatch failed",
    ) -> dict[str, Any]:
        async with self._lock:
            record = self._get_locked(event_id)
            self._validate_lease_locked(record, lease_id)
            if record["status"] not in {OUTBOX_PENDING, OUTBOX_RETRYING}:
                raise HarnessError(409, "OBX-409", "outbox event cannot transition to retry")
            record["attempts"] += 1
            record["last_error"] = str(reason)[:200]
            if not retryable or record["attempts"] >= self._max_attempts:
                record["status"] = OUTBOX_DEAD_LETTER
                record["dead_lettered_at"] = isoformat(self._clock())
            else:
                record["status"] = OUTBOX_RETRYING
            self._clear_lease(record)
            return self._safe_record(record)

    async def consume(self, event_id: str) -> dict[str, Any]:
        async with self._lock:
            record = self._get_locked(event_id)
            if record["status"] != OUTBOX_PUBLISHED:
                raise HarnessError(409, "OBX-409", "only a published event can be consumed")
            record["status"] = OUTBOX_CONSUMED
            record["consumed_at"] = isoformat(self._clock())
            return self._safe_record(record)

    async def dead_letter(self, event_id: str, reason: str) -> dict[str, Any]:
        async with self._lock:
            record = self._get_locked(event_id)
            if record["status"] == OUTBOX_CONSUMED:
                raise HarnessError(409, "OBX-409", "consumed event cannot be dead-lettered")
            record["status"] = OUTBOX_DEAD_LETTER
            record["last_error"] = str(reason)[:200]
            record["dead_lettered_at"] = isoformat(self._clock())
            return self._safe_record(record)

    def get(self, event_id: str) -> dict[str, Any] | None:
        record = self._events.get(event_id)
        return self._safe_record(record) if record is not None else None

    def list_events(self) -> list[dict[str, Any]]:
        return [self._safe_record(record) for record in self._events.values()]

    def _get_locked(self, event_id: str) -> dict[str, Any]:
        try:
            event_id = require_nonempty(event_id, "event_id")
        except ValueError as exc:
            raise HarnessError(422, "OBX-422", str(exc)) from None
        record = self._events.get(event_id)
        if record is None:
            raise HarnessError(422, "OBX-422", "outbox event does not exist")
        return record

    def _validate_lease_locked(self, record: dict[str, Any], lease_id: str) -> None:
        current = record.get("_lease_id")
        if not current or current != lease_id:
            raise HarnessError(409, "OBX-409", "outbox dispatch lease does not match")
        lease_until = record.get("_lease_until")
        if lease_until is None or _as_utc(self._clock()) > _as_utc(lease_until):
            raise HarnessError(410, "OBX-410", "outbox dispatch lease has expired")

    @staticmethod
    def _clear_lease(record: dict[str, Any]) -> None:
        record.pop("_lease_id", None)
        record.pop("_lease_until", None)

    @staticmethod
    def _safe_record(record: dict[str, Any]) -> dict[str, Any]:
        return deepcopy({key: value for key, value in record.items() if not key.startswith("_")})


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
