"""Prepare orchestrator tests (Spec 4.2; P-04 confirmed 2026-10-24).

Covers the P-04 gap: duty-slot assignment from project_role_grants, PENDING
approval_requests creation, frozen-fact persistence, content-level
idempotency (same fingerprint → same preparation, different → PREP-409),
and the commit boundary requiring a persisted preparation.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.core.harness.errors import HarnessError
from app.models.tables import ApprovalRequest, AuditEvent, Preparation
from harness.tests.conftest import make_approvals, make_version


def make_decision(kernel) -> dict:
    """A real PDP decision for the etl.execute intent prepare would freeze."""
    return kernel.pdp.decide(
        {
            "tool": "etl.execute",
            "actor_id": "u1",
            "project_id": "p1",
            "environment": "test",
            "resource_scope": {"version_id": "v1", "pipeline_id": "pl1"},
            "artifact_digest": "a" * 64,
        }
    )


def make_request_facts() -> dict:
    return {
        "schedule": {"cron": "0 2 * * *"},
        "budget": {"max_rows": 1000},
        "quality_contract_ref": "qc_demo_001",
    }


async def _create(prepare_orchestrator, kernel, **overrides):
    params = {
        "version": make_version(),
        "project_id": "p1",
        "applicant_id": "u1",
        "fingerprint": "sha256:" + "b" * 64,
        "request_facts": make_request_facts(),
        "decision": make_decision(kernel),
    }
    params.update(overrides)
    return await prepare_orchestrator.create(**params)


async def test_prepare_creates_slots_approvals_and_ledger_events(
    prepare_orchestrator, kernel, seeded_engine, session_factory
):
    result = await _create(prepare_orchestrator, kernel)

    assert result["created"] is True
    mirror = result["preparation"]
    assert mirror["status"] == "PREPARED"
    assert mirror["risk_level"] == "P1"  # etl.execute per the tool registry
    assert mirror["environment"] == "test"
    assert mirror["rollback_plan"]["production_untouched"] is True
    assert [slot["approver_id"] for slot in result["approval_slots"]] == ["u2", "u3"]
    assert [slot["role_slot"] for slot in result["approval_slots"]] == [
        "data_checker",
        "security_checker",
    ]

    with session_factory() as session:
        row = session.execute(
            select(Preparation).where(Preparation.id == mirror["preparation_id"])
        ).scalar_one()
        assert row.status == "PREPARED"
        assert row.artifact_digest == "a" * 64
        assert row.quality_contract_ref == "qc_demo_001"
        decision_digest = row.decision_digest
        assert decision_digest is not None

        approvals = session.execute(
            select(ApprovalRequest)
            .where(ApprovalRequest.preparation_id == mirror["preparation_id"])
            .order_by(ApprovalRequest.required_role)
        ).scalars().all()
        assert [(a.required_role, a.status, a.approver_id) for a in approvals] == [
            ("data_checker", "PENDING", "u2"),
            ("security_checker", "PENDING", "u3"),
        ]

        events = session.execute(
            select(AuditEvent.event_type).order_by(AuditEvent.chain_seq)
        ).scalars().all()
    assert events == ["preparation.created", "approval.slot.assigned", "approval.slot.assigned"]

    # Spec 3.4: the decision is bound to the preparation.
    bound = kernel.pdp.get_decision(decision_digest)
    assert bound["state"] == "BOUND_TO_PREPARATION"
    assert bound["preparation_id"] == mirror["preparation_id"]


async def test_same_fingerprint_returns_same_preparation(
    prepare_orchestrator, kernel, seeded_engine, session_factory
):
    first = await _create(prepare_orchestrator, kernel)
    second = await _create(prepare_orchestrator, kernel)

    assert second["created"] is False
    assert (
        second["preparation"]["preparation_id"]
        == first["preparation"]["preparation_id"]
    )
    assert second["approval_slots"] == first["approval_slots"]

    with session_factory() as session:
        assert len(session.execute(select(Preparation)).all()) == 1
        assert len(session.execute(select(ApprovalRequest)).all()) == 2


async def test_different_fingerprint_conflicts(
    prepare_orchestrator, kernel, seeded_engine, session_factory
):
    await _create(prepare_orchestrator, kernel, fingerprint="sha256:" + "b" * 64)
    with pytest.raises(HarnessError) as conflict:
        await _create(prepare_orchestrator, kernel, fingerprint="sha256:" + "c" * 64)
    assert conflict.value.error_code == "PREP-409"
    assert conflict.value.details["reason"] == "FINGERPRINT_CONFLICT"

    with session_factory() as session:
        assert len(session.execute(select(Preparation)).all()) == 1


async def test_missing_grants_fail_closed_without_writes(
    prepare_orchestrator, kernel, seeded_engine, session_factory
):
    with session_factory() as session:
        session.execute(text("DELETE FROM project_role_grants"))
        session.commit()

    with pytest.raises(HarnessError) as denied:
        await _create(prepare_orchestrator, kernel)
    assert denied.value.error_code == "PREP-409"
    assert denied.value.details["reason"] == "NO_ELIGIBLE_APPROVER"

    with session_factory() as session:
        assert session.execute(select(Preparation)).first() is None
        assert session.execute(select(ApprovalRequest)).first() is None
        assert session.execute(select(AuditEvent)).first() is None


async def test_applicant_holder_slot_has_no_eligible_approver(
    prepare_orchestrator, kernel, seeded_engine, session_factory
):
    with session_factory() as session:
        session.execute(text("DELETE FROM project_role_grants WHERE id='g1'"))
        session.execute(
            text(
                "INSERT INTO project_role_grants (id, project_id, user_id, "
                "role_slot, created_at, updated_at) VALUES "
                "('g3','p1','u1','data_checker',:now,:now)"
            ),
            {"now": "2026-10-24T00:00:00+00:00"},
        )
        session.commit()

    with pytest.raises(HarnessError) as denied:
        await _create(prepare_orchestrator, kernel)
    assert denied.value.details == {
        "reason": "NO_ELIGIBLE_APPROVER",
        "slot": "data_checker",
    }


async def test_record_status_syncs_sql_row_and_skips_demo_rows(
    prepare_orchestrator, kernel, seeded_engine, session_factory
):
    result = await _create(prepare_orchestrator, kernel)
    preparation_id = result["preparation"]["preparation_id"]

    await prepare_orchestrator.record_status(preparation_id, "APPROVED")
    with session_factory() as session:
        row = session.execute(
            select(Preparation).where(Preparation.id == preparation_id)
        ).scalar_one()
    assert row.status == "APPROVED"

    # Memory-only demo preparations have no SQL row; the sync is a mirror,
    # not a gate — it must not raise.
    await prepare_orchestrator.record_status("prep_demo_001", "APPROVED")


async def test_commit_requires_persisted_preparation(commit_orchestrator, seeded_engine):
    from harness.tests.conftest import make_preparation

    with pytest.raises(HarnessError) as not_persisted:
        await commit_orchestrator.commit(
            preparation=make_preparation(),
            version=make_version(),
            approvals=make_approvals(),
            actor_id="ops1",
        )
    assert not_persisted.value.error_code == "CMT-409"
    assert not_persisted.value.details["reason"] == "NOT_PERSISTED"


async def test_commit_marks_preparation_committed_in_sql(
    prepare_orchestrator, commit_orchestrator, kernel, seeded_engine, session_factory
):
    result = await _create(prepare_orchestrator, kernel)
    preparation = result["preparation"]
    preparation["status"] = "APPROVED"  # as decide_approval leaves it

    commit_result = await commit_orchestrator.commit(
        preparation=preparation,
        version=make_version(),
        approvals=make_approvals(),
        actor_id="ops1",
    )

    with session_factory() as session:
        row = session.execute(
            select(Preparation).where(Preparation.id == preparation["preparation_id"])
        ).scalar_one()
    assert row.status == "COMMITTED"
    assert row.commit_facts["execution_run_id"] == commit_result["execution_run_id"]
    assert row.commit_facts["capability_digest"] == commit_result["capability_digest"]
