"""Redis replay guard tests: atomic replay rejection, TTL, fail-closed.

Covers Spec 3.7 / 5.2 and the user-approved requirement: Redis SET NX EX
atomic reservation, duplicates intercepted immediately, and Redis
unavailability must fail closed (RG-503), never fall through.
"""

from __future__ import annotations

import asyncio

import pytest
from fakeredis import FakeAsyncRedis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.harness.errors import HarnessError
from harness.core.replay_redis import RedisReplayGuard


class _BrokenRedis(FakeAsyncRedis):
    """Pretends Redis is unreachable: every command raises."""

    def _raise(self, *args, **kwargs):
        raise RedisConnectionError("redis down")

    async def set(self, *args, **kwargs):
        self._raise()

    async def get(self, *args, **kwargs):
        self._raise()

    async def eval(self, *args, **kwargs):
        self._raise()


async def test_first_request_reserved_second_rejected(replay_guard):
    first = await replay_guard.reserve("key-1", "cancel:ops1:run_1")
    assert first["state"] == "RESERVED"

    with pytest.raises(HarnessError) as replay:
        await replay_guard.reserve("key-1", "cancel:ops1:run_1")
    assert replay.value.error_code == "RG-409"
    assert replay.value.status_code == 409


async def test_same_key_with_different_scope_is_rejected(replay_guard):
    await replay_guard.reserve("key-2", "cancel:ops1:run_1")
    with pytest.raises(HarnessError) as conflict:
        await replay_guard.reserve("key-2", "rollback:ops1:run_1")
    assert conflict.value.error_code == "RG-409"


async def test_consumed_key_still_rejects_replays(replay_guard):
    await replay_guard.reserve("key-3", "scope-a")
    await replay_guard.consume("key-3")

    with pytest.raises(HarnessError) as replay:
        await replay_guard.reserve("key-3", "scope-a")
    assert replay.value.error_code == "RG-409"


async def test_expired_key_frees_the_slot():
    guard = RedisReplayGuard(FakeAsyncRedis(), ttl_seconds=1)
    await guard.reserve("key-4", "scope-a")

    await asyncio.sleep(1.05)
    # The Redis TTL expired the reservation, so the retry succeeds.
    renewed = await guard.reserve("key-4", "scope-a")
    assert renewed["state"] == "RESERVED"


async def test_rejected_key_blocks_reuse(replay_guard):
    await replay_guard.reserve("key-5", "scope-a")
    await replay_guard.reject("key-5", "operation aborted")

    with pytest.raises(HarnessError) as rejected:
        await replay_guard.reserve("key-5", "scope-a")
    assert rejected.value.error_code == "RG-409"


async def test_unavailable_redis_fails_closed():
    guard = RedisReplayGuard(_BrokenRedis())
    with pytest.raises(HarnessError) as unavailable:
        await guard.reserve("key-6", "scope-a")
    assert unavailable.value.error_code == "RG-503"
    assert unavailable.value.status_code == 503
