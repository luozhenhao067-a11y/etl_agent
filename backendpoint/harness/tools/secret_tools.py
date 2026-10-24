"""``secret.materialize`` tool adapter (Spec 8.14, P0).

The broker requires a bound execution capability for this tool, so only a
verified single-use execution context (preparation + run + artifact digest)
can materialise a credential. The intent carries the ``connection_id`` only
(a raw ``secret://`` reference would trip the credential-material guard);
the handler derives the reference internally. The value is returned only on
the in-process worker path; the Evidence Ledger records the output digest,
never the value.
"""

from __future__ import annotations

from typing import Any

from app.core.harness.errors import HarnessError


def make_secret_materialize_handler(*, secret: Any) -> Any:
    async def handler(intent: dict[str, Any]) -> dict[str, Any]:
        scope = intent.get("resource_scope") or {}
        connection_id = scope.get("connection_id")
        if not isinstance(connection_id, str) or not connection_id.strip():
            raise HarnessError(400, "TB-400", "connection_id is required")
        context = {
            "preparation_id": intent.get("preparation_id"),
            "execution_run_id": intent.get("execution_run_id"),
            "environment": intent.get("environment"),
        }
        value = await secret.materialize(
            f"secret://connections/{connection_id.strip()}", context
        )
        return {"secret_value": value}

    return handler


__all__ = ["make_secret_materialize_handler"]
