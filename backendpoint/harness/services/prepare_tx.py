"""API-12 Prepare orchestrator (Spec 4.2; P-04 confirmed 2026-10-24).

Runs only in kernel mode (``container.prepare``), mirroring the Commit
orchestrator: the endpoint keeps RBAC, the deterministic-gate checks, the
Idempotency-Key handling and the PDP call; this service owns the durable
Preparation transaction:

1. Content-level idempotency: the same ``version_id + fingerprint`` returns
   the same Preparation; a different fingerprint for the same version is
   ``PREP-409 FINGERPRINT_CONFLICT`` (Spec 4.2 幂等).
2. Duty-slot assignment from ``project_role_grants``: one holder per
   ``data_checker`` / ``security_checker``, neither equals the applicant and
   the two must be distinct — otherwise ``PREP-409 NO_ELIGIBLE_APPROVER``
   and nothing is written.
3. ONE PostgreSQL transaction inserts the Preparation row (frozen facts),
   the two ``approval_requests`` (``PENDING``) and the ``preparation.created``
   / ``approval.slot.assigned`` ledger events. The PDP decision is bound to
   the Preparation (Spec 3.4 ``BOUND_TO_PREPARATION``) before the writes.

The endpoint mirrors the returned dict into ``container.state.preparations``
(the memory read model used by approve/commit), so memory mode keeps working
unchanged and SQL rows are only absent for the seeded demo preparations.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from app.core.harness.errors import HarnessError
from app.core.harness.kernel import HarnessKernel
from app.core.harness.models import Clock, isoformat, utcnow
from app.core.utils import digest_of, new_id
from app.models.tables import ApprovalRequest, Preparation, ProjectRoleGrant
from harness.core.ledger_sql import SqlLedger
from harness.services.gateway import SessionFactory

REQUIRED_SLOTS = ("data_checker", "security_checker")
_PREPARATION_STATUS = "PREPARED"


class PrepareOrchestrator:
    """Prepare transaction boundary; injected as ``container.prepare``."""

    def __init__(
        self,
        *,
        kernel: HarnessKernel,
        session_factory: SessionFactory,
        ledger: SqlLedger,
        environment: str,
        clock: Clock = utcnow,
    ) -> None:
        self._kernel = kernel
        self._session_factory = session_factory
        self._ledger = ledger
        self._environment = environment
        self._clock = clock

    async def create(
        self,
        *,
        version: dict[str, Any],
        project_id: str,
        applicant_id: str,
        fingerprint: str,
        request_facts: dict[str, Any],
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        """Create (or idempotently return) the Preparation with its slots."""
        version_id = version["version_id"]
        preparation_id = new_id("prep")
        rollback_plan = self._derive_rollback_plan(version)

        # Spec 3.4: bind the evaluated decision to this preparation before
        # any durable write happens.
        try:
            self._kernel.pdp.bind_to_preparation(
                decision["decision_digest"], preparation_id
            )
        except (KeyError, ValueError):
            raise HarnessError(
                422, "PREP-422", "pdp decision cannot be bound to a preparation"
            ) from None

        now = self._clock()
        session = self._session_factory()
        try:
            existing = session.execute(
                select(Preparation).where(Preparation.version_id == version_id)
            ).scalar_one_or_none()
            if existing is not None:
                if existing.fingerprint == fingerprint:
                    return self._existing_result(session, existing)
                raise HarnessError(
                    409,
                    "PREP-409",
                    "version already has a preparation with a different fingerprint",
                    {"reason": "FINGERPRINT_CONFLICT"},
                )

            slots = self._assign_slots(session, project_id, applicant_id)
            approval_ids = []
            for slot in slots:
                approval_id = new_id("apr")
                approval_ids.append(approval_id)
                session.add(
                    ApprovalRequest(
                        id=approval_id,
                        preparation_id=preparation_id,
                        version_id=version_id,
                        required_role=slot["role_slot"],
                        # The assigned grantee is recorded at creation; the
                        # decision later confirms the same (role-gated) user.
                        approver_id=slot["approver_id"],
                        status="PENDING",
                        created_at=now,
                        updated_at=now,
                    )
                )
            session.add(
                Preparation(
                    id=preparation_id,
                    version_id=version_id,
                    project_id=project_id,
                    applicant_id=applicant_id,
                    status=_PREPARATION_STATUS,
                    risk_level=decision["risk_level"],
                    fingerprint=fingerprint,
                    artifact_digest=version.get("artifact_digest"),
                    environment=self._environment,
                    resource_scope={
                        "version_id": version_id,
                        "pipeline_id": version.get("pipeline_id"),
                    },
                    budget=request_facts.get("budget"),
                    schedule=request_facts.get("schedule"),
                    quality_contract_ref=request_facts.get("quality_contract_ref"),
                    rollback_plan=rollback_plan,
                    decision_digest=decision["decision_digest"],
                    created_at=now,
                    updated_at=now,
                )
            )
            await self._ledger.append(
                session,
                {
                    "project_id": project_id,
                    "actor_id": applicant_id,
                    "event_type": "preparation.created",
                    "resource_type": "preparation",
                    "resource_id": preparation_id,
                    "payload_digest": digest_of(
                        {
                            "preparation_id": preparation_id,
                            "version_id": version_id,
                            "fingerprint": fingerprint,
                            "risk_level": decision["risk_level"],
                        }
                    ),
                },
            )
            for slot, approval_id in zip(slots, approval_ids):
                await self._ledger.append(
                    session,
                    {
                        "project_id": project_id,
                        "actor_id": applicant_id,
                        "event_type": "approval.slot.assigned",
                        "resource_type": "approval_request",
                        "resource_id": approval_id,
                        "payload_digest": digest_of(slot),
                    },
                )
            session.commit()
        except HarnessError:
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            session.rollback()
            raise HarnessError(503, "PREP-503", "prepare transaction failed") from exc
        finally:
            session.close()

        mirror = {
            "preparation_id": preparation_id,
            "version_id": version_id,
            "project_id": project_id,
            "applicant_id": applicant_id,
            "status": _PREPARATION_STATUS,
            "risk_level": decision["risk_level"],
            "fingerprint": fingerprint,
            "approval_ids": approval_ids,
            "environment": self._environment,
            "rollback_plan": rollback_plan,
            "created_at": isoformat(now),
        }
        return {
            "preparation": mirror,
            "approval_slots": slots,
            "created": True,
        }

    async def record_status(self, preparation_id: str, status: str) -> None:
        """Sync an approval-driven status change into the SQL row.

        This is a mirror sync, not a gate: demo preparations seeded only into
        the memory read model have no SQL row and are skipped, while real
        preparations are always present. The commit boundary independently
        fails closed when the row is missing.
        """
        session = self._session_factory()
        try:
            session.execute(
                update(Preparation)
                .where(Preparation.id == preparation_id)
                .values(status=status, updated_at=self._clock())
            )
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise HarnessError(
                503, "PREP-503", "preparation status sync failed"
            ) from exc
        finally:
            session.close()

    # -- helpers ----------------------------------------------------------------

    def _assign_slots(
        self, session: Any, project_id: str, applicant_id: str
    ) -> list[dict[str, str]]:
        """Pick one grantee per duty slot; fail closed when ineligible."""
        slots: list[dict[str, str]] = []
        for role_slot in REQUIRED_SLOTS:
            holders = (
                session.execute(
                    select(ProjectRoleGrant.user_id)
                    .where(
                        ProjectRoleGrant.project_id == project_id,
                        ProjectRoleGrant.role_slot == role_slot,
                    )
                    .order_by(ProjectRoleGrant.user_id)
                )
                .scalars()
                .all()
            )
            eligible = [user for user in holders if user != applicant_id]
            if not eligible:
                raise HarnessError(
                    409,
                    "PREP-409",
                    "no eligible approver for the duty slot",
                    {"reason": "NO_ELIGIBLE_APPROVER", "slot": role_slot},
                )
            slots.append({"role_slot": role_slot, "approver_id": eligible[0]})
        if slots[0]["approver_id"] == slots[1]["approver_id"]:
            raise HarnessError(
                409,
                "PREP-409",
                "duty slots must be held by two distinct approvers",
                {"reason": "NO_ELIGIBLE_APPROVER"},
            )
        return slots

    def _existing_result(self, session: Any, row: Preparation) -> dict[str, Any]:
        """Spec 4.2 idempotency: same facts return the same Preparation."""
        approval_ids = (
            session.execute(
                select(ApprovalRequest.id)
                .where(ApprovalRequest.preparation_id == row.id)
                .order_by(ApprovalRequest.created_at)
            )
            .scalars()
            .all()
        )
        slots = (
            session.execute(
                select(ApprovalRequest.required_role, ApprovalRequest.approver_id)
                .where(ApprovalRequest.preparation_id == row.id)
                .order_by(ApprovalRequest.required_role)
            )
            .all()
        )
        return {
            "preparation": {
                "preparation_id": row.id,
                "version_id": row.version_id,
                "project_id": row.project_id,
                "applicant_id": row.applicant_id,
                "status": row.status,
                "risk_level": row.risk_level,
                "fingerprint": row.fingerprint,
                "approval_ids": list(approval_ids),
                "environment": row.environment,
                "rollback_plan": row.rollback_plan or {},
                "created_at": isoformat(row.created_at),
            },
            "approval_slots": [
                {"role_slot": role, "approver_id": approver}
                for role, approver in slots
            ],
            "created": False,
        }

    @staticmethod
    def _derive_rollback_plan(version: dict[str, Any]) -> dict[str, Any]:
        """Control-plane rollback facts (Spec 4.2 冻结事实).

        Prepare has no external side effects: nothing is dispatched, no shadow
        table is materialised and production is untouched, so the derived plan
        is the deterministic discard procedure — no runtime data is invented.
        """
        return {
            "strategy": "shadow_discard",
            "steps": [
                "abort_pending_dispatch",
                "drop_shadow_resources",
                "release_preparation",
            ],
            "production_untouched": True,
            "artifact_digest": version.get("artifact_digest"),
        }


__all__ = ["PrepareOrchestrator", "REQUIRED_SLOTS"]
