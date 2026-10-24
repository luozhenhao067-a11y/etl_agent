"""Composition root for the API layer.

Only Port implementations are injected into routes. The Harness is switchable
through ``Settings.harness`` (env ``HARNESS``): ``stub`` keeps the fail-closed
stub (default), ``kernel`` wires the real Harness (Spec 3-5) — PDP, Ed25519
capabilities, the Redis replay guard, the SQL Outbox and the SQL Evidence
Ledger — and requires ``STORAGE=postgres`` with ``DATABASE_URL``, ``REDIS_URL``
and the signing keys, failing fast at startup otherwise (user-approved
2026-10-24). With the kernel, ``container.commit`` exposes the API-14 Commit
orchestrator that owns the atomic execution_runs + Outbox + audit transaction.

The storage backend is switchable through ``Settings.storage`` (env
``STORAGE``): ``memory`` keeps the self-contained demo behaviour (default,
no PostgreSQL required), ``postgres`` wires the SQL repository in
``app.adapters.sql`` to the engine controlled by ``DATABASE_URL``. Spec 10.3
entities (connections, preparations, designs, benchmarks, outbox) stay in
``MemoryState`` for both backends until Spec P-04…P-10 are confirmed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.adapters.memory.repository import InMemoryRepository
from app.adapters.memory.seed import seed_all, seed_state
from app.adapters.memory.state import MemoryState
from app.adapters.env import EnvSecretAdapter
from app.adapters.local.exec import LocalAsyncExecAdapter
from app.adapters.sql.repository import SqlRepository
from app.adapters.stub.exec import StubExecAdapter
from app.adapters.stub.harness import StubHarnessAdapter
from app.adapters.stub.secret import StubSecretAdapter
from app.config import Settings
from app.core.audit import AuditService
from app.core.utils import digest_of
from app.core.harness.capability import CapabilityService
from app.core.harness.kernel import HarnessKernel
from app.core.idempotency import InMemoryIdempotencyStore
from app.core.utils import now
from app.db.session import create_db_engine, make_session_factory
from app.ports.exec import ExecPort
from app.ports.harness import HarnessPort
from app.ports.repository import RepositoryPort
from app.ports.secret import SecretPort
from harness.core.keys import load_private_key
from harness.core.ledger_sql import SqlLedger
from harness.core.outbox_sql import SqlOutbox
from harness.core.redis_client import create_redis_client
from harness.core.replay_redis import RedisReplayGuard
from harness.services.commit_tx import CommitOrchestrator
from harness.services.evaluation import BenchmarkEvaluationService
from harness.services.gateway import KernelHarnessAdapter
from harness.services.prepare_tx import PrepareOrchestrator
from harness.tools import register_tool_handlers
from harness.worker import ExecutionWorker, OutboxDispatcher, PendingCommandStore


@dataclass
class Container:
    settings: Settings
    repository: RepositoryPort
    state: MemoryState
    harness: HarnessPort
    secret: SecretPort
    exec: ExecPort
    idempotency: InMemoryIdempotencyStore
    audit: AuditService
    # Kernel mode only (HARNESS=kernel): the shared session factory, the
    # API-12 Prepare / API-14 Commit orchestrators, and the Spec 5.5 step 4+
    # dispatch layer (token handoff store, Worker, Outbox dispatcher). All
    # stay None under the stub.
    session_factory: Any | None = None
    prepare: PrepareOrchestrator | None = None
    commit: CommitOrchestrator | None = None
    command_store: Any | None = None
    worker: Any | None = None
    dispatcher: Any | None = None
    # API-18 evaluation service (Spec 11.1 run_benchmark); None under stub.
    evaluation: Any | None = None
    started_at: object = field(default_factory=now)

    async def record_audit(
        self,
        *,
        project_id: str,
        actor_id: str,
        event_type: str,
        resource_type: str,
        resource_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Single audit facade for the Spec 12.2 staging-path events.

        Kernel mode writes the durable SQL Evidence Ledger through the
        gateway (hash chain, Spec 3.9) — writing these rows through the
        staging AuditService instead would leave ``external_entries`` in the
        chain verification. Stub/memory mode keeps the staging AuditService
        so the self-contained demo behaviour is unchanged.
        """
        if self.commit is not None:
            await self.harness.append_ledger(
                {
                    "project_id": project_id,
                    "actor_id": actor_id,
                    "event_type": event_type,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "payload_digest": digest_of(payload),
                }
            )
        else:
            self.audit.append(
                project_id=project_id,
                actor_id=actor_id,
                event_type=event_type,
                resource_type=resource_type,
                resource_id=resource_id,
                payload=payload,
            )


def build_container(
    settings: Settings | None = None,
    repository: RepositoryPort | None = None,
) -> Container:
    resolved = settings or Settings.from_env()
    state = MemoryState()
    session_factory: Any | None = None
    # Memory/stub mode keeps the fail-closed stub; kernel mode swaps in the
    # environment-backed provider below (shared by the Tool Broker handlers).
    secret: SecretPort = StubSecretAdapter()
    # The execution engine: the stub honestly fails every submission
    # (EXEC_ENGINE_NOT_READY / TB-503); EXEC_ENGINE=local (kernel mode)
    # wires the in-process async adapter so Outbox commands are truly
    # consumed and runs reach a terminal state through supervision.
    exec_port: ExecPort = (
        LocalAsyncExecAdapter() if resolved.exec_engine == "local" else StubExecAdapter()
    )

    if repository is not None:
        # Injected backend (test fixtures): seed both layers inside it.
        seed_all(repository, state, resolved.default_project_id)
    elif resolved.storage == "postgres":
        engine = create_db_engine()
        session_factory = make_session_factory(engine)
        repository = SqlRepository(session_factory)
        # The 13-table rows come from the live database (建表/seed_data.py);
        # only the memory-only Spec 10.3 entities are seeded here.
        seed_state(state, resolved.default_project_id)
    else:
        repository = InMemoryRepository()
        seed_all(repository, state, resolved.default_project_id)

    harness: HarnessPort
    prepare: PrepareOrchestrator | None = None
    commit: CommitOrchestrator | None = None
    command_store: Any | None = None
    worker: Any | None = None
    dispatcher: Any | None = None
    evaluation: Any | None = None
    if resolved.harness == "kernel":
        # Fail-fast: kernel mode boots only on the SQL path with a persisted
        # signing key; silently degrading would violate fail-closed.
        if session_factory is None:  # defensive; Settings already enforces this
            raise RuntimeError("HARNESS=kernel requires STORAGE=postgres")
        # Real SecretPort: references materialise from the process environment
        # at call time; unset references fail closed (SECRET-503).
        secret = EnvSecretAdapter()
        capability_key = load_private_key("CAPABILITY_SIGNING_KEY")
        try:
            ledger_key = load_private_key("LEDGER_CHECKPOINT_KEY")
        except RuntimeError:
            # Without its key, checkpoint signing fails closed at use; token
            # issuance and the hash chain itself do not need it.
            ledger_key = None
        # One shared replay guard: endpoint replay checks and the broker's
        # single-use capability consumption must see the same atomic store
        # (Redis), not two independent in-memory guards.
        replay_guard = RedisReplayGuard(create_redis_client())
        kernel = HarnessKernel(
            capability=CapabilityService(private_key=capability_key),
            replay=replay_guard,
        )
        # One shared Outbox/Ledger pair: the adapter commits single writes,
        # the Commit orchestrator reuses them inside its atomic transaction.
        outbox = SqlOutbox()
        ledger = SqlLedger(private_key=ledger_key)
        harness = KernelHarnessAdapter(
            kernel=kernel,
            session_factory=session_factory,
            replay=replay_guard,
            outbox=outbox,
            ledger=ledger,
        )
        # Spec 5.5 step 4+ dispatch layer: commit hands the plaintext token
        # to the store (in-process only), the dispatcher delivers queued
        # commands to the Worker, which owns the run state machine. The exec
        # port stays a stub until a real engine adapter is wired; the Worker
        # then fails runs closed with EXEC_ENGINE_NOT_READY (TB-503).
        command_store = PendingCommandStore()
        worker = ExecutionWorker(
            kernel=kernel,
            session_factory=session_factory,
            ledger=ledger,
            exec_port=exec_port,
        )
        dispatcher = OutboxDispatcher(
            session_factory=session_factory,
            outbox=outbox,
            ledger=ledger,
            worker=worker,
            commands=command_store,
        )
        commit = CommitOrchestrator(
            kernel=kernel,
            session_factory=session_factory,
            outbox=outbox,
            ledger=ledger,
            data_environment=resolved.data_environment,
            command_store=command_store,
        )
        prepare = PrepareOrchestrator(
            kernel=kernel,
            session_factory=session_factory,
            ledger=ledger,
            environment=resolved.data_environment,
        )
        # Tool adapters for the six registered tools (Spec 3.6): conn.test,
        # metadata.profile, file.parse, benchmark.run, run.cancel,
        # shadow.rollback. Tools without a usable downstream dependency fail
        # closed inside their handlers (TB-503), never with fake results.
        register_tool_handlers(
            kernel,
            session_factory=session_factory,
            ledger=ledger,
            secret=secret,
            exec_port=exec_port,
        )
        # API-18 评测服务 (Spec 11.1 run_benchmark): closes accepted
        # benchmark runs out with the registered benchmark.run.completed
        # ledger event; in stub mode the API keeps failing closed (BENCH-503).
        evaluation = BenchmarkEvaluationService(
            append_ledger=harness.append_ledger, runs=state.benchmark_runs
        )
    else:
        harness = StubHarnessAdapter()

    return Container(
        settings=resolved,
        repository=repository,
        state=state,
        harness=harness,
        secret=secret,
        exec=exec_port,
        idempotency=InMemoryIdempotencyStore(),
        audit=AuditService(repository),
        session_factory=session_factory,
        prepare=prepare,
        commit=commit,
        command_store=command_store,
        worker=worker,
        dispatcher=dispatcher,
        evaluation=evaluation,
    )
