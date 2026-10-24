"""In-memory Harness adapter for local execution and kernel tests.

This adapter is deliberately not injected into the API container. Commit's
``execution_runs`` + Outbox + Ledger transaction is blocked by P-06, so wiring
the adapter into the API would imply atomicity that does not exist.
"""

from __future__ import annotations

from typing import Any

from app.core.harness.kernel import HarnessKernel


class InMemoryHarnessAdapter:
    def __init__(self, kernel: HarnessKernel | None = None) -> None:
        self.kernel = kernel or HarnessKernel()

    async def pdp_decide(self, intent: dict[str, Any]) -> dict[str, Any]:
        return await self.kernel.decide(intent)

    async def issue_capability(self, claims: dict[str, Any]) -> dict[str, Any]:
        return await self.kernel.issue_capability(
            claims,
            approval_facts=claims.get("approval_facts"),
        )

    async def verify_capability(
        self, capability: str, claims: dict[str, Any]
    ) -> dict[str, Any]:
        return await self.kernel.verify_capability(capability, claims)

    async def replay_guard_check(self, key: str, scope: str) -> None:
        await self.kernel.replay.reserve(key, scope, kind="ops")

    async def write_outbox(self, event: dict[str, Any]) -> str:
        record = await self.kernel.enqueue_outbox(event)
        return record["event_id"]

    async def append_ledger(self, event: dict[str, Any]) -> str:
        record = await self.kernel.append_ledger(event)
        return record["id"]
