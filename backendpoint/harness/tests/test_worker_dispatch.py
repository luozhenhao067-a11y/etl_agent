"""Outbox dispatch + managed execution Worker tests (Spec 5.5 steps 4-10).

Covers the token handoff (in-process only — Spec 5.1), the Worker's binding
and fail-closed rejection paths, the dispatcher's ack / retry / dead-letter
semantics, and the supervision refresh. The engine is a deterministic fake;
the stub-engine path is asserted separately (honest TB-503, no fabricated
job IDs).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.adapters.stub.exec import StubExecAdapter
from app.core.harness.errors import HarnessError
from app.models.tables import AuditEvent, ExecutionRun
from harness.models.outbox import OutboxEvent
from harness.tests.conftest import (
    make_approvals,
    make_preparation,
    make_version,
    persist_preparation,
)
from harness.worker import ExecutionWorker, OutboxDispatcher, PendingCommandStore


async def _commit_run(commit_orchestrator, session_factory):
    """persist the preparation row, run commit; returns the run id."""
    await persist_preparation(session_factory, make_preparation())
    result = await commit_orchestrator.commit(
        preparation=make_preparation(),
        version=make_version(),
        approvals=make_approvals(),
        actor_id="ops1",
    )
    return result["execution_run_id"]


def _run_row(session_factory, run_id):
    with session_factory() as session:
        return session.get(ExecutionRun, run_id)


def _event_row(session_factory, run_id):
    with session_factory() as session:
        return session.execute(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == run_id)
        ).scalar_one()


def _ledger_types(session_factory):
    with session_factory() as session:
        return (
            session.execute(
                select(AuditEvent.event_type).order_by(AuditEvent.chain_seq)
            )
            .scalars()
            .all()
        )


# -- happy path ----------------------------------------------------------------


async def test_dispatch_delivers_queued_run_to_engine(
    seeded_engine,
    commit_orchestrator, dispatcher, command_store, execution_worker, fake_exec, session_factory
):
    run_id = await _commit_run(commit_orchestrator, session_factory)
    assert command_store.pending_count() == 1  # token handed off in-process

    summary = await dispatcher.dispatch_pending()

    assert summary == {
        "delivered": 1,
        "rejected": 0,
        "duplicate": 0,
        "failed": 0,
        "skipped": 0,
    }
    assert command_store.pending_count() == 0  # consumed on delivery

    run = _run_row(session_factory, run_id)
    assert run.status == "running"
    assert run.engine_job_id == "job_1"
    assert run.started_at is not None

    # The engine received the managed command from the immutable artifact.
    assert len(fake_exec.submitted) == 1
    command = fake_exec.submitted[0]
    assert command["execution_run_id"] == run_id
    assert command["preparation_id"] == "prep_t001"
    assert command["artifact_digest"] == "a" * 64
    assert command["hocon"] == "conf"  # seeded_engine's immutable v1

    assert _event_row(session_factory, run_id).status == "CONSUMED"
    types = _ledger_types(session_factory)
    assert "run.started" in types
    assert "outbox.event.published" in types
    assert "outbox.event.consumed" in types


# -- fail-closed rejections ------------------------------------------------------


async def test_lost_token_fails_run_closed(
    seeded_engine,
    commit_orchestrator, dispatcher, command_store, session_factory
):
    run_id = await _commit_run(commit_orchestrator, session_factory)
    command_store.pop(run_id)  # simulate a restart that emptied the store

    summary = await dispatcher.dispatch_pending()

    assert summary["rejected"] == 1
    run = _run_row(session_factory, run_id)
    assert run.status == "failed"
    assert run.engine_job_id is None
    assert run.finished_at is not None
    # Delivered and acked: the rejection is a business outcome, not transport.
    assert _event_row(session_factory, run_id).status == "CONSUMED"
    assert "run.failed" in _ledger_types(session_factory)


async def test_foreign_token_is_rejected_by_digest_binding(
    seeded_engine,
    commit_orchestrator, command_store, execution_worker, session_factory
):
    run_id = await _commit_run(commit_orchestrator, session_factory)
    token = command_store.pop(run_id)
    assert token

    # Tamper with the unique digest recorded at Commit: the token no longer
    # belongs to this run and must be refused before any execution.
    with session_factory() as session:
        run = session.get(ExecutionRun, run_id)
        run.capability_token_digest = "c" * 64
        session.commit()

    outcome = await execution_worker.handle_command(
        {"aggregate_id": run_id, "event_type": "execution.command"},
        capability_token=token,
    )
    assert outcome["result"] == "rejected"
    assert outcome["failure_code"] == "CAP-403"
    assert _run_row(session_factory, run_id).status == "failed"


async def test_stub_engine_fails_run_honestly_without_job_id(
    seeded_engine,
    commit_orchestrator, command_store, kernel, session_factory, outbox, ledger
):
    stub_worker = ExecutionWorker(
        kernel=kernel,
        session_factory=session_factory,
        ledger=ledger,
        exec_port=StubExecAdapter(),
    )
    stub_dispatcher = OutboxDispatcher(
        session_factory=session_factory,
        outbox=outbox,
        ledger=ledger,
        worker=stub_worker,
        commands=command_store,
    )
    run_id = await _commit_run(commit_orchestrator, session_factory)

    summary = await stub_dispatcher.dispatch_pending()

    assert summary["rejected"] == 1
    run = _run_row(session_factory, run_id)
    assert run.status == "failed"
    assert run.engine_job_id is None  # never a fabricated job ID
    assert _event_row(session_factory, run_id).status == "CONSUMED"
    assert "run.failed" in _ledger_types(session_factory)


# -- idempotent redelivery -------------------------------------------------------


async def test_redelivered_command_is_duplicate_without_mutation(
    seeded_engine,
    commit_orchestrator, dispatcher, execution_worker, session_factory
):
    run_id = await _commit_run(commit_orchestrator, session_factory)
    await dispatcher.dispatch_pending()
    before = _run_row(session_factory, run_id)

    outcome = await execution_worker.handle_command(
        {"aggregate_id": run_id, "event_type": "execution.command"},
        capability_token=None,  # not even needed: the status gate short-circuits
    )

    assert outcome["result"] == "duplicate"
    after = _run_row(session_factory, run_id)
    assert after.status == before.status == "running"
    assert after.engine_job_id == before.engine_job_id


async def test_outbox_refuses_events_other_than_execution_commands(
    seeded_engine, outbox, session_factory
):
    # Spec 3.8: the Outbox carries execution.command events only — the guard
    # sits at enqueue, so a foreign event can never enter the dispatch flow.
    with pytest.raises(HarnessError) as refused:
        with session_factory() as session:
            await outbox.enqueue(
                session,
                {
                    "event_type": "not.a.command",
                    "aggregate_id": "agg_1",
                    "payload_digest": "a" * 64,
                    "idempotency_key": "foreign:1",
                },
            )
    assert refused.value.error_code == "OBX-422"


# -- retry / dead-letter ---------------------------------------------------------


async def test_transport_failure_moves_event_to_retrying(
    seeded_engine,
    commit_orchestrator, dispatcher, session_factory, monkeypatch
):
    run_id = await _commit_run(commit_orchestrator, session_factory)

    async def boom(self, event, *, capability_token=None):
        raise HarnessError(503, "TB-503", "broker unavailable")

    monkeypatch.setattr(ExecutionWorker, "handle_command", boom)
    summary = await dispatcher.dispatch_pending()

    assert summary["failed"] == 1
    row = _event_row(session_factory, run_id)
    assert row.status == "RETRYING"
    assert row.attempts == 1
    assert "outbox.event.failed" in _ledger_types(session_factory)


async def test_transport_failure_then_successful_redelivery(
    seeded_engine,
    commit_orchestrator, dispatcher, execution_worker, session_factory, monkeypatch
):
    run_id = await _commit_run(commit_orchestrator, session_factory)
    original = execution_worker.handle_command

    async def flaky(event, *, capability_token=None):
        if len(flaky.calls) == 0:
            flaky.calls.append(event)
            raise HarnessError(503, "TB-503", "broker unavailable")
        return await original(event, capability_token=capability_token)

    flaky.calls = []
    monkeypatch.setattr(execution_worker, "handle_command", flaky)

    first = await dispatcher.dispatch_pending()
    assert first["failed"] == 1
    assert _event_row(session_factory, run_id).status == "RETRYING"

    monkeypatch.setattr(execution_worker, "handle_command", original)
    second = await dispatcher.dispatch_pending()

    assert second["delivered"] == 1
    assert _run_row(session_factory, run_id).status == "running"
    assert _event_row(session_factory, run_id).status == "CONSUMED"


# -- token handoff store ---------------------------------------------------------


def test_pending_command_store_expires_with_token_ttl():
    moment = {"now": datetime(2026, 10, 24, tzinfo=timezone.utc)}
    store = PendingCommandStore(clock=lambda: moment["now"])

    store.put("run_1", "token-plaintext")
    assert store.pop("run_1") == "token-plaintext"  # delivered once

    store.put("run_2", "token-plaintext")
    moment["now"] = moment["now"] + timedelta(seconds=301)
    assert store.pop("run_2") is None  # expired with the token (exp = iat+300)
    assert store.pending_count() == 0


def test_pending_command_store_rejects_empty_entries():
    store = PendingCommandStore()
    try:
        store.put("", "token")
    except ValueError:
        pass
    else:
        raise AssertionError("empty run id must be refused")


# -- supervision refresh ----------------------------------------------------------


async def test_poll_run_completes_succeeded_run(
    seeded_engine,
    commit_orchestrator, dispatcher, execution_worker, fake_exec, session_factory
):
    run_id = await _commit_run(commit_orchestrator, session_factory)
    await dispatcher.dispatch_pending()

    fake_exec.reports["job_1"] = {
        "status": "SUCCEEDED",
        "input_records": 1000,
        "output_records": 980,
        "error_records": 20,
        "bytes_processed": 1048576,
    }
    outcome = await execution_worker.poll_run(run_id)

    assert outcome == {"result": "completed", "status": "succeeded"}
    run = _run_row(session_factory, run_id)
    assert run.status == "succeeded"
    assert run.input_records == 1000
    assert run.output_records == 980
    assert run.bytes_processed == 1048576
    assert run.finished_at is not None
    assert "run.succeeded" in _ledger_types(session_factory)


async def test_poll_run_records_engine_failure(
    seeded_engine,
    commit_orchestrator, dispatcher, execution_worker, fake_exec, session_factory
):
    run_id = await _commit_run(commit_orchestrator, session_factory)
    await dispatcher.dispatch_pending()

    fake_exec.reports["job_1"] = {"status": "FAILED", "error_code": "EXEC-502"}
    outcome = await execution_worker.poll_run(run_id)

    assert outcome == {"result": "completed", "status": "failed"}
    assert _run_row(session_factory, run_id).status == "failed"
    assert "run.failed" in _ledger_types(session_factory)


async def test_poll_run_skips_non_running_runs(
    seeded_engine,
    commit_orchestrator, dispatcher, execution_worker, session_factory
):
    run_id = await _commit_run(commit_orchestrator, session_factory)
    outcome = await execution_worker.poll_run(run_id)
    assert outcome["result"] == "skipped"
    assert outcome["status"] == "queued"


async def test_poll_run_is_honest_without_engine(
    seeded_engine,
    commit_orchestrator, kernel, session_factory, ledger
):
    class _DeadExec:
        async def submit_job(self, command):
            raise NotImplementedError("EXEC_ENGINE_NOT_READY")

        async def cancel_job(self, engine_job_id, reason):
            raise NotImplementedError("EXEC_ENGINE_NOT_READY")

        async def query_status(self, engine_job_id):
            raise NotImplementedError("EXEC_ENGINE_NOT_READY")

    worker = ExecutionWorker(
        kernel=kernel, session_factory=session_factory, ledger=ledger, exec_port=_DeadExec()
    )
    run_id = await _commit_run(commit_orchestrator, session_factory)
    with session_factory() as session:
        run = session.get(ExecutionRun, run_id)
        run.status = "running"  # as if an engine had accepted it earlier
        run.engine_job_id = "job_gone"
        session.commit()

    outcome = await worker.poll_run(run_id)

    assert outcome == {"result": "unavailable"}
    run = _run_row(session_factory, run_id)
    assert run.status == "running"  # untouched — never a fabricated state

