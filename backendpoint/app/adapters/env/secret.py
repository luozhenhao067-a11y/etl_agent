"""SecretPort implementation backed by environment variables.

The operator fills the connection DSNs into the process environment
(``harness/.env``); the platform never persists credential material. A
reference such as ``secret://connections/conn_demo_001`` maps to a
deterministic variable name (``SECRET_CONNECTIONS_CONN_DEMO_001``) that is
read only at materialisation time — never logged, never stored, and failing
closed (SECRET-503) when unset.
"""

from __future__ import annotations

import os
import re
from typing import Any

from app.core.harness.errors import HarnessError

_REF_RE = re.compile(r"^secret://connections/([A-Za-z0-9_.-]+)$")


def env_var_name_for(secret_ref: str) -> str:
    """Deterministic env-var name for a secret reference."""

    match = _REF_RE.fullmatch(secret_ref)
    if match is None:
        raise HarnessError(
            422, "SECRET-422", "unsupported secret reference", {"ref": secret_ref}
        )
    return "SECRET_" + re.sub(r"[^A-Z0-9]", "_", match.group(1).upper())


class EnvSecretAdapter:
    """SecretProvider over process environment variables (Vault in production)."""

    async def materialize(self, secret_ref: str, context: dict[str, Any]) -> str:
        name = env_var_name_for(secret_ref)
        value = os.getenv(name)
        if not value or not value.strip():
            raise HarnessError(
                503,
                "SECRET-503",
                "secret reference is not configured",
                {"ref": secret_ref, "variable": name},
            )
        return value.strip()

    async def get_ref(self, secret_ref: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        env_var_name_for(secret_ref)  # validates the reference shape
        name = env_var_name_for(secret_ref)
        configured = bool(os.getenv(name))
        # Only reference metadata and state — never the secret value.
        return {"ref": secret_ref, "state": "configured" if configured else "not_configured", "variable": name}


__all__ = ["EnvSecretAdapter", "env_var_name_for"]
