"""Atomic replay reservation (Spec 3.7 / 5.2).

This in-memory adapter implements the state machine and fail-closed contract.
Production still requires a Redis atomic reserve plus a PostgreSQL unique
constraint; the persistence window for ops keys remains pending. A deployment
must not treat this adapter as durable.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.harness.errors import HarnessError
from app.core.harness.models import (
    REPLAY_CONSUMED,
    REPLAY_EXPIRED,
    REPLAY_REJECTED,
    REPLAY_RESERVED,
    REPLAY_UNSEEN,
    Clock,
    isoformat,
    require_nonempty,
    utcnow,
)


class ReplayGuard:
    def __init__(
        self,
        *,
        clock: Clock = utcnow,
        ttl_seconds: int = 300,
        unavailable: bool = False,
    ) -> None:
        self._clock = clock
        self._ttl_seconds = ttl_seconds
        self._unavailable = unavailable
        self._records: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def reserve(
        self,
        key: str,
        scope: str,
        *,
        ttl_seconds: int | None = None,
        kind: str = "capability",
    ) -> dict[str, Any]:
        if self._unavailable:
            raise HarnessError(503, "RG-503", "replay guard is unavailable")
        try:
            key = require_nonempty(key, "replay key")
            scope = require_nonempty(scope, "replay scope")
        except ValueError as exc:
            raise HarnessError(422, "RG-422", str(exc)) from None
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl_seconds
        if ttl <= 0:
            raise HarnessError(422, "RG-422", "replay TTL must be positive")

        async with self._lock:
            now = _as_utc(self._clock())
            existing = self._records.get(key)
            if existing is not None:
                self._expire_locked(existing, now)
                if existing["state"] == REPLAY_EXPIRED:
                    raise HarnessError(
                        410,
                        "RG-410",
                        "replay key has expired",
                        {"key_kind": existing["kind"]},
                    )
                if existing["state"] == REPLAY_REJECTED:
                    raise HarnessError(409, "RG-409", "replay key was rejected")
                if existing["scope"] != scope:
                    raise HarnessError(
                        409,
                        "RG-409",
                        "replay key is bound to a different scope",
                    )
                raise HarnessError(
                    409,
                    "RG-409",
                    "replay key has already been reserved",
                    {"state": existing["state"]},
                )

            record = {
                "key": key,
                "scope": scope,
                "kind": kind,
                "state": REPLAY_RESERVED,
                "reserved_at": isoformat(now),
                "expires_at": isoformat(now + timedelta(seconds=ttl)),
                "_expires_at": now + timedelta(seconds=ttl),
            }
            self._records[key] = record
            return self._safe_record(record)

    async def consume(self, key: str) -> dict[str, Any]:
        if self._unavailable:
            raise HarnessError(503, "RG-503", "replay guard is unavailable")
        try:
            key = require_nonempty(key, "replay key")
        except ValueError as exc:
            raise HarnessError(422, "RG-422", str(exc)) from None
        async with self._lock:
            record = self._records.get(key)
            if record is None:
                raise HarnessError(422, "RG-422", "replay key is missing")
            now = _as_utc(self._clock())
            self._expire_locked(record, now)
            if record["state"] == REPLAY_EXPIRED:
                raise HarnessError(410, "RG-410", "replay key has expired")
            if record["state"] == REPLAY_CONSUMED:
                raise HarnessError(409, "RG-409", "replay key has already been consumed")
            if record["state"] != REPLAY_RESERVED:
                raise HarnessError(409, "RG-409", "replay key is not reserved")
            record["state"] = REPLAY_CONSUMED
            record["consumed_at"] = isoformat(now)
            return self._safe_record(record)

    async def reject(self, key: str, reason: str) -> dict[str, Any]:
        if self._unavailable:
            raise HarnessError(503, "RG-503", "replay guard is unavailable")
        async with self._lock:
            record = self._records.get(key)
            if record is None:
                raise HarnessError(422, "RG-422", "replay key is missing")
            now = _as_utc(self._clock())
            self._expire_locked(record, now)
            if record["state"] == REPLAY_EXPIRED:
                raise HarnessError(410, "RG-410", "replay key has expired")
            if record["state"] == REPLAY_CONSUMED:
                raise HarnessError(409, "RG-409", "replay key has already been consumed")
            record["state"] = REPLAY_REJECTED
            record["rejected_at"] = isoformat(now)
            record["reject_reason"] = str(reason)[:200]
            return self._safe_record(record)

    def get(self, key: str) -> dict[str, Any] | None:
        record = self._records.get(key)
        if record is None:
            return None
        self._expire_locked(record, _as_utc(self._clock()))
        return self._safe_record(record)

    async def sweep(self) -> int:
        async with self._lock:
            now = _as_utc(self._clock())
            expired = 0
            for record in self._records.values():
                self._expire_locked(record, now)
                if record["state"] == REPLAY_EXPIRED:
                    expired += 1
            return expired

    @staticmethod
    def _expire_locked(record: dict[str, Any], now: datetime) -> None:
        if record["state"] in {REPLAY_CONSUMED, REPLAY_REJECTED, REPLAY_EXPIRED}:
            return
        if now >= _as_utc(record["_expires_at"]):
            record["state"] = REPLAY_EXPIRED
            record["expired_at"] = isoformat(now)

    @staticmethod
    def _safe_record(record: dict[str, Any]) -> dict[str, Any]:
        return deepcopy({key: value for key, value in record.items() if not key.startswith("_")})


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# Re-exported for state-machine tests and callers that build guards by kind.
__all__ = ["ReplayGuard", "REPLAY_UNSEEN"]
