"""Commit transaction tests: execution_runs + Outbox + audit in ONE transaction.

Covers Spec 4.4 / 5.5 steps 1-3 and the user-approved requirement: the Outbox
event and the business fact share one PostgreSQL transaction; any failure
rolls the whole thing back — no execution is produced. The run row carries
only the capability digest; the token plaintext is never persisted.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.harness.errors import HarnessError
from app.models.tables import AuditEvent, ExecutionRun
from harness.models.outbox import OutboxEvent
from harness.services.commit_tx import CommitOrchestrator
from harness.tests.conftest import (
    make_approvals,
    make_preparation,
    make_version,
    persist_preparation,
)


class _ExplodingOutbox:
    """Simulates an Outbox write failure (Spec 4.4 failure policy)."""

    async def enqueue(self, session, event):
        raise HarnessError(503, "OBX-503", "outbox unavailable")


class _ExplodingLedger:
    """Simulates a database-level audit failure."""

    async def append(self, session, event):
        raise IntegrityError("INSERT INTO audit_events", {}, Exception("disk boom"))


async def test_commit_writes_run_outbox_and_audit_atomically(
    commit_orchestrator, seeded_engine, session_factory
):
    # Commit's NOT_PERSISTED guard requires the durable Preparation row
    # (created by the prepare orchestrator in the API flow).
    await persist_preparation(session_factory, make_preparation())
    result = await commit_orchestrator.commit(
        preparation=make_preparation(),
        version=make_version(),
        approvals=make_approvals(),
        actor_id="ops1",
    )

    # Response carries exactly the API-14 fields; no token plaintext.
    assert set(result) == {
        "execution_run_id",
        "status",
        "committed_at",
        "capability_digest",
    }
    assert result["status"] == "queued"
    assert len(result["capability_digest"]) == 64

    with session_factory() as session:
        run = session.execute(
            select(ExecutionRun).where(ExecutionRun.id == result["execution_run_id"])
        ).scalar_one()
        assert run.status == "queued"
        assert run.capability_token_digest == result["capability_digest"]

        event = session.execute(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == run.id)
        ).scalar_one()
        assert event.event_type == "execution.command"
        assert event.status == "PENDING"
        assert event.idempotency_key == f"execution:{run.id}"
        # The command digest is stored, never the command payload or token.
        assert len(event.payload_digest) == 64

        events = session.execute(
            select(AuditEvent.event_type)
            .where(AuditEvent.project_id == "p1")
            .order_by(AuditEvent.chain_seq)
        ).scalars().all()
        assert events == [
            "approval.validated",
            "capability.issued",
            "run.committed",
            "outbox.event.created",
        ]


async def test_outbox_failure_rolls_back_run_and_audit(
    kernel, seeded_engine, session_factory, ledger
):
    orchestrator = CommitOrchestrator(
        kernel=kernel,
        session_factory=session_factory,
        outbox=_ExplodingOutbox(),
        ledger=ledger,
        data_environment="test",
    )
    await persist_preparation(session_factory, make_preparation())
    with pytest.raises(HarnessError) as failed:
        await orchestrator.commit(
            preparation=make_preparation(),
            version=make_version(),
            approvals=make_approvals(),
            actor_id="ops1",
        )
    assert failed.value.error_code == "OBX-503"

    with session_factory() as session:
        assert session.execute(select(ExecutionRun)).first() is None
        assert session.execute(select(OutboxEvent)).first() is None
        assert session.execute(select(AuditEvent)).first() is None


async def test_audit_failure_rolls_back_run_and_outbox(
    kernel, seeded_engine, session_factory, outbox
):
    orchestrator = CommitOrchestrator(
        kernel=kernel,
        session_factory=session_factory,
        outbox=outbox,
        ledger=_ExplodingLedger(),
        data_environment="test",
    )
    await persist_preparation(session_factory, make_preparation())
    with pytest.raises(HarnessError) as failed:
        await orchestrator.commit(
            preparation=make_preparation(),
            version=make_version(),
            approvals=make_approvals(),
            actor_id="ops1",
        )
    assert failed.value.error_code == "CMT-503"

    with session_factory() as session:
        assert session.execute(select(ExecutionRun)).first() is None
        assert session.execute(select(OutboxEvent)).first() is None
        assert session.execute(select(AuditEvent)).first() is None


async def test_duplicate_commit_is_rejected(commit_orchestrator, seeded_engine, session_factory):
    preparation = make_preparation()
    await persist_preparation(session_factory, preparation)
    await commit_orchestrator.commit(
        preparation=preparation,
        version=make_version(),
        approvals=make_approvals(),
        actor_id="ops1",
    )

    # The orchestrator marks the memory-side commit record; a second commit
    # attempt fails closed with CMT-409 (Spec 4.4 idempotency).
    assert preparation["commit"]["execution_run_id"].startswith("run_")
    with pytest.raises(HarnessError) as duplicate:
        await commit_orchestrator.commit(
            preparation=preparation,
            version=make_version(),
            approvals=make_approvals(),
            actor_id="ops1",
        )
    assert duplicate.value.error_code == "CMT-409"
    assert duplicate.value.details["reason"] == "ALREADY_COMMITTED"


async def test_duty_separation_violation_is_rejected(commit_orchestrator, seeded_engine):
    same_approver = make_approvals(approver_id="u2")
    with pytest.raises(HarnessError) as denied:
        await commit_orchestrator.commit(
            preparation=make_preparation(),
            version=make_version(),
            approvals=same_approver,
            actor_id="ops1",
        )
    assert denied.value.error_code == "CMT-409"
    assert denied.value.details["reason"] == "APPROVAL_INCOMPLETE"


async def test_version_drift_is_rejected(commit_orchestrator, seeded_engine):
    with pytest.raises(HarnessError) as drifted:
        await commit_orchestrator.commit(
            preparation=make_preparation(),
            version=make_version(is_immutable=False),
            approvals=make_approvals(),
            actor_id="ops1",
        )
    assert drifted.value.error_code == "CMT-409"
    assert drifted.value.details["reason"] == "FINGERPRINT_MISMATCH"

    with pytest.raises(HarnessError) as digest_missing:
        await commit_orchestrator.commit(
            preparation=make_preparation(),
            version=make_version(artifact_digest=None),
            approvals=make_approvals(),
            actor_id="ops1",
        )
    assert digest_missing.value.error_code == "CMT-409"
