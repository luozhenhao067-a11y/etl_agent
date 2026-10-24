"""SecretProvider stub. Never returns secret material."""

from __future__ import annotations

from typing import Any

_NOT_READY = "SECRET_PROVIDER_NOT_READY"


class StubSecretAdapter:
    async def materialize(self, secret_ref: str, context: dict[str, Any]) -> str:
        raise NotImplementedError(_NOT_READY)

    async def get_ref(self, secret_ref: str) -> dict[str, Any]:
        raise NotImplementedError(_NOT_READY)
