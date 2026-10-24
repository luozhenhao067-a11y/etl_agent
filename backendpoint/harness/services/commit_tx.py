"""API-14 Commit orchestrator: one atomic PostgreSQL transaction (Spec 4.4).

Sequence (Spec 5.5 steps 1-3, user-approved 2026-10-24):

1. Server-side recheck: 2/2 approvals ``APPROVED`` with independent approvers
   (neither is the applicant), version still immutable, artifact digest still
   bound, preparation not committed yet.
2. The Capability issuer signs the single-use ``etl.execute`` token
   (``exp = iat + 300``); only ``jti`` and ``token_digest`` are retained —
   the plaintext token is never stored, logged or returned.
3. ONE PostgreSQL transaction inserts the ``execution_runs`` row (with the
   unique ``capability_token_digest``), enqueues the ``execution.command``
   Outbox event and appends the ``approval.validated`` / ``capability.issued``
   / ``run.committed`` / ``outbox.event.created`` audit events. Any failure
   rolls the whole transaction back — no execution is produced.

The response carries only ``execution_run_id`` / ``status`` / ``committed_at``
/ ``capability_digest``; the dispatch (Spec 5.5 step 4+) is out of scope here.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError

from app.core.harness.errors import HarnessError
from app.core.harness.kernel import HarnessKernel
from app.core.harness.models import is_digest, isoformat, utcnow
from app.core.utils import digest_of, new_id
from app.models.tables import ExecutionRun, Preparation
from harness.core.ledger_sql import SqlLedger
from harness.core.outbox_sql import SqlOutbox
from harness.services.gateway import SessionFactory

Clock = Callable[..., Any]

# Spec 4.7 names the state QUEUED; the wire format (contract example and the
# API terminal sets) is lowercase, so the stored value is lowercase too.
_RUN_STATUS_QUEUED = "queued"
_PREPARATION_COMMITTED = "COMMITTED"


class CommitOrchestrator:
    """Three-phase Commit boundary; injected as ``container.commit``."""

    def __init__(
        self,
        *,
        kernel: HarnessKernel,
        session_factory: SessionFactory,
        outbox: SqlOutbox,
        ledger: SqlLedger,
        data_environment: str,
        clock: Clock = utcnow,
        command_store: Any | None = None,
    ) -> None:
        self._kernel = kernel
        self._session_factory = session_factory
        self._outbox = outbox
        self._ledger = ledger
        self._data_environment = data_environment
        self._clock = clock
        # Optional token handoff for dispatch (Spec 5.5 step 4): when a
        # Worker/Dispatcher is wired, the plaintext token is placed in this
        # in-process store after the transaction commits — never persisted
        # (Spec 5.1). None keeps commit usable without a dispatch layer.
        self._command_store = command_store

    async def commit(
        self,
        *,
        preparation: dict[str, Any],
        version: dict[str, Any],
        approvals: list[dict[str, Any]],
        actor_id: str,
    ) -> dict[str, str]:
        """Recheck, issue the capability and commit the atomic transaction.

        Returns exactly the API-14 fields. Raises ``HarnessError`` with the
        CMT-*/CAP-*/OBX-*/EL-* codes; the endpoint maps it via
        ``harness_error_to_api``.
        """
        self._recheck(preparation, version, approvals)

        preparation_id = preparation["preparation_id"]
        execution_run_id = new_id("run")
        artifact_digest = version["artifact_digest"]
        command = {
            "tool": "etl.execute",
            "execution_run_id": execution_run_id,
            "version_id": preparation["version_id"],
            "preparation_id": preparation_id,
            "artifact_digest": artifact_digest,
            "environment": self._data_environment,
            "capability_token_digest": None,  # replaced after issuance
        }

        # Spec 5.5 step 2: sign the token before the transaction so the run
        # row can carry its digest; the signature itself is pure in-memory.
        spec = self._kernel.pdp.tool_spec("etl.execute")
        if spec is None:
            raise HarnessError(
                500, "CMT-500", "execution tool is not registered", {"tool": "etl.execute"}
            )
        issued = self._kernel.capability.issue(
            {
                "tool": "etl.execute",
                "sub": actor_id,
                "project_id": preparation["project_id"],
                "environment": self._data_environment,
                "resource_scope": {
                    "version_id": preparation["version_id"],
                    "preparation_id": preparation_id,
                    "pipeline_id": version.get("pipeline_id"),
                },
                "artifact_digest": artifact_digest,
                "preparation_id": preparation_id,
                "execution_run_id": execution_run_id,
            },
            approval_facts=[
                {
                    "decision": row.get("decision") or row.get("status"),
                    "approver_id": row.get("approver_id"),
                    "required_role": row.get("required_role"),
                }
                for row in approvals
            ],
            required_slots=spec.required_slots,
        )
        command["capability_token_digest"] = issued["token_digest"]
        command_digest = digest_of(command)

        now = self._clock()
        session = self._session_factory()
        try:
            session.add(
                ExecutionRun(
                    id=execution_run_id,
                    version_id=preparation["version_id"],
                    preparation_id=preparation_id,
                    capability_token_digest=issued["token_digest"],
                    status=_RUN_STATUS_QUEUED,
                    created_at=now,
                    updated_at=now,
                )
            )
            # Sync the durable Preparation row inside the same transaction.
            # A memory-only demo preparation has no row and must not commit —
            # fail closed instead of fabricating a run.
            preparation_update = session.execute(
                update(Preparation)
                .where(Preparation.id == preparation_id)
                .values(
                    status=_PREPARATION_COMMITTED,
                    commit_facts={
                        "execution_run_id": execution_run_id,
                        "capability_digest": issued["token_digest"],
                        "committed_at": isoformat(now),
                        "committed_by": actor_id,
                    },
                    updated_at=now,
                )
            )
            if preparation_update.rowcount != 1:
                raise HarnessError(
                    409,
                    "CMT-409",
                    "preparation is not persisted",
                    {"reason": "NOT_PERSISTED"},
                )
            # Spec 4.4: the Outbox event stores the command digest only — the
            # capability plaintext never reaches the database.
            outbox_record = await self._outbox.enqueue(
                session,
                {
                    "event_type": "execution.command",
                    "aggregate_id": execution_run_id,
                    "payload_digest": command_digest,
                    "idempotency_key": f"execution:{execution_run_id}",
                },
            )
            await self._ledger.append(
                session,
                {
                    "project_id": preparation["project_id"],
                    "actor_id": actor_id,
                    "event_type": "approval.validated",
                    "resource_type": "preparation",
                    "resource_id": preparation_id,
                    "payload_digest": digest_of(
                        {
                            "approved_count": len(approvals),
                            "approver_ids": sorted(
                                {row.get("approver_id") for row in approvals}
                            ),
                        }
                    ),
                },
            )
            await self._ledger.append(
                session,
                {
                    "project_id": preparation["project_id"],
                    "actor_id": actor_id,
                    "event_type": "capability.issued",
                    "resource_type": "capability",
                    "resource_id": issued["jti"],
                    "payload_digest": digest_of(
                        {
                            "preparation_id": preparation_id,
                            "execution_run_id": execution_run_id,
                            "tool": "etl.execute",
                        }
                    ),
                },
            )
            await self._ledger.append(
                session,
                {
                    "project_id": preparation["project_id"],
                    "actor_id": actor_id,
                    "event_type": "run.committed",
                    "resource_type": "execution_run",
                    "resource_id": execution_run_id,
                    "payload_digest": digest_of(
                        {
                            "execution_run_id": execution_run_id,
                            "preparation_id": preparation_id,
                            "capability_token_digest": issued["token_digest"],
                        }
                    ),
                },
            )
            await self._ledger.append(
                session,
                {
                    "project_id": preparation["project_id"],
                    "actor_id": actor_id,
                    "event_type": "outbox.event.created",
                    "resource_type": "outbox_event",
                    "resource_id": outbox_record["event_id"],
                    "payload_digest": command_digest,
                },
            )
            session.commit()
        except HarnessError:
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            # Spec 4.4 failure policy: Outbox or audit failure rolls back the
            # run row too — no execution, no half state.
            session.rollback()
            raise HarnessError(503, "CMT-503", "commit transaction failed") from exc
        finally:
            session.close()

        # Spec 5.5 step 4 handoff: right after the transaction commits, the
        # plaintext token is placed in the in-process dispatcher store. It is
        # never persisted, logged or returned (Spec 5.1); a restart loses it
        # and the Worker then fails the run closed (CAP-403 → dead-letter).
        if self._command_store is not None:
            self._command_store.put(execution_run_id, issued["token"])

        result = {
            "execution_run_id": execution_run_id,
            "status": _RUN_STATUS_QUEUED,
            "committed_at": isoformat(now),
            "capability_digest": issued["token_digest"],
        }
        # Memory-side commit record: duplicate commits and replays read this
        # (Spec 4.4 idempotency — same preparation never commits twice).
        preparation["commit"] = {
            "execution_run_id": execution_run_id,
            "capability_digest": issued["token_digest"],
            "committed_at": result["committed_at"],
            "committed_by": actor_id,
        }
        return result

    def _recheck(
        self,
        preparation: dict[str, Any],
        version: dict[str, Any],
        approvals: list[dict[str, Any]],
    ) -> None:
        """Server-side recheck (Spec 4.4); independent of the route checks."""
        if preparation.get("commit") is not None:
            raise HarnessError(
                409,
                "CMT-409",
                "preparation is already committed",
                {"reason": "ALREADY_COMMITTED"},
            )
        if preparation.get("status") != "APPROVED":
            raise HarnessError(
                409,
                "CMT-409",
                "approval incomplete",
                {"reason": "APPROVAL_INCOMPLETE"},
            )
        # The frozen Preparation fingerprint binds the artifact digest; the
        # frozen payload itself is not persisted yet (P-04), so the recheck
        # verifies every artifact fact available server-side.
        artifact_digest = version.get("artifact_digest")
        if not version.get("is_immutable") or not is_digest(artifact_digest):
            raise HarnessError(
                409,
                "CMT-409",
                "version facts no longer match the preparation",
                {"reason": "FINGERPRINT_MISMATCH"},
            )
        approved = [
            row for row in approvals if str(row.get("status", "")).upper() == "APPROVED"
        ]
        approver_ids = {row.get("approver_id") for row in approved}
        if (
            len(approved) < 2
            or len(approver_ids) < 2
            or None in approver_ids
            or preparation.get("applicant_id") in approver_ids
        ):
            raise HarnessError(
                409,
                "CMT-409",
                "approval facts violate duty separation",
                {
                    "reason": "APPROVAL_INCOMPLETE",
                    "approved_count": len(approved),
                    "distinct_approvers": len(approver_ids),
                },
            )


__all__ = ["CommitOrchestrator"]
