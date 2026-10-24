"""SecretPort real-implementation tests (task: SecretPort 真实现).

Covers the environment-backed reference resolution (fail-closed when unset),
and the two consumers: the ``conn.test`` probe path and the capability-bound
``secret.materialize`` Tool Broker tool (issue → verify → single consumption).
"""

from __future__ import annotations

import pytest

from app.adapters.env import EnvSecretAdapter, env_var_name_for
from app.adapters.stub.secret import StubSecretAdapter
from app.core.harness.errors import HarnessError
from harness.tools import (
    make_conn_test_handler,
    make_secret_materialize_handler,
    register_tool_handlers,
)
from harness.tools.db_tools import _connect_postgres


# -- reference resolution ------------------------------------------------------


def test_reference_maps_to_deterministic_env_variable():
    assert env_var_name_for("secret://connections/conn_demo_001") == (
        "SECRET_CONN_DEMO_001"
    )


def test_unsupported_reference_is_rejected():
    with pytest.raises(HarnessError) as invalid:
        env_var_name_for("secret://vault/other")
    assert invalid.value.error_code == "SECRET-422"


async def test_materialize_resolves_env_value(monkeypatch):
    monkeypatch.setenv("SECRET_CONN_X", "postgresql://u:p@h/db")
    adapter = EnvSecretAdapter()
    value = await adapter.materialize(
        "secret://connections/conn_x", {"connection_id": "conn_x"}
    )
    assert value == "postgresql://u:p@h/db"


async def test_materialize_fails_closed_when_unset(monkeypatch):
    monkeypatch.delenv("SECRET_CONN_Y", raising=False)
    with pytest.raises(HarnessError) as missing:
        await EnvSecretAdapter().materialize(
            "secret://connections/conn_y", {"connection_id": "conn_y"}
        )
    assert missing.value.error_code == "SECRET-503"
    assert missing.value.details["variable"] == "SECRET_CONN_Y"


async def test_get_ref_returns_state_never_the_value(monkeypatch):
    monkeypatch.setenv("SECRET_CONN_Z", "postgresql://u:p@h/db")
    adapter = EnvSecretAdapter()
    configured = await adapter.get_ref("secret://connections/conn_z")
    not_configured = await adapter.get_ref("secret://connections/conn_missing")
    assert configured["state"] == "configured"
    assert not_configured["state"] == "not_configured"
    assert "postgresql://" not in str(configured)
    assert "postgresql://" not in str(not_configured)


# -- consumer: conn.test --------------------------------------------------------


async def test_conn_test_materializes_through_real_secret_port(kernel, monkeypatch):
    monkeypatch.setenv("SECRET_CONN_Q", "postgresql://u:p@127.0.0.1:1/db")
    handler = make_conn_test_handler(
        secret=EnvSecretAdapter(), connector=_connect_postgres
    )
    kernel.broker.register_handler("conn.test", handler)
    intent = {
        "tool": "conn.test",
        "actor_id": "u1",
        "project_id": "p1",
        "environment": "test",
        "resource_scope": {"connection_id": "conn_q", "db_type": "postgresql"},
    }
    decision = kernel.pdp.decide(intent)

    result = await kernel.broker.execute(intent, policy_decision=decision)

    # The env-provided DSN is genuinely attempted; the unreachable host yields
    # an honest de-identified failure — never a fabricated success.
    assert result["status"] == "SUCCEEDED"
    assert result["output"]["success"] is False


# -- consumer: secret.materialize tool ------------------------------------------


def _materialize_intent():
    return {
        "tool": "secret.materialize",
        "actor_id": "worker1",
        "project_id": "p1",
        "environment": "test",
        "resource_scope": {"connection_id": "conn_m"},
        "artifact_digest": "a" * 64,
        "preparation_id": "prep_1",
        "execution_run_id": "run_1",
    }


def _approval_facts():
    return [
        {"decision": "APPROVED", "approver_id": "u2", "required_role": "data_checker"},
        {
            "decision": "APPROVED",
            "approver_id": "u3",
            "required_role": "security_checker",
        },
    ]


async def test_secret_materialize_tool_verifies_and_consumes_capability(
    kernel, seeded_engine, session_factory, ledger, monkeypatch
):
    monkeypatch.setenv("SECRET_CONN_M", "postgresql://u:p@h/db")
    register_tool_handlers(
        kernel, session_factory=session_factory, ledger=ledger, secret=EnvSecretAdapter()
    )
    intent = _materialize_intent()
    decision = kernel.pdp.decide(intent)
    issued = await kernel.issue_capability(
        {
            "tool": "secret.materialize",
            "sub": "worker1",
            "project_id": "p1",
            "environment": "test",
            "resource_scope": {"connection_id": "conn_m"},
            "artifact_digest": "a" * 64,
            "preparation_id": "prep_1",
            "execution_run_id": "run_1",
        },
        approval_facts=_approval_facts(),
    )

    result = await kernel.broker.execute(
        intent,
        policy_decision=decision,
        capability_token=issued["token"],
        idempotency_key="mat-key-1",
    )

    assert result["status"] == "SUCCEEDED"
    assert result["output"]["secret_value"] == "postgresql://u:p@h/db"

    # Single consumption: a replayed token is rejected fail-closed.
    with pytest.raises(HarnessError):
        await kernel.broker.execute(
            intent,
            policy_decision=decision,
            capability_token=issued["token"],
            idempotency_key="mat-key-2",
        )


async def test_secret_materialize_without_capability_is_rejected(
    kernel, seeded_engine, session_factory, ledger, monkeypatch
):
    monkeypatch.setenv("SECRET_CONN_M", "postgresql://u:p@h/db")
    register_tool_handlers(
        kernel, session_factory=session_factory, ledger=ledger, secret=EnvSecretAdapter()
    )
    intent = _materialize_intent()
    decision = kernel.pdp.decide(intent)

    with pytest.raises(HarnessError) as rejected:
        await kernel.broker.execute(intent, policy_decision=decision)
    assert rejected.value.error_code == "TB-403"


async def test_stub_secret_adapter_remains_fail_closed():
    with pytest.raises(NotImplementedError):
        await StubSecretAdapter().materialize("secret://connections/c", {})


async def test_materialize_handler_validates_scope():
    handler = make_secret_materialize_handler(secret=StubSecretAdapter())
    with pytest.raises(HarnessError) as invalid:
        await handler({"resource_scope": {}})
    assert invalid.value.error_code == "TB-400"
