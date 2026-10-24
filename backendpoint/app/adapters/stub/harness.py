"""Harness stub. Every method fails closed; no success is fabricated."""

from __future__ import annotations

from typing import Any

_NOT_READY = "HARNESS_NOT_READY"


class StubHarnessAdapter:
    async def pdp_decide(self, intent: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(_NOT_READY)

    async def execute_tool(
        self,
        intent: dict[str, Any],
        *,
        policy_decision: dict[str, Any] | None,
        capability_token: str | None = None,
        idempotency_key: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError(_NOT_READY)

    async def issue_capability(self, claims: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(_NOT_READY)

    async def verify_capability(
        self, capability: str, claims: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError(_NOT_READY)

    async def replay_guard_check(self, key: str, scope: str) -> None:
        raise NotImplementedError(_NOT_READY)

    async def write_outbox(self, event: dict[str, Any]) -> str:
        raise NotImplementedError(_NOT_READY)

    async def append_ledger(self, event: dict[str, Any]) -> str:
        raise NotImplementedError(_NOT_READY)
