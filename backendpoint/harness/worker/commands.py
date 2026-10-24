"""In-process handoff of the plaintext capability token (Spec 5.5 step 4).

Spec 5.1 forbids persisting the token plaintext — only ``jti`` and
``token_digest`` enter the database — yet the Worker must receive the token
to verify it (Spec 5.5 step 6). The Commit orchestrator hands the freshly
issued token to this store immediately after its transaction commits; the
dispatcher pops it when the command is delivered. Entries expire with the
token itself (``exp = iat + 300``).

A process restart empties the store: pending commands then fail closed at
the Worker (CAP rejection → run failed → dead-letter). That is the intended
behaviour — a token that cannot be delivered is never silently retried, and
the only legitimate replacement is a fresh Prepare → Approve → Commit cycle.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

from app.core.harness.models import utcnow

Clock = Callable[..., datetime]

# Matches the capability TTL (Spec 5.1: exp = iat + 300).
TOKEN_TTL_SECONDS = 300


class PendingCommandStore:
    """Process-local ``execution_run_id → token`` handoff with TTL."""

    def __init__(
        self, *, clock: Clock = utcnow, ttl_seconds: int = TOKEN_TTL_SECONDS
    ) -> None:
        self._clock = clock
        self._ttl = timedelta(seconds=ttl_seconds)
        self._entries: dict[str, tuple[str, Any]] = {}

    def put(self, execution_run_id: str, token: str) -> None:
        """Hand the freshly issued plaintext token to the dispatcher."""
        if not execution_run_id or not token:
            raise ValueError("execution_run_id and token are required")
        self._entries[execution_run_id] = (token, self._clock() + self._ttl)

    def pop(self, execution_run_id: str) -> str | None:
        """Take the token for delivery; ``None`` when missing or expired."""
        entry = self._entries.pop(execution_run_id, None)
        if entry is None:
            return None
        token, expires_at = entry
        if self._clock() >= expires_at:
            return None
        return token

    def pending_count(self) -> int:
        """Diagnostics only — never exposes tokens."""
        now = self._clock()
        return sum(1 for _, expires_at in self._entries.values() if now < expires_at)


__all__ = ["PendingCommandStore", "TOKEN_TTL_SECONDS"]
