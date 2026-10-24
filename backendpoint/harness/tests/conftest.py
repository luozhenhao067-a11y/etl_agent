"""Fixtures for the Harness delivery tests (Spec 3-5).

SQLite in memory stands in for PostgreSQL (same ORM models, same session
pattern); fakeredis stands in for Redis. The signing keys are fixed test
seeds — production loads them from the environment via harness.core.keys,
which is covered by the container wiring, not here.
"""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fakeredis import FakeAsyncRedis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import harness.models  # noqa: F401  (registers outbox_events/ledger_checkpoints)
from app.core.harness.capability import CapabilityService
from app.core.harness.kernel import HarnessKernel
from app.models.tables import Base
from harness.core.ledger_sql import SqlLedger
from harness.core.outbox_sql import SqlOutbox
from harness.core.replay_redis import RedisReplayGuard
from harness.services.commit_tx import CommitOrchestrator
from harness.services.gateway import KernelHarnessAdapter
from harness.services.prepare_tx import PrepareOrchestrator
from harness.worker import ExecutionWorker, OutboxDispatcher, PendingCommandStore

# Fixed 32-byte Ed25519 test seed (user-approved 2026-10-24: 测试用固定测试钥).
TEST_SEED = bytes(range(32))

NOW = "2026-10-24T00:00:00+00:00"


def fixed_private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(TEST_SEED)


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def kernel():
    return HarnessKernel(capability=CapabilityService(private_key_bytes=TEST_SEED))


@pytest.fixture
def replay_guard():
    return RedisReplayGuard(FakeAsyncRedis())


@pytest.fixture
def outbox():
    return SqlOutbox()


@pytest.fixture
def ledger():
    return SqlLedger(private_key=fixed_private_key())


@pytest.fixture
def adapter(kernel, session_factory, replay_guard, outbox, ledger):
    return KernelHarnessAdapter(
        kernel=kernel,
        session_factory=session_factory,
        replay=replay_guard,
        outbox=outbox,
        ledger=ledger,
    )


@pytest.fixture
def command_store():
    return PendingCommandStore()


class _FakeExecAdapter:
    """Deterministic engine double: records submissions, canned reports."""

    def __init__(self):
        self.submitted = []
        self.reports: dict[str, dict] = {}

    async def submit_job(self, command):
        self.submitted.append(command)
        job_id = f"job_{len(self.submitted)}"
        self.reports[job_id] = {"status": "SUCCEEDED"}
        return {"engine_job_id": job_id, "status": "SUBMITTED"}

    async def cancel_job(self, engine_job_id: str, reason: str):
        return {"status": "CANCELLED"}

    async def query_status(self, engine_job_id: str):
        return dict(self.reports.get(engine_job_id, {"status": "RUNNING"}))


@pytest.fixture
def fake_exec():
    return _FakeExecAdapter()


@pytest.fixture
def execution_worker(kernel, session_factory, ledger, fake_exec):
    return ExecutionWorker(
        kernel=kernel,
        session_factory=session_factory,
        ledger=ledger,
        exec_port=fake_exec,
    )


@pytest.fixture
def dispatcher(session_factory, outbox, ledger, execution_worker, command_store):
    return OutboxDispatcher(
        session_factory=session_factory,
        outbox=outbox,
        ledger=ledger,
        worker=execution_worker,
        commands=command_store,
    )


@pytest.fixture
def commit_orchestrator(kernel, session_factory, outbox, ledger, command_store):
    return CommitOrchestrator(
        kernel=kernel,
        session_factory=session_factory,
        outbox=outbox,
        ledger=ledger,
        data_environment="test",
        command_store=command_store,
    )


@pytest.fixture
def prepare_orchestrator(kernel, session_factory, ledger):
    return PrepareOrchestrator(
        kernel=kernel,
        session_factory=session_factory,
        ledger=ledger,
        environment="test",
    )


@pytest.fixture
def seeded_engine(engine):
    """Core rows so foreign keys hold on PostgreSQL too."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, display_name, email, status, "
                "created_at, updated_at) VALUES "
                "('u1','u1','Applicant','u1@example.com','active',:now,:now)"
            ),
            {"now": NOW},
        )
        for user_id, display in (("u2", "Checker1"), ("u3", "Checker2"), ("ops1", "Operator")):
            connection.execute(
                text(
                    "INSERT INTO users (id, username, display_name, email, "
                    "status, created_at, updated_at) VALUES "
                    "(:id, :id, :display, :email, 'active', :now, :now)"
                ),
                {
                    "id": user_id,
                    "display": display,
                    "email": f"{user_id}@example.com",
                    "now": NOW,
                },
            )
        connection.execute(
            text(
                "INSERT INTO projects (id, name, code, description, "
                "created_at, updated_at) VALUES "
                "('p1','Demo','demo',NULL,:now,:now)"
            ),
            {"now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO pipelines (id, project_id, name, code, "
                "description, status, created_at, updated_at) VALUES "
                "('pl1','p1','Demo','demo',NULL,'active',:now,:now)"
            ),
            {"now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO pipeline_versions (id, pipeline_id, "
                "version_number, etl_plan_json, hocon_text, artifact_digest, "
                "is_immutable, created_at, updated_at) VALUES "
                "('v1','pl1',1,NULL,'conf',:digest,1,:now,:now)"
            ),
            {"digest": "a" * 64, "now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO project_role_grants (id, project_id, user_id, "
                "role_slot, created_at, updated_at) VALUES "
                "('g1','p1','u2','data_checker',:now,:now), "
                "('g2','p1','u3','security_checker',:now,:now)"
            ),
            {"now": NOW},
        )
    return engine


# -- shared Commit fixtures ---------------------------------------------------


def make_preparation(**overrides) -> dict:
    preparation = {
        "preparation_id": "prep_t001",
        "version_id": "v1",
        "project_id": "p1",
        "applicant_id": "u1",
        "status": "APPROVED",
        "fingerprint": "sha256:" + "b" * 64,
    }
    preparation.update(overrides)
    return preparation


def make_version(**overrides) -> dict:
    version = {
        "version_id": "v1",
        "pipeline_id": "pl1",
        "is_immutable": True,
        "artifact_digest": "a" * 64,
    }
    version.update(overrides)
    return version


def make_approvals(**overrides) -> list[dict]:
    approvals = [
        {
            "id": "apr1",
            "required_role": "data_checker",
            "status": "APPROVED",
            "decision": "approved",
            "approver_id": "u2",
        },
        {
            "id": "apr2",
            "required_role": "security_checker",
            "status": "APPROVED",
            "decision": "approved",
            "approver_id": "u3",
        },
    ]
    for key, value in overrides.items():
        for row in approvals:
            row[key] = value(row) if callable(value) else value
    return approvals


async def persist_preparation(session_factory, preparation) -> None:
    """Insert the durable Preparation row so commit's NOT_PERSISTED guard
    passes for a memory-dict preparation (the API flow creates it through the
    prepare orchestrator; commit tests here only need the row to exist)."""
    from datetime import datetime, timezone

    from app.models.tables import Preparation

    now = datetime(2026, 10, 24, tzinfo=timezone.utc)
    with session_factory() as session:
        session.add(
            Preparation(
                id=preparation["preparation_id"],
                version_id=preparation["version_id"],
                project_id=preparation["project_id"],
                applicant_id=preparation["applicant_id"],
                status="APPROVED",
                risk_level="P1",
                fingerprint=preparation["fingerprint"],
                artifact_digest="a" * 64,
                environment="test",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
