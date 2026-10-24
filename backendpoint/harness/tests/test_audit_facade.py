"""Container.record_audit facade tests (staging audit → Evidence Ledger).

Kernel mode routes the Spec 12.2 staging-path events through the gateway's
SQL hash chain, so chain verification reports ``external_entries == 0``;
stub/memory mode keeps the staging AuditService rows the API contract tests
assert on.
"""

from __future__ import annotations

from app.adapters.memory.repository import InMemoryRepository
from app.adapters.memory.state import MemoryState
from app.adapters.stub.exec import StubExecAdapter
from app.adapters.stub.secret import StubSecretAdapter
from app.config import Settings
from app.container import Container
from app.core.audit import AuditService
from app.core.idempotency import InMemoryIdempotencyStore
from harness.services.gateway import KernelHarnessAdapter


def _container(**overrides) -> Container:
    fields = dict(
        settings=Settings.from_env(),
        repository=InMemoryRepository(),
        state=MemoryState(),
        harness=StubExecAdapter(),  # replaced below when needed
        secret=StubSecretAdapter(),
        exec=StubExecAdapter(),
        idempotency=InMemoryIdempotencyStore(),
        audit=AuditService(InMemoryRepository()),
    )
    fields.update(overrides)
    return Container(**fields)


async def test_record_audit_writes_the_evidence_ledger_chain_in_kernel_mode(
    kernel, session_factory, replay_guard, outbox, ledger
):
    harness = KernelHarnessAdapter(
        kernel=kernel,
        session_factory=session_factory,
        replay=replay_guard,
        outbox=outbox,
        ledger=ledger,
    )
    # Any non-None commit marks kernel mode for the facade.
    container = _container(harness=harness, session_factory=session_factory, commit=object())

    await container.record_audit(
        project_id="p1",
        actor_id="u1",
        event_type="pipeline.created",
        resource_type="pipeline",
        resource_id="pl1",
        payload={"pipeline_id": "pl1", "project_id": "p1", "code": "demo"},
    )
    await container.record_audit(
        project_id="p1",
        actor_id="u1",
        event_type="approval.decision.recorded",
        resource_type="approval_request",
        resource_id="apr1",
        payload={"approval_id": "apr1", "decision": "approved", "approver_id": "u2"},
    )

    with session_factory() as session:
        report = ledger.verify(session, "p1")
    assert report["status"] == "VERIFIED"
    assert report["entries"] == 2
    assert report["external_entries"] == 0


async def test_record_audit_keeps_staging_rows_in_stub_mode():
    repository = InMemoryRepository()
    container = _container(commit=None, audit=AuditService(repository))

    await container.record_audit(
        project_id="p1",
        actor_id="u1",
        event_type="pipeline.created",
        resource_type="pipeline",
        resource_id="pl1",
        payload={"pipeline_id": "pl1"},
    )

    events = repository.list_audit_events("p1")
    assert [event["event_type"] for event in events] == ["pipeline.created"]
