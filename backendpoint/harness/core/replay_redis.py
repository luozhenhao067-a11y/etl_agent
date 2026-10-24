"""Redis-backed atomic replay reservation (Spec 3.7 / 5.2).

Durable counterpart of ``app.core.harness.replay.ReplayGuard``: the state
machine semantics are identical, but the RESERVED/CONSUMED/REJECTED record
lives in Redis under ``harness:replay:<key>`` and the reservation is an atomic
``SET NX EX``. Redis removes the key at TTL, which realises EXPIRED.

Fail-closed contract: every Redis error — connection refused, timeout,
read-only replica — surfaces as ``RG-503`` and the business call is rejected.
The guard never degrades to an in-memory fallback, because that would silently
drop the single-consumption guarantee across processes (Spec 5.2: 存储不可用即
拒绝，不得降级放行).

State transitions are compare-and-set through a Lua script so two workers can
never consume the same key concurrently. The PostgreSQL unique-constraint
backstay remains with the execution path (``execution_runs.
capability_token_digest``); this guard is the atomic first line.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from redis import asyncio as aioredis
from redis.exceptions import RedisError

from app.core.harness.errors import HarnessError
from app.core.harness.models import (
    REPLAY_CONSUMED,
    REPLAY_EXPIRED,
    REPLAY_REJECTED,
    REPLAY_RESERVED,
    Clock,
    isoformat,
    require_nonempty,
    utcnow,
)
from app.core.utils import canonical_json

KEY_PREFIX = "harness:replay:"

# Compare-and-set: swap the stored record only if it is still the value the
# caller read. KEEPTTL preserves the original reservation expiry.
_CAS_LUA = """
local current = redis.call('GET', KEYS[1])
if not current then return 'MISSING' end
if current ~= ARGV[1] then return 'CONFLICT' end
redis.call('SET', KEYS[1], ARGV[2], 'KEEPTTL')
return 'OK'
"""

# If the key vanished between a failed NX and the read (expired in between),
# the reservation is simply retried; the bound only caps pathological races.
_RESERVE_ATTEMPTS = 3


class RedisReplayGuard:
    def __init__(
        self,
        client: aioredis.Redis,
        *,
        clock: Clock = utcnow,
        ttl_seconds: int = 300,
    ) -> None:
        self._client = client
        self._clock = clock
        self._ttl_seconds = ttl_seconds

    async def reserve(
        self,
        key: str,
        scope: str,
        *,
        ttl_seconds: int | None = None,
        kind: str = "capability",
    ) -> dict[str, Any]:
        try:
            return await self._reserve(key, scope, ttl_seconds=ttl_seconds, kind=kind)
        except RedisError as exc:
            raise HarnessError(503, "RG-503", "replay guard is unavailable") from exc

    async def consume(self, key: str) -> dict[str, Any]:
        try:
            return await self._consume(key)
        except RedisError as exc:
            raise HarnessError(503, "RG-503", "replay guard is unavailable") from exc

    async def reject(self, key: str, reason: str) -> dict[str, Any]:
        try:
            return await self._reject(key, reason)
        except RedisError as exc:
            raise HarnessError(503, "RG-503", "replay guard is unavailable") from exc

    async def get(self, key: str) -> dict[str, Any] | None:
        try:
            value = await self._client.get(KEY_PREFIX + str(key))
        except RedisError as exc:
            raise HarnessError(503, "RG-503", "replay guard is unavailable") from exc
        if value is None:
            return None
        return self._parse(value)

    async def sweep(self) -> int:
        """No-op: Redis expires keys itself (kept for adapter parity)."""

        return 0

    # -- implementations (RedisError propagates to the fail-closed wrapper) --

    async def _reserve(
        self,
        key: str,
        scope: str,
        *,
        ttl_seconds: int | None,
        kind: str,
    ) -> dict[str, Any]:
        try:
            key = require_nonempty(key, "replay key")
            scope = require_nonempty(scope, "replay scope")
        except ValueError as exc:
            raise HarnessError(422, "RG-422", str(exc)) from None
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl_seconds
        if ttl <= 0:
            raise HarnessError(422, "RG-422", "replay TTL must be positive")

        now = isoformat(self._clock())
        record = {
            "key": key,
            "scope": scope,
            "kind": kind,
            "state": REPLAY_RESERVED,
            "reserved_at": now,
            "expires_at": isoformat(self._clock() + timedelta(seconds=ttl)),
        }
        full_key = KEY_PREFIX + key
        value = canonical_json(record)
        for _ in range(_RESERVE_ATTEMPTS):
            placed = await self._client.set(full_key, value, nx=True, ex=ttl)
            if placed:
                return dict(record)
            existing = await self._client.get(full_key)
            if existing is None:
                continue
            parsed = self._parse(existing)
            if parsed.get("scope") != scope:
                raise HarnessError(409, "RG-409", "replay key is bound to a different scope")
            state = parsed.get("state")
            if state == REPLAY_EXPIRED:
                raise HarnessError(410, "RG-410", "replay key has expired")
            if state == REPLAY_REJECTED:
                raise HarnessError(409, "RG-409", "replay key was rejected")
            raise HarnessError(
                409,
                "RG-409",
                "replay key has already been reserved",
                {"state": state},
            )
        raise HarnessError(503, "RG-503", "replay guard contention, retry rejected")

    async def _consume(self, key: str) -> dict[str, Any]:
        try:
            key = require_nonempty(key, "replay key")
        except ValueError as exc:
            raise HarnessError(422, "RG-422", str(exc)) from None
        full_key = KEY_PREFIX + key

        current = await self._client.get(full_key)
        if current is None:
            raise HarnessError(422, "RG-422", "replay key is missing")
        record = self._parse(current)
        self._require_reserved(record)
        updated = {
            **record,
            "state": REPLAY_CONSUMED,
            "consumed_at": isoformat(self._clock()),
        }
        outcome = await self._cas(full_key, current, updated)
        if outcome == "OK":
            return updated
        # Lost the race: re-read once; anything but our reservation is a replay.
        current = await self._client.get(full_key)
        if current is None:
            raise HarnessError(422, "RG-422", "replay key is missing")
        record = self._parse(current)
        self._require_reserved(record)
        raise HarnessError(409, "RG-409", "replay key is not reserved")

    async def _reject(self, key: str, reason: str) -> dict[str, Any]:
        try:
            key = require_nonempty(key, "replay key")
        except ValueError as exc:
            raise HarnessError(422, "RG-422", str(exc)) from None
        full_key = KEY_PREFIX + key

        current = await self._client.get(full_key)
        if current is None:
            raise HarnessError(422, "RG-422", "replay key is missing")
        record = self._parse(current)
        if record.get("state") == REPLAY_CONSUMED:
            raise HarnessError(409, "RG-409", "replay key has already been consumed")
        updated = {
            **record,
            "state": REPLAY_REJECTED,
            "rejected_at": isoformat(self._clock()),
            "reject_reason": str(reason)[:200],
        }
        outcome = await self._cas(full_key, current, updated)
        if outcome == "OK":
            return updated
        current = await self._client.get(full_key)
        if current is None:
            raise HarnessError(422, "RG-422", "replay key is missing")
        return self._parse(current)

    # -- helpers --------------------------------------------------------------

    async def _cas(self, full_key: str, expected: str, updated: dict[str, Any]) -> str:
        outcome = await self._client.eval(
            _CAS_LUA, 1, full_key, expected, canonical_json(updated)
        )
        # redis-py decodes EVAL results under decode_responses, but not every
        # client/server combination does (fakeredis returns bytes); normalise
        # so the compare-and-set outcome is always a str.
        if isinstance(outcome, bytes):
            return outcome.decode("ascii", "replace")
        return str(outcome)

    @staticmethod
    def _require_reserved(record: dict[str, Any]) -> None:
        state = record.get("state")
        if state == REPLAY_CONSUMED:
            raise HarnessError(409, "RG-409", "replay key has already been consumed")
        if state != REPLAY_RESERVED:
            raise HarnessError(409, "RG-409", "replay key is not reserved")

    @staticmethod
    def _parse(value: str) -> dict[str, Any]:
        try:
            record = json.loads(value)
        except ValueError:
            raise HarnessError(
                503, "RG-503", "replay guard record is unreadable"
            ) from None
        if not isinstance(record, dict):
            raise HarnessError(503, "RG-503", "replay guard record is unreadable")
        return record


__all__ = ["RedisReplayGuard"]
