"""Harness kernel composition.

The kernel wires PDP, Capability, Replay Guard, Tool Broker, Outbox and Ledger
for local execution and tests. It is intentionally not injected into the API
container yet: the Commit transaction boundary and Outbox persistence are
blocked by P-06, and the API delivery still fails closed at its existing
dependency checks.
"""

from __future__ import annotations

from typing import Any

from app.core.harness.broker import ToolBroker
from app.core.harness.capability import CapabilityService
from app.core.harness.errors import HarnessError
from app.core.harness.ledger import EvidenceLedger
from app.core.harness.models import Clock, utcnow
from app.core.harness.outbox import InMemoryOutbox
from app.core.harness.pdp import PolicyDecisionPoint
from app.core.harness.replay import ReplayGuard
from app.core.utils import digest_of, now_iso


class HarnessKernel:
    def __init__(
        self,
        *,
        pdp: PolicyDecisionPoint | None = None,
        capability: CapabilityService | None = None,
        replay: ReplayGuard | None = None,
        broker: ToolBroker | None = None,
        outbox: InMemoryOutbox | None = None,
        ledger: EvidenceLedger | None = None,
        clock: Clock = utcnow,
    ) -> None:
        self._clock = clock
        self.pdp = pdp or PolicyDecisionPoint(clock=clock)
        self.capability = capability or CapabilityService(clock=clock)
        self.replay = replay or ReplayGuard(clock=clock)
        self.broker = broker or ToolBroker(
            capability=self.capability, replay=self.replay, pdp=self.pdp
        )
        self.outbox = outbox or InMemoryOutbox(clock=clock)
        self.ledger = ledger or EvidenceLedger(clock=clock)

    async def decide(self, intent: dict[str, Any]) -> dict[str, Any]:
        try:
            decision = self.pdp.decide(intent)
        except HarnessError as exc:
            actor_id = (
                (intent.get("actor_id") or intent.get("sub"))
                if isinstance(intent, dict)
                else None
            )
            if isinstance(intent, dict) and intent.get("project_id") and actor_id:
                await self.append_ledger(
                    {
                        "project_id": intent["project_id"],
                        "actor_id": actor_id,
                        "event_type": "pdp.denied",
                        "resource_type": "tool_intent",
                        "resource_id": str(intent.get("tool") or "unknown"),
                        "payload_digest": digest_of(
                            {"error_code": exc.error_code, "tool": intent.get("tool")}
                        ),
                    }
                )
            raise
        else:
            await self.append_ledger(
                {
                    "project_id": decision["project_id"],
                    "actor_id": decision["actor_id"],
                    "event_type": "pdp.decision.recorded",
                    "resource_type": "pdp_decision",
                    "resource_id": decision["decision_digest"],
                    "payload_digest": digest_of(
                        {
                            "decision": decision["decision"],
                            "risk_level": decision["risk_level"],
                            "policy_version": decision["policy_version"],
                        }
                    ),
                }
            )
            return decision

    async def issue_capability(
        self,
        claims: dict[str, Any],
        *,
        approval_facts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        tool = claims.get("tool") if isinstance(claims, dict) else None
        spec = self.pdp.tool_spec(tool) if isinstance(tool, str) else None
        if isinstance(tool, str) and spec is None:
            raise HarnessError(
                422,
                "CAP-422",
                "tool is not registered",
                {"field": "tool"},
            )
        issued = self.capability.issue(
            claims,
            approval_facts=approval_facts,
            required_slots=spec.required_slots if spec is not None else None,
        )
        await self.append_ledger(
            {
                "project_id": issued["claims"]["project_id"],
                "actor_id": issued["claims"]["sub"],
                "event_type": "capability.issued",
                "resource_type": "capability",
                "resource_id": issued["jti"],
                "payload_digest": digest_of(
                    {
                        "preparation_id": issued["claims"]["preparation_id"],
                        "execution_run_id": issued["claims"]["execution_run_id"],
                        "tool": issued["claims"]["tool"],
                    }
                ),
            }
        )
        return issued

    async def verify_capability(
        self, token: str, expected_claims: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            verified = self.capability.verify(token, expected_claims)
        except HarnessError:
            raise
        await self.append_ledger(
            {
                "project_id": verified["claims"]["project_id"],
                "actor_id": verified["claims"]["sub"],
                "event_type": "capability.verified",
                "resource_type": "capability",
                "resource_id": verified["jti"],
                "payload_digest": digest_of(
                    {"tool": verified["claims"]["tool"], "status": verified["status"]}
                ),
            }
        )
        return verified

    async def execute_tool(
        self,
        intent: dict[str, Any],
        *,
        policy_decision: dict[str, Any] | None,
        capability_token: str | None = None,
        idempotency_key: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        try:
            result = await self.broker.execute(
                intent,
                policy_decision=policy_decision,
                capability_token=capability_token,
                idempotency_key=idempotency_key,
                timeout_seconds=timeout_seconds,
            )
        except HarnessError as exc:
            project_id = intent.get("project_id") if isinstance(intent, dict) else None
            actor_id = (
                (intent.get("actor_id") or intent.get("sub"))
                if isinstance(intent, dict)
                else None
            )
            if project_id and actor_id:
                await self.append_ledger(
                    {
                        "project_id": project_id,
                        "actor_id": actor_id,
                        "event_type": "tool.call.rejected",
                        "resource_type": "tool_call",
                        "resource_id": str(
                            intent.get("execution_run_id") or intent.get("tool") or "unknown"
                        ),
                        "payload_digest": digest_of(
                            {
                                "tool": intent.get("tool"),
                                "error_code": exc.error_code,
                            }
                        ),
                    }
                )
            raise
        event_type = (
            "tool.call.executed"
            if result["status"] in {"SUCCEEDED", "FAILED"}
            else "tool.call.unknown"
        )
        entry = await self.append_ledger(
            {
                "project_id": intent["project_id"],
                "actor_id": intent.get("actor_id") or intent.get("sub"),
                "event_type": event_type,
                "resource_type": "tool_call",
                "resource_id": str(intent.get("execution_run_id") or intent["tool"]),
                "payload_digest": digest_of(
                    {
                        "tool": result["tool"],
                        "status": result["status"],
                        "domain_code": result["domain_code"],
                        "output_digest": result["output_digest"],
                    }
                ),
            }
        )
        return {**result, "audit_event_id": entry["id"]}

    async def enqueue_outbox(
        self, event: dict[str, Any], *, project_id: str | None = None
    ) -> dict[str, Any]:
        record = await self.outbox.enqueue(event)
        if project_id:
            await self.append_ledger(
                {
                    "project_id": project_id,
                    "actor_id": event.get("actor_id", "service"),
                    "event_type": "outbox.event.created",
                    "resource_type": "outbox_event",
                    "resource_id": record["event_id"],
                    "payload_digest": record["payload_digest"],
                }
            )
        return record

    async def append_ledger(self, event: dict[str, Any]) -> dict[str, Any]:
        return await self.ledger.append(event)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "components": [
                {"name": "pdp", "status": "ok"},
                {"name": "capability", "status": "ok"},
                {"name": "replay_guard", "status": "ok"},
                {"name": "tool_broker", "status": "ok"},
                {"name": "outbox", "status": "ok"},
                {"name": "ledger", "status": "ok"},
            ],
            "time": now_iso(),
        }


__all__ = ["HarnessKernel"]
