"""Tool Broker adapter tests (Spec 3.6, task: 工具适配器).

Every test drives the real broker path (registered handler + PDP-bound
intent + replay guard). Downstream externals are stubbed only where no
dependency exists in-process (SecretPort values, the database connector);
the PostgreSQL connect failure path runs against the real psycopg driver.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.adapters.stub.secret import StubSecretAdapter
from app.core.harness.errors import HarnessError
from app.models.tables import AuditEvent, ExecutionRun
from harness.tools import (
    make_conn_test_handler,
    make_file_parse_handler,
    make_metadata_profile_handler,
    register_tool_handlers,
)
from harness.tools.db_tools import _connect_postgres

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


class _FakeSecret:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def materialize(self, secret_ref: str, context: dict) -> str:
        return self._dsn

    async def get_ref(self, secret_ref: str) -> dict:
        return {"ref": secret_ref, "state": "configured"}


class _FakeConnection:
    def __init__(self, tables, columns, samples) -> None:
        self._tables = tables
        self._columns = columns
        self._samples = samples

    def query(self, sql, params):
        if "information_schema.tables" in sql:
            return self._tables
        if "information_schema.columns" in sql:
            return self._columns
        return self._samples

    def close(self):
        pass


def _seed_run(session_factory, run_id, status="queued", engine_job_id=None):
    with session_factory() as session:
        session.add(
            ExecutionRun(
                id=run_id,
                version_id="v1",
                preparation_id="prep_t001",
                status=status,
                engine_job_id=engine_job_id,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


def _intent(tool, scope, project_id="p1"):
    return {
        "tool": tool,
        "actor_id": "u1",
        "project_id": project_id,
        "environment": "test",
        "resource_scope": scope,
    }


def _ledger_types(session_factory):
    with session_factory() as session:
        return (
            session.execute(
                select(AuditEvent.event_type).order_by(AuditEvent.chain_seq)
            )
            .scalars()
            .all()
        )


# -- conn.test ---------------------------------------------------------------


async def test_conn_test_reports_unreachable_host_honestly(kernel, seeded_engine):
    handler = make_conn_test_handler(
        secret=_FakeSecret("postgresql://u:p@127.0.0.1:1/db"),
        connector=_connect_postgres,  # real psycopg path
    )
    kernel.broker.register_handler("conn.test", handler)
    intent = _intent("conn.test", {"connection_id": "c1", "db_type": "postgresql", "timeout_ms": 1000})
    decision = kernel.pdp.decide(intent)

    result = await kernel.broker.execute(intent, policy_decision=decision)

    assert result["status"] == "SUCCEEDED"
    assert result["output"]["success"] is False
    # The real driver failure is classified and de-identified; whether the
    # OS stack refuses or drops the connection decides the stable code.
    assert result["output"]["error_code"] in {"CONNECTION_FAILED", "TIMEOUT"}
    assert result["output"]["latency_ms"] >= 0
    assert len(result["output_digest"]) == 64


async def test_conn_test_without_secret_provider_fails_closed(kernel, seeded_engine):
    handler = make_conn_test_handler(secret=StubSecretAdapter())
    kernel.broker.register_handler("conn.test", handler)
    intent = _intent("conn.test", {"connection_id": "c1", "db_type": "postgresql"})
    decision = kernel.pdp.decide(intent)

    with pytest.raises(HarnessError) as unavailable:
        await kernel.broker.execute(intent, policy_decision=decision)
    assert unavailable.value.error_code == "TB-503"


async def test_conn_test_unsupported_db_type_fails_closed(kernel, seeded_engine):
    handler = make_conn_test_handler(secret=_FakeSecret("mysql://u:p@h/db"))
    kernel.broker.register_handler("conn.test", handler)
    intent = _intent("conn.test", {"connection_id": "c1", "db_type": "mysql"})
    decision = kernel.pdp.decide(intent)

    with pytest.raises(HarnessError) as unavailable:
        await kernel.broker.execute(intent, policy_decision=decision)
    assert unavailable.value.error_code == "TB-503"


# -- metadata.profile ---------------------------------------------------------


async def test_metadata_profile_assembles_masked_results(kernel, seeded_engine):
    connection = _FakeConnection(
        tables=[{"table_schema": "public", "table_name": "t1", "table_type": "BASE TABLE"}],
        columns=[
            {
                "table_schema": "public",
                "table_name": "t1",
                "column_name": "id",
                "data_type": "integer",
                "is_nullable": "NO",
                "ordinal_position": 1,
            }
        ],
        samples=[{"id": 1, "phone": "13800138000"}],
    )
    handler = make_metadata_profile_handler(
        secret=_FakeSecret("postgresql://u:p@127.0.0.1:1/db"),
        connector=lambda dsn, timeout, readonly: connection,
    )
    kernel.broker.register_handler("metadata.profile", handler)
    profile = {
        "schemas": ["public"],
        "tables": ["t1"],
        "sample_rows": 10,
        "readonly": True,
    }
    intent = _intent(
        "metadata.profile", {"connection_id": "c1", "db_type": "postgresql", "profile": profile}
    )
    decision = kernel.pdp.decide(intent)

    result = await kernel.broker.execute(intent, policy_decision=decision)

    assert result["status"] == "SUCCEEDED"
    output = result["output"]
    assert output["profile_status"] == "completed"
    assert output["tables"][0]["table_name"] == "t1"
    assert output["columns"][0]["data_type"] == "integer"
    # Samples are masked before they ever leave the tool.
    assert output["masked_samples"][0]["phone"] != "13800138000"


async def test_metadata_profile_requires_readonly_intent(kernel, seeded_engine):
    handler = make_metadata_profile_handler(secret=_FakeSecret("postgresql://u:p@h/db"))
    kernel.broker.register_handler("metadata.profile", handler)
    intent = _intent(
        "metadata.profile",
        {
            "connection_id": "c1",
            "db_type": "postgresql",
            "profile": {"schemas": ["public"], "tables": ["t1"], "sample_rows": 0, "readonly": False},
        },
    )
    decision = kernel.pdp.decide(intent)

    with pytest.raises(HarnessError) as invalid:
        await kernel.broker.execute(intent, policy_decision=decision)
    assert invalid.value.error_code == "META-422"


# -- file.parse ---------------------------------------------------------------


async def test_file_parse_csv_and_json(kernel, seeded_engine, tmp_path):
    kernel.broker.register_handler("file.parse", make_file_parse_handler())

    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,amount\n1,10.5\n2,20\n", encoding="utf-8")
    intent = _intent(
        "file.parse", {"file_format": "csv", "file_path": str(csv_path), "file_digest": "a" * 64}
    )
    decision = kernel.pdp.decide(intent)
    result = await kernel.broker.execute(intent, policy_decision=decision)
    assert result["status"] == "SUCCEEDED"
    schema = result["output"]["file_schema"]
    assert schema["fields"] == [
        {"name": "order_id", "type": "integer"},
        {"name": "amount", "type": "number"},
    ]
    assert schema["row_count"] == 2

    json_path = tmp_path / "rows.json"
    json_path.write_text(
        json.dumps([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]), encoding="utf-8"
    )
    intent = _intent(
        "file.parse", {"file_format": "json", "file_path": str(json_path), "file_digest": "a" * 64}
    )
    decision = kernel.pdp.decide(intent)
    result = await kernel.broker.execute(intent, policy_decision=decision)
    assert result["output"]["file_schema"]["row_count"] == 2
    assert result["output"]["file_schema"]["fields"][0] == {"name": "id", "type": "integer"}


async def test_file_parse_failures_are_honest(kernel, seeded_engine, tmp_path):
    kernel.broker.register_handler("file.parse", make_file_parse_handler())

    broken = tmp_path / "broken.csv"
    broken.write_bytes(b"\xff\xfe\x00broken")
    intent = _intent(
        "file.parse", {"file_format": "csv", "file_path": str(broken), "file_digest": "a" * 64}
    )
    decision = kernel.pdp.decide(intent)
    result = await kernel.broker.execute(intent, policy_decision=decision)
    assert result["status"] == "FAILED"
    assert result["domain_code"] == "TB-424"
    assert result["output"] is None

    missing = tmp_path / "missing.csv"
    intent = _intent(
        "file.parse", {"file_format": "csv", "file_path": str(missing), "file_digest": "a" * 64}
    )
    decision = kernel.pdp.decide(intent)
    result = await kernel.broker.execute(intent, policy_decision=decision)
    assert result["status"] == "FAILED"

    intent = _intent("file.parse", {"file_format": "parquet", "file_path": "x", "file_digest": "a" * 64})
    decision = kernel.pdp.decide(intent)
    with pytest.raises(HarnessError) as unavailable:
        await kernel.broker.execute(intent, policy_decision=decision)
    assert unavailable.value.error_code == "TB-503"


# -- benchmark.run ------------------------------------------------------------


async def test_benchmark_run_records_accepted_run(
    kernel, seeded_engine, session_factory, ledger
):
    register_tool_handlers(kernel, session_factory=session_factory, ledger=ledger, secret=StubSecretAdapter())
    intent = _intent(
        "benchmark.run",
        {"suite_id": "suite_demo_001", "layer": "L0", "dataset_version": "ds_demo_v1"},
    )
    decision = kernel.pdp.decide(intent)

    result = await kernel.broker.execute(
        intent, policy_decision=decision, idempotency_key="bench-key-1"
    )

    assert result["status"] == "SUCCEEDED"
    output = result["output"]
    assert output["benchmark_run_id"].startswith("bench_")
    assert output["status"] == "running"
    assert output["started_at"]


# -- run.cancel ---------------------------------------------------------------


def _registered_kernel(kernel, session_factory, ledger):
    register_tool_handlers(
        kernel, session_factory=session_factory, ledger=ledger, secret=StubSecretAdapter()
    )
    return kernel


async def test_run_cancel_control_plane_transaction(
    kernel, seeded_engine, session_factory, ledger
):
    _registered_kernel(kernel, session_factory, ledger)
    _seed_run(session_factory, "run_1")
    intent = _intent(
        "run.cancel", {"execution_run_id": "run_1", "reason_digest": "b" * 64}
    )
    decision = kernel.pdp.decide(intent)

    result = await kernel.broker.execute(
        intent, policy_decision=decision, idempotency_key="cancel-key-1"
    )

    assert result["status"] == "SUCCEEDED"
    assert result["output"]["status"] == "cancelled"
    assert result["output"]["cancelled_at"]
    with session_factory() as session:
        row = session.execute(
            select(ExecutionRun).where(ExecutionRun.id == "run_1")
        ).scalar_one()
        assert row.status == "cancelled"
        assert row.finished_at is not None
    assert _ledger_types(session_factory) == ["run.cancel_requested", "run.cancelled"]


async def test_run_cancel_missing_row_fails_closed_without_writes(
    kernel, seeded_engine, session_factory, ledger
):
    _registered_kernel(kernel, session_factory, ledger)
    intent = _intent(
        "run.cancel", {"execution_run_id": "run_missing", "reason_digest": "b" * 64}
    )
    decision = kernel.pdp.decide(intent)

    with pytest.raises(HarnessError) as rejected:
        await kernel.broker.execute(
            intent, policy_decision=decision, idempotency_key="cancel-key-2"
        )
    assert rejected.value.error_code == "OPS-409"
    assert rejected.value.details["reason"] == "NOT_PERSISTED"
    assert _ledger_types(session_factory) == []


async def test_run_cancel_terminal_state_rejected(
    kernel, seeded_engine, session_factory, ledger
):
    _registered_kernel(kernel, session_factory, ledger)
    _seed_run(session_factory, "run_2", status="succeeded")
    intent = _intent(
        "run.cancel", {"execution_run_id": "run_2", "reason_digest": "b" * 64}
    )
    decision = kernel.pdp.decide(intent)

    with pytest.raises(HarnessError) as rejected:
        await kernel.broker.execute(
            intent, policy_decision=decision, idempotency_key="cancel-key-3"
        )
    assert rejected.value.error_code == "OPS-409"
    assert rejected.value.details["status"] == "succeeded"


# -- shadow.rollback ----------------------------------------------------------


async def test_shadow_rollback_completes_control_plane(
    kernel, seeded_engine, session_factory, ledger
):
    _registered_kernel(kernel, session_factory, ledger)
    _seed_run(session_factory, "run_3", status="failed")
    intent = _intent(
        "shadow.rollback", {"execution_run_id": "run_3", "reason_digest": "b" * 64}
    )
    decision = kernel.pdp.decide(intent)

    result = await kernel.broker.execute(
        intent, policy_decision=decision, idempotency_key="rollback-key-1"
    )

    assert result["status"] == "SUCCEEDED"
    output = result["output"]
    assert output["rollback_status"] == "completed"
    assert output["finished_at"]
    types = _ledger_types(session_factory)
    assert types == [
        "run.rollback_requested",
        "run.rolled_back",
        "run.cleaned",
    ]
    assert output["ledger_event_id"]


async def test_shadow_rollback_requires_terminal_failed_or_cancelled(
    kernel, seeded_engine, session_factory, ledger
):
    _registered_kernel(kernel, session_factory, ledger)
    _seed_run(session_factory, "run_4")  # queued is not rollback-eligible
    intent = _intent(
        "shadow.rollback", {"execution_run_id": "run_4", "reason_digest": "b" * 64}
    )
    decision = kernel.pdp.decide(intent)

    with pytest.raises(HarnessError) as rejected:
        await kernel.broker.execute(
            intent, policy_decision=decision, idempotency_key="rollback-key-2"
        )
    assert rejected.value.error_code == "OPS-409"
    assert _ledger_types(session_factory) == []


# -- broker integration --------------------------------------------------------


async def test_stale_policy_decision_is_rejected(kernel, seeded_engine):
    kernel.broker.register_handler("file.parse", make_file_parse_handler())
    intent = _intent(
        "file.parse",
        {"file_format": "json", "file_path": "x.json", "file_digest": "a" * 64},
    )
    other = _intent(
        "file.parse",
        {"file_format": "json", "file_path": "y.json", "file_digest": "a" * 64},
    )
    decision = kernel.pdp.decide(other)

    with pytest.raises(HarnessError) as rejected:
        await kernel.broker.execute(intent, policy_decision=decision)
    assert rejected.value.error_code == "TB-403"
