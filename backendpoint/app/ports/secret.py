"""SecretProvider boundary (Vault KV v2 in production)."""

from __future__ import annotations

from typing import Any, Protocol


class SecretPort(Protocol):
    async def materialize(self, secret_ref: str, context: dict[str, Any]) -> str:
        """Return a short-lived secret value for a managed execution context."""
        ...

    async def get_ref(self, secret_ref: str) -> dict[str, Any]:
        """Return only reference metadata and state, never the secret value."""
        ...
