"""KernelHarnessAdapter: the real HarnessPort over the kernel components.

Selected by ``HARNESS=kernel`` (user-approved 2026-10-24). Kernel mode is only
booted with ``STORAGE=postgres`` plus ``DATABASE_URL``, ``REDIS_URL`` and the
Ed25519 signing keys — build_container fails fast when any of them is missing,
and at request time every component failure surfaces as a fail-closed
HarnessError carrying its Spec 3.10 code (PDP-*/CAP-*/RG-*/OBX-*/EL-*).

Persistence split:

- PDP decisions, capability issuance/verification and ad-hoc ledger appends
  each commit in their own short transaction through the SQL Evidence Ledger
  (``harness/core/ledger_sql.py``), which is the ONLY legitimate writer of the
  audit_events hash chain in kernel mode.
- The API-14 Commit flow does NOT pass through here: ``commit_tx.py`` owns the
  single atomic transaction (execution_runs + Outbox + audit events).
- The kernel's in-memory demo components (ReplayGuard, InMemoryOutbox,
  EvidenceLedger) are not used for persistence; only its PDP and
  CapabilityService are.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from sqlalchemy.exc import SQLAlchemyError

from app.core.harness.errors import HarnessError
from app.core.harness.kernel import HarnessKernel
from app.core.utils import digest_of
from harness.core.ledger_sql import SqlLedger
from harness.core.outbox_sql import SqlOutbox
from harness.core.replay_redis import RedisReplayGuard

# Session factory: sessionmaker or any callable returning a SQLAlchemy Session.
SessionFactory = Callable[[], Any]

_logger = logging.getLogger("etl.harness")


class KernelHarnessAdapter:
    """HarnessPort implementation for kernel mode (Spec 3.3-3.9)."""

    def __init__(
        self,
        *,
        kernel: HarnessKernel,
        session_factory: SessionFactory,
        replay: RedisReplayGuard,
        outbox: SqlOutbox,
        ledger: SqlLedger,
    ) -> None:
        self._kernel = kernel
        self._session_factory = session_factory
        self._replay = replay
        self._outbox = outbox
        self._ledger = ledger

    # -- HarnessPort ----------------------------------------------------------

    async def pdp_decide(self, intent: dict[str, Any]) -> dict[str, Any]:
        """Evaluate a ToolIntent (Spec 3.4) and record the decision.

        A DENY decision is recorded and then raised as ``PDP-403`` — the
        adapter never returns a denial for the caller to ignore.
        """
        try:
            decision = self._kernel.pdp.decide(intent)
        except HarnessError as exc:
            await self._record_denial(intent, exc)
            raise
        await self._append_entry(
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
        if decision["decision"] != "ALLOW":
            raise HarnessError(
                403,
                "PDP-403",
                "policy decision denied",
                {
                    "decision_digest": decision["decision_digest"],
                    "risk_level": decision["risk_level"],
                },
            )
        return decision

    async def issue_capability(self, claims: dict[str, Any]) -> dict[str, Any]:
        """Issue a single-use Ed25519 capability (Spec 3.5)."""
        tool = claims.get("tool") if isinstance(claims, dict) else None
        spec = self._kernel.pdp.tool_spec(tool) if isinstance(tool, str) else None
        if isinstance(tool, str) and spec is None:
            raise HarnessError(
                422, "CAP-422", "tool is not registered", {"field": "tool"}
            )
        issued = self._kernel.capability.issue(
            claims,
            approval_facts=claims.get("approval_facts")
            if isinstance(claims, dict)
            else None,
            required_slots=spec.required_slots if spec is not None else None,
        )
        await self._append_entry(
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
        self, capability: str, claims: dict[str, Any]
    ) -> dict[str, Any]:
        """Verify a capability token against its declared scope (Spec 5.1)."""
        verified = self._kernel.capability.verify(capability, claims or None)
        await self._append_entry(
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

    async def replay_guard_check(self, key: str, scope: str) -> None:
        """Atomically reserve a replay-guard key or raise (Spec 3.7/5.2)."""
        await self._replay.reserve(key, scope, kind="ops")

    async def execute_tool(
        self,
        intent: dict[str, Any],
        *,
        policy_decision: dict[str, Any] | None,
        capability_token: str | None = None,
        idempotency_key: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Run one registered tool through the Tool Broker (Spec 3.6).

        The kernel verifies the recorded policy decision against this exact
        intent, then invokes the registered handler and appends
        ``tool.call.executed`` / ``tool.call.rejected`` to the ledger.
        """
        return await self._kernel.execute_tool(
            intent,
            policy_decision=policy_decision,
            capability_token=capability_token,
            idempotency_key=idempotency_key,
            timeout_seconds=timeout_seconds,
        )

    async def write_outbox(self, event: dict[str, Any]) -> str:
        """Write one outbox event in its own transaction (Spec 3.8).

        The Commit flow does not use this method — it enqueues inside the
        atomic transaction owned by ``commit_tx.CommitOrchestrator``.
        """
        session = self._session_factory()
        try:
            record = await self._outbox.enqueue(session, event)
            session.commit()
        except HarnessError:
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            session.rollback()
            raise HarnessError(503, "OBX-503", "outbox write failed") from exc
        finally:
            session.close()
        return record["event_id"]

    async def append_ledger(self, event: dict[str, Any]) -> str:
        """Append one audit event to the SQL hash chain (Spec 3.9)."""
        entry = await self._append_entry(event)
        return entry["id"]

    # -- helpers ----------------------------------------------------------------

    async def _append_entry(self, event: dict[str, Any]) -> dict[str, Any]:
        session = self._session_factory()
        try:
            entry = await self._ledger.append(session, event)
            session.commit()
        except HarnessError:
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            session.rollback()
            raise HarnessError(500, "EL-500", "evidence ledger write failed") from exc
        finally:
            session.close()
        return entry

    async def _record_denial(
        self, intent: dict[str, Any], exc: HarnessError
    ) -> None:
        """Log a malformed/failed PDP evaluation without a ledger write.

        ``pdp.denied`` is not in the Spec 12.2 audit catalogue, and contract
        §9.2 forbids persisting unregistered event types until confirmed —
        so the denial is only logged here. It still fails closed: the raised
        ``PDP-*`` error is the caller-visible outcome, and a DENY decision
        that completes evaluation is durably recorded as the registered
        ``pdp.decision.recorded``.
        """
        actor_id = (
            (intent.get("actor_id") or intent.get("sub"))
            if isinstance(intent, dict)
            else None
        )
        _logger.warning(
            "pdp evaluation denied: error_code=%s tool=%s project_id=%s actor_id=%s",
            exc.error_code,
            intent.get("tool") if isinstance(intent, dict) else None,
            intent.get("project_id") if isinstance(intent, dict) else None,
            actor_id,
        )


__all__ = ["KernelHarnessAdapter", "SessionFactory"]
