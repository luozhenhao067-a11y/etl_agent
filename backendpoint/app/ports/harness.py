"""Harness boundary.

The API layer never implements PDP, capability issuance/verification, replay
protection, outbox writes, or ledger appends inline. It may only call this
port. The only adapter injected in the current API delivery is a stub that
raises ``NotImplementedError("HARNESS_NOT_READY")``. The kernel adapter in
``app.adapters.memory.harness`` is available for local Harness execution and
tests, but is not wired to the API until the Commit transaction boundary is
settled.
"""

from __future__ import annotations

from typing import Any, Protocol


class HarnessPort(Protocol):
    async def pdp_decide(self, intent: dict[str, Any]) -> dict[str, Any]:
        """Return a policy decision for a ToolIntent."""
        ...

    async def execute_tool(
        self,
        intent: dict[str, Any],
        *,
        policy_decision: dict[str, Any] | None,
        capability_token: str | None = None,
        idempotency_key: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Run a registered tool through the Tool Broker (Spec 3.6).

        The intent must be the exact object the policy decision was made for.
        The result carries the broker verdict (status/domain_code), the output
        digest and the handler's sanitized output.
        """
        ...

    async def issue_capability(self, claims: dict[str, Any]) -> dict[str, Any]:
        """Issue a single-use execution capability."""
        ...

    async def verify_capability(
        self, capability: str, claims: dict[str, Any]
    ) -> dict[str, Any]:
        """Verify a capability token against its declared scope."""
        ...

    async def replay_guard_check(self, key: str, scope: str) -> None:
        """Atomically reserve a replay-guard key or raise."""
        ...

    async def write_outbox(self, event: dict[str, Any]) -> str:
        """Write an outbox event atomically with the business fact."""
        ...

    async def append_ledger(self, event: dict[str, Any]) -> str:
        """Append an audit event to the Evidence Ledger."""
        ...
