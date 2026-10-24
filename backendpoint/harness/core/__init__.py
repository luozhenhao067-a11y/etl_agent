"""Harness core: durable counterparts of the ``app.core.harness`` state machines.

Importing this package is side-effect free; each module imports its own
dependencies (``redis`` is only needed by ``redis_client``/``replay_redis``).
"""

from __future__ import annotations

__all__: list[str] = []
