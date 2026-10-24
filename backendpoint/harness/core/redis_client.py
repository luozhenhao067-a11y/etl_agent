"""Redis connection factory for the Harness Replay Guard (Spec 3.7 / 5.2).

Mirrors ``app.db.session``: the connection string is read from the environment
only, no credentials are hardcoded, and the URL is validated before use. The
client returned here is the shared connection pool — callers must not build a
second Redis connection layer (project constraint).

The asyncio API is used because every Harness port call is awaited; a sync
client would block the event loop on each atomic command.
"""

from __future__ import annotations

import os

from redis import asyncio as aioredis

# Fail-closed budget: a dead Redis must surface as RG-503 within seconds
# instead of hanging the request path.
CONNECT_TIMEOUT_SECONDS = 2.0
SOCKET_TIMEOUT_SECONDS = 2.0

_URL_PREFIXES = ("redis://", "rediss://", "unix://")


def redis_url() -> str:
    """Return the validated ``REDIS_URL`` (environment-only, like DATABASE_URL)."""

    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        raise RuntimeError("REDIS_URL is required, e.g. redis://localhost:6379/0")
    return validate_url(url)


def validate_url(url: str) -> str:
    """Reject anything that is not a Redis connection URL."""

    if not url.startswith(_URL_PREFIXES):
        raise RuntimeError(
            "REDIS_URL must use redis://, rediss:// or unix://; got: "
            + url.split("://", 1)[0] + "://"
        )
    return url


def create_redis_client(url: str | None = None) -> aioredis.Redis:
    """Create the shared asyncio Redis client (responses decoded as ``str``).

    ``url`` overrides the environment for one-off callers (tests); production
    code always goes through ``redis_url()``.
    """

    return aioredis.Redis.from_url(
        url if url is not None else redis_url(),
        decode_responses=True,
        socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
        socket_timeout=SOCKET_TIMEOUT_SECONDS,
        health_check_interval=30,
    )


__all__ = ["create_redis_client", "redis_url", "validate_url"]
