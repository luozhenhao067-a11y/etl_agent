from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.adapters.memory.harness import InMemoryHarnessAdapter
from app.core.harness import (
    CapabilityService,
    EvidenceLedger,
    HarnessError,
    HarnessKernel,
    InMemoryOutbox,
    PolicyDecisionPoint,
    ReplayGuard,
    ToolBroker,
    ToolDependencyError,
)
from app.core.utils import digest_of

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
NOW = datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)


@dataclass
class FakeClock:
    value: datetime = NOW

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value = self.value + timedelta(seconds=seconds)


def private_key(seed: int = 1) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes([seed]) * 32)


def base_intent(tool: str = "etl.execute", **overrides):
    intent = {
        "request_id": "req_1",
        "tool": tool,
        "actor_id": "user_demo_005",
        "project_id": "prj_demo_001",
        "environment": "prod",
        "resource_scope": {"tables": ["orders"]},
        "artifact_digest": DIGEST_A,
        "preparation_id": "prep_1",
        "execution_run_id": "run_1",
        "requested_budget": {"max_rows": 1000},
    }
    intent.update(overrides)
    return intent


def base_claims(**overrides):
    claims = {
        "sub": "user_demo_005",
        "project_id": "prj_demo_001",
        "environment": "prod",
        "tool": "etl.execute",
        "resource_scope": {"tables": ["orders"]},
        "artifact_digest": DIGEST_A,
        "preparation_id": "prep_1",
        "execution_run_id": "run_1",
        "applicant_id": "user_demo_001",
    }
    claims.update(overrides)
    return claims


def approval_facts():
    # Spec 4.6: approval decision/status values are uppercase.
    return [
        {
            "approver_id": "user_demo_002",
            "decision": "APPROVED",
            "role_slot": "data_checker",
            "preparation_id": "prep_1",
            "artifact_digest": DIGEST_A,
        },
        {
            "approver_id": "user_demo_003",
            "decision": "APPROVED",
            "role_slot": "security_checker",
            "preparation_id": "prep_1",
            "artifact_digest": DIGEST_A,
        },
    ]


def assert_code(code: str, fn, *args, **kwargs):
    with pytest.raises(HarnessError) as caught:
        fn(*args, **kwargs)
    assert caught.value.error_code == code
    return caught.value


async def assert_async_code(code: str, fn, *args, **kwargs):
    with pytest.raises(HarnessError) as caught:
        await fn(*args, **kwargs)
    assert caught.value.error_code == code
    return caught.value


# PDP


def test_pdp_allows_execution_with_both_slots():
    pdp = PolicyDecisionPoint(clock=FakeClock())
    decision = pdp.decide(base_intent())

    assert decision["decision"] == "ALLOW"
    assert decision["state"] == "EVALUATED"
    assert decision["risk_level"] == "P1"
    assert decision["required_slots"] == ["data_checker", "security_checker"]
    assert decision["constraints"]["four_eye_minimum"] is True
    assert len(decision["decision_digest"]) == 64
    assert pdp.get_decision(decision["decision_digest"])["decision_digest"] == decision[
        "decision_digest"
    ]


def test_pdp_rejects_unknown_tool():
    pdp = PolicyDecisionPoint(clock=FakeClock())
    assert_code("PDP-400", pdp.decide, base_intent("drop.table"))


def test_pdp_requires_resource_scope():
    pdp = PolicyDecisionPoint(clock=FakeClock())
    intent = base_intent()
    del intent["resource_scope"]
    assert_code("PDP-422", pdp.decide, intent)


def test_pdp_scope_tool_allowlist_is_enforced():
    pdp = PolicyDecisionPoint(clock=FakeClock())
    assert_code(
        "PDP-422",
        pdp.decide,
        base_intent(resource_scope={"tools": ["conn.test"]}),
    )
    assert_code(
        "PDP-422",
        pdp.decide,
        base_intent(resource_scope={"tools": "etl.execute"}),
    )


def test_pdp_requires_artifact_digest_for_execution():
    pdp = PolicyDecisionPoint(clock=FakeClock())
    intent = base_intent()
    del intent["artifact_digest"]
    assert_code("PDP-422", pdp.decide, intent)


def test_pdp_denial_is_explicit():
    pdp = PolicyDecisionPoint(clock=FakeClock(), deny_tools={"etl.execute"})
    decision = pdp.decide(base_intent())
    assert decision["decision"] == "DENY"
    assert decision["state"] == "DENIED"


def test_pdp_engine_error_and_weakened_slots_fail_closed():
    def broken(intent, spec):
        raise RuntimeError("policy storage down")

    pdp = PolicyDecisionPoint(clock=FakeClock(), evaluator=broken)
    assert_code("PDP-500", pdp.decide, base_intent())

    def weak(intent, spec):
        return {"required_slots": ["data_checker"]}

    pdp = PolicyDecisionPoint(clock=FakeClock(), evaluator=weak)
    assert_code("PDP-500", pdp.decide, base_intent())


def test_pdp_can_bind_an_evaluated_decision():
    pdp = PolicyDecisionPoint(clock=FakeClock())
    decision = pdp.decide(base_intent())
    bound = pdp.bind_to_preparation(decision["decision_digest"], "prep_1")
    assert bound["state"] == "BOUND_TO_PREPARATION"
    assert bound["preparation_id"] == "prep_1"


# Capability


def test_capability_issue_verify_consume_and_no_plaintext_storage():
    clock = FakeClock()
    service = CapabilityService(private_key=private_key(), clock=clock)
    issued = service.issue(base_claims(), approval_facts=approval_facts())

    assert issued["claims"]["iat"] == int(NOW.timestamp())
    assert issued["claims"]["exp"] == int(NOW.timestamp()) + 300
    assert len(issued["token_digest"]) == 64
    assert "token" not in service.get_record(issued["jti"])

    expected = {
        key: base_claims()[key]
        for key in (
            "sub",
            "project_id",
            "environment",
            "tool",
            "resource_scope",
            "artifact_digest",
            "preparation_id",
            "execution_run_id",
        )
    }
    verified = service.verify(issued["token"], expected)
    assert verified["status"] == "PRESENTED"
    consumed = service.consume(issued["jti"], issued["token_digest"])
    assert consumed["status"] == "CONSUMED"


def test_capability_rejects_tampered_signature():
    service = CapabilityService(private_key=private_key(), clock=FakeClock())
    issued = service.issue(base_claims(), approval_facts=approval_facts())
    parts = issued["token"].split(".")
    tampered = ".".join([parts[0], parts[1], parts[2][:-1] + ("A" if parts[2][-1] != "A" else "B")])
    assert_code("CAP-401", service.verify, tampered)


def test_capability_scope_and_binding_mismatch_are_distinct():
    service = CapabilityService(private_key=private_key(), clock=FakeClock())
    issued = service.issue(base_claims(), approval_facts=approval_facts())
    expected = {
        "sub": "user_demo_005",
        "project_id": "prj_demo_001",
        "environment": "prod",
        "tool": "etl.execute",
        "resource_scope": {"tables": ["other"]},
    }
    assert_code("CAP-403", service.verify, issued["token"], expected)

    issued = service.issue(base_claims(), approval_facts=approval_facts())
    assert_code(
        "CAP-422",
        service.verify,
        issued["token"],
        {"artifact_digest": DIGEST_B},
    )


def test_capability_expiry_and_single_use_are_enforced():
    clock = FakeClock()
    service = CapabilityService(private_key=private_key(), clock=clock)
    issued = service.issue(base_claims(), approval_facts=approval_facts())
    clock.advance(300)
    assert_code("CAP-410", service.verify, issued["token"])

    clock = FakeClock()
    service = CapabilityService(private_key=private_key(), clock=clock)
    issued = service.issue(base_claims(), approval_facts=approval_facts())
    service.verify(issued["token"])
    assert_code("CAP-409", service.verify, issued["token"])
    service.consume(issued["jti"], issued["token_digest"])
    assert_code("CAP-409", service.verify, issued["token"])
    assert_code("CAP-409", service.consume, issued["jti"], issued["token_digest"])


def test_capability_requires_two_independent_approvers():
    service = CapabilityService(private_key=private_key(), clock=FakeClock())
    assert_code("CAP-422", service.issue, base_claims())

    self_approved = approval_facts()
    self_approved[0]["approver_id"] = "user_demo_001"
    assert_code("CAP-422", service.issue, base_claims(), approval_facts=self_approved)

    wrong_slots = approval_facts()
    wrong_slots[0]["role_slot"] = "auditor"
    wrong_slots[1]["role_slot"] = "data_checker"
    assert_code(
        "CAP-422",
        service.issue,
        base_claims(),
        approval_facts=wrong_slots,
        required_slots=("data_checker", "security_checker"),
    )


def test_capability_rejects_plaintext_secret_material():
    service = CapabilityService(private_key=private_key(), clock=FakeClock())
    claims = base_claims(resource_scope={"password": "do-not-store"})
    assert_code("CAP-422", service.issue, claims, approval_facts=approval_facts())


# Replay Guard


async def test_replay_reserve_is_single_use():
    clock = FakeClock()
    guard = ReplayGuard(clock=clock)
    reserved = await guard.reserve("jti:digest", "etl.execute:user:project:prod")
    assert reserved["state"] == "RESERVED"
    await assert_async_code("RG-409", guard.reserve, "jti:digest", "etl.execute:user:project:prod")
    assert (await guard.consume("jti:digest"))["state"] == "CONSUMED"
    await assert_async_code("RG-409", guard.reserve, "jti:digest", "etl.execute:user:project:prod")


async def test_replay_missing_scope_and_expiry():
    clock = FakeClock()
    guard = ReplayGuard(clock=clock)
    await assert_async_code("RG-422", guard.reserve, "", "scope")
    await guard.reserve("key", "scope", ttl_seconds=1)
    clock.advance(1)
    await assert_async_code("RG-410", guard.reserve, "key", "scope")


async def test_replay_scope_binding_and_fail_closed_unavailable():
    guard = ReplayGuard(clock=FakeClock())
    await guard.reserve("key", "scope-a")
    await assert_async_code("RG-409", guard.reserve, "key", "scope-b")
    unavailable = ReplayGuard(clock=FakeClock(), unavailable=True)
    await assert_async_code("RG-503", unavailable.reserve, "key", "scope")


# Outbox


def outbox_event(**overrides):
    event = {
        "event_id": "obx_1",
        "event_type": "execution.command",
        "aggregate_id": "run_1",
        "payload_digest": DIGEST_A,
        "idempotency_key": "commit:prep_1",
    }
    event.update(overrides)
    return event


async def test_outbox_happy_path_and_duplicate_guards():
    outbox = InMemoryOutbox(clock=FakeClock())
    created = await outbox.enqueue(outbox_event())
    assert created["status"] == "PENDING"
    await assert_async_code("OBX-409", outbox.enqueue, outbox_event())
    await assert_async_code(
        "OBX-409", outbox.enqueue, outbox_event(event_id="obx_2")
    )
    await assert_async_code(
        "OBX-422", outbox.enqueue, outbox_event(event_id="obx_3", payload_digest="bad")
    )
    await assert_async_code(
        "OBX-422", outbox.enqueue, outbox_event(event_id="obx_4", payload={"raw": "x"})
    )
    await assert_async_code(
        "OBX-422",
        outbox.enqueue,
        outbox_event(event_id="obx_5", idempotency_key="password=plaintext"),
    )

    lease = await outbox.begin_dispatch("obx_1")
    published = await outbox.mark_published("obx_1", lease["lease_id"])
    assert published["status"] == "PUBLISHED"
    consumed = await outbox.consume("obx_1")
    assert consumed["status"] == "CONSUMED"
    await assert_async_code("OBX-409", outbox.consume, "obx_1")


async def test_outbox_retry_and_dead_letter():
    outbox = InMemoryOutbox(clock=FakeClock(), max_attempts=2)
    await outbox.enqueue(outbox_event())
    lease = await outbox.begin_dispatch("obx_1")
    retrying = await outbox.mark_failed("obx_1", lease["lease_id"], reason="broker down")
    assert retrying["status"] == "RETRYING"
    assert retrying["attempts"] == 1

    lease = await outbox.begin_dispatch("obx_1")
    dead = await outbox.mark_failed("obx_1", lease["lease_id"], reason="broker down")
    assert dead["status"] == "DEAD_LETTER"
    assert dead["attempts"] == 2


async def test_outbox_expired_lease_is_rejected():
    clock = FakeClock()
    outbox = InMemoryOutbox(clock=clock)
    await outbox.enqueue(outbox_event())
    lease = await outbox.begin_dispatch("obx_1", lease_seconds=1)
    clock.advance(2)
    await assert_async_code(
        "OBX-410", outbox.mark_published, "obx_1", lease["lease_id"]
    )


async def test_outbox_expired_lease_can_be_taken_over():
    clock = FakeClock()
    outbox = InMemoryOutbox(clock=clock)
    await outbox.enqueue(outbox_event())
    old_lease = await outbox.begin_dispatch("obx_1", lease_seconds=1)
    clock.advance(2)

    new_lease = await outbox.begin_dispatch("obx_1", lease_seconds=5)
    assert new_lease["lease_id"] != old_lease["lease_id"]
    # The stale dispatcher can no longer publish the event.
    await assert_async_code(
        "OBX-409", outbox.mark_published, "obx_1", old_lease["lease_id"]
    )
    published = await outbox.mark_published("obx_1", new_lease["lease_id"])
    assert published["status"] == "PUBLISHED"


# Ledger


def ledger_event(project_id: str = "prj_demo_001", event_id: str = "evt_1", **overrides):
    event = {
        "event_id": event_id,
        "project_id": project_id,
        "actor_id": "user_demo_005",
        "event_type": "tool.call.executed",
        "resource_type": "execution_run",
        "resource_id": "run_1",
        "payload_digest": DIGEST_A,
        "occurred_at": NOW.isoformat(),
    }
    event.update(overrides)
    return event


async def test_ledger_hash_chain_and_project_isolation():
    ledger = EvidenceLedger(clock=FakeClock(), private_key=private_key())
    first = await ledger.append(ledger_event())
    second = await ledger.append(ledger_event(event_id="evt_2", payload_digest=DIGEST_B))
    other = await ledger.append(ledger_event(project_id="prj_2", event_id="evt_3"))

    assert first["prev_event_hash"] == "0" * 64
    assert second["prev_event_hash"] == first["event_hash"]
    assert other["prev_event_hash"] == "0" * 64
    assert ledger.verify("prj_demo_001")["status"] == "VERIFIED"
    assert ledger.verify("prj_demo_001")["entries"] == 2


async def test_ledger_detects_tampering_and_checkpoint_signature():
    ledger = EvidenceLedger(clock=FakeClock(), private_key=private_key())
    await ledger.append(ledger_event())
    await ledger.append(ledger_event(event_id="evt_2"))
    checkpoint = ledger.checkpoint("prj_demo_001")
    assert ledger.verify_checkpoint(checkpoint)["status"] == "VERIFIED"

    broken_checkpoint = dict(checkpoint)
    broken_checkpoint["last_event_hash"] = "f" * 64
    assert_code("EL-410", ledger.verify_checkpoint, broken_checkpoint)

    ledger._chains["prj_demo_001"][0]["payload_digest"] = DIGEST_B
    result = ledger.verify("prj_demo_001")
    assert result["status"] == "BROKEN"
    assert result["broken_at"] == 1


async def test_ledger_rejects_raw_payload_and_bad_digest():
    ledger = EvidenceLedger(clock=FakeClock(), private_key=private_key())
    await assert_async_code("EL-422", ledger.append, ledger_event(payload_digest="bad"))
    await assert_async_code("EL-422", ledger.append, ledger_event(payload={"raw": "x"}))


# Broker


def handler(output=None, *, raises=None, delay=0):
    async def run(intent):
        if delay:
            await asyncio.sleep(delay)
        if raises is not None:
            raise raises
        return output if output is not None else {"ok": True}

    return run


async def test_broker_drops_sensitive_external_ref():
    kernel = HarnessKernel(
        pdp=PolicyDecisionPoint(clock=FakeClock()),
        capability=CapabilityService(private_key=private_key(), clock=FakeClock()),
        replay=ReplayGuard(clock=FakeClock()),
        ledger=EvidenceLedger(clock=FakeClock(), private_key=private_key()),
    )
    kernel.broker.register_handler(
        "conn.test",
        handler(
            {
                "ok": True,
                "external_ref": "jdbc:postgresql://user:pass@db:5432/etl",
            }
        ),
    )
    intent = base_intent("conn.test")
    del intent["artifact_digest"]
    decision = kernel.pdp.decide(intent)
    result = await kernel.broker.execute(intent, policy_decision=decision)
    assert result["status"] == "SUCCEEDED"
    assert result["external_ref"] is None


async def test_broker_read_only_tool_and_unknown_tool():
    kernel = HarnessKernel(
        pdp=PolicyDecisionPoint(clock=FakeClock()),
        capability=CapabilityService(private_key=private_key(), clock=FakeClock()),
        replay=ReplayGuard(clock=FakeClock()),
        ledger=EvidenceLedger(clock=FakeClock(), private_key=private_key()),
    )
    kernel.broker.register_handler("conn.test", handler({"ok": True, "external_ref": "ext_1"}))
    intent = base_intent("conn.test")
    del intent["artifact_digest"]
    decision = kernel.pdp.decide(intent)
    result = await kernel.broker.execute(intent, policy_decision=decision)
    assert result["status"] == "SUCCEEDED"
    assert result["external_ref"] == "ext_1"
    assert len(result["output_digest"]) == 64

    await assert_async_code(
        "TB-400",
        kernel.broker.execute,
        base_intent("drop.table"),
        policy_decision=decision,
    )


async def test_broker_requires_adapter_policy_and_capability():
    kernel = HarnessKernel(
        pdp=PolicyDecisionPoint(clock=FakeClock()),
        capability=CapabilityService(private_key=private_key(), clock=FakeClock()),
        replay=ReplayGuard(clock=FakeClock()),
        ledger=EvidenceLedger(clock=FakeClock(), private_key=private_key()),
    )
    intent = base_intent()
    decision = kernel.pdp.decide(intent)
    await assert_async_code(
        "TB-503", kernel.broker.execute, intent, policy_decision=decision
    )

    kernel.broker.register_handler("etl.execute", handler())
    await assert_async_code(
        "TB-403", kernel.broker.execute, intent, policy_decision=decision
    )
    await assert_async_code(
        "TB-403",
        kernel.broker.execute,
        intent,
        policy_decision={**decision, "actor_id": "other"},
    )


async def test_broker_rejects_forged_or_mismatched_policy():
    kernel = HarnessKernel(
        pdp=PolicyDecisionPoint(clock=FakeClock()),
        capability=CapabilityService(private_key=private_key(), clock=FakeClock()),
        replay=ReplayGuard(clock=FakeClock()),
        ledger=EvidenceLedger(clock=FakeClock(), private_key=private_key()),
    )
    intent = base_intent("run.cancel")
    decision = kernel.pdp.decide(intent)
    kernel.broker.register_handler("run.cancel", handler({"ok": True}))

    await assert_async_code(
        "TB-403", kernel.broker.execute, intent, policy_decision=None
    )
    forged = dict(decision)
    forged.pop("decision_digest")
    await assert_async_code(
        "TB-403", kernel.broker.execute, intent, policy_decision=forged
    )
    unregistered = {**decision, "decision_digest": "f" * 64}
    await assert_async_code(
        "TB-403", kernel.broker.execute, intent, policy_decision=unregistered
    )
    other_scope = {**intent, "resource_scope": {"tables": ["other"]}}
    await assert_async_code(
        "TB-403",
        kernel.broker.execute,
        other_scope,
        policy_decision=decision,
        idempotency_key="cancel:1",
    )
    other_run = {**intent, "execution_run_id": "run_2"}
    await assert_async_code(
        "TB-403",
        kernel.broker.execute,
        other_run,
        policy_decision=decision,
        idempotency_key="cancel:2",
    )


async def test_broker_full_capability_path_consumes_once():
    kernel = HarnessKernel(
        pdp=PolicyDecisionPoint(clock=FakeClock()),
        capability=CapabilityService(private_key=private_key(), clock=FakeClock()),
        replay=ReplayGuard(clock=FakeClock()),
        ledger=EvidenceLedger(clock=FakeClock(), private_key=private_key()),
    )
    kernel.broker.register_handler("etl.execute", handler({"rows": 10}))
    intent = base_intent()
    decision = kernel.pdp.decide(intent)
    issued = kernel.capability.issue(base_claims(), approval_facts=approval_facts())

    result = await kernel.broker.execute(
        intent, policy_decision=decision, capability_token=issued["token"]
    )
    assert result["status"] == "SUCCEEDED"
    await assert_async_code(
        "CAP-409",
        kernel.broker.execute,
        intent,
        policy_decision=decision,
        capability_token=issued["token"],
    )


async def test_broker_ops_replay_and_failure_codes():
    kernel = HarnessKernel(
        pdp=PolicyDecisionPoint(clock=FakeClock()),
        capability=CapabilityService(private_key=private_key(), clock=FakeClock()),
        replay=ReplayGuard(clock=FakeClock()),
        ledger=EvidenceLedger(clock=FakeClock(), private_key=private_key()),
    )
    intent = base_intent("run.cancel")
    decision = kernel.pdp.decide(intent)
    kernel.broker.register_handler("run.cancel", handler({"ok": True}))
    first = await kernel.broker.execute(
        intent, policy_decision=decision, idempotency_key="cancel:1"
    )
    assert first["status"] == "SUCCEEDED"
    await assert_async_code(
        "RG-409",
        kernel.broker.execute,
        intent,
        policy_decision=decision,
        idempotency_key="cancel:1",
    )

    kernel.broker.register_handler(
        "conn.test", handler(raises=ToolDependencyError("downstream down"))
    )
    conn_intent = base_intent("conn.test")
    del conn_intent["artifact_digest"]
    conn_decision = kernel.pdp.decide(conn_intent)
    failed = await kernel.broker.execute(conn_intent, policy_decision=conn_decision)
    assert failed["status"] == "FAILED"
    assert failed["domain_code"] == "TB-424"

    kernel.broker.register_handler("conn.test", handler(delay=0.05))
    timed_out = await kernel.broker.execute(
        conn_intent, policy_decision=conn_decision, timeout_seconds=0.001
    )
    assert timed_out["status"] == "UNKNOWN"
    assert timed_out["domain_code"] == "TB-504"


async def test_memory_adapter_wraps_kernel_ports():
    kernel = HarnessKernel(
        pdp=PolicyDecisionPoint(clock=FakeClock()),
        capability=CapabilityService(private_key=private_key(), clock=FakeClock()),
        replay=ReplayGuard(clock=FakeClock()),
        ledger=EvidenceLedger(clock=FakeClock(), private_key=private_key()),
    )
    adapter = InMemoryHarnessAdapter(kernel)

    intent = base_intent("run.cancel")
    decision = await adapter.pdp_decide(intent)
    assert decision["decision"] == "ALLOW"

    await adapter.replay_guard_check("cancel:adapter", "cancel:adapter")
    await assert_async_code(
        "RG-409", adapter.replay_guard_check, "cancel:adapter", "cancel:adapter"
    )

    event_id = await adapter.write_outbox(outbox_event())
    assert event_id == "obx_1"
    entry_id = await adapter.append_ledger(
        ledger_event(event_id="adapter_evt")
    )
    assert entry_id == "adapter_evt"

    claims = {**base_claims(), "approval_facts": approval_facts()}
    issued = await adapter.issue_capability(claims)
    verified = await adapter.verify_capability(
        issued["token"],
        {
            "sub": claims["sub"],
            "project_id": claims["project_id"],
            "environment": claims["environment"],
            "tool": claims["tool"],
            "resource_scope": claims["resource_scope"],
            "artifact_digest": claims["artifact_digest"],
            "preparation_id": claims["preparation_id"],
            "execution_run_id": claims["execution_run_id"],
        },
    )
    assert verified["status"] == "PRESENTED"


async def test_kernel_rejects_non_object_intent():
    kernel = HarnessKernel(
        pdp=PolicyDecisionPoint(clock=FakeClock()),
        capability=CapabilityService(private_key=private_key(), clock=FakeClock()),
        replay=ReplayGuard(clock=FakeClock()),
        ledger=EvidenceLedger(clock=FakeClock(), private_key=private_key()),
    )
    await assert_async_code("PDP-400", kernel.decide, [])
    await assert_async_code(
        "TB-400", kernel.execute_tool, [], policy_decision=None
    )
    await assert_async_code(
        "CAP-422",
        kernel.issue_capability,
        base_claims(tool="unknown.tool"),
        approval_facts=approval_facts(),
    )


async def test_kernel_end_to_end_ledger_and_outbox():
    kernel = HarnessKernel(
        pdp=PolicyDecisionPoint(clock=FakeClock()),
        capability=CapabilityService(private_key=private_key(), clock=FakeClock()),
        replay=ReplayGuard(clock=FakeClock()),
        ledger=EvidenceLedger(clock=FakeClock(), private_key=private_key()),
    )
    kernel.broker.register_handler("etl.execute", handler({"rows": 1}))
    intent = base_intent()
    decision = await kernel.decide(intent)
    issued = await kernel.issue_capability(base_claims(), approval_facts=approval_facts())
    result = await kernel.execute_tool(
        intent,
        policy_decision=decision,
        capability_token=issued["token"],
    )
    assert result["status"] == "SUCCEEDED"
    assert result["audit_event_id"]

    event = await kernel.enqueue_outbox(
        outbox_event(), project_id="prj_demo_001"
    )
    assert event["status"] == "PENDING"
    assert kernel.ledger.verify("prj_demo_001")["status"] == "VERIFIED"
    event_types = [
        entry["event_type"]
        for entry in kernel.ledger.entries("prj_demo_001")
    ]
    assert event_types == [
        "pdp.decision.recorded",
        "capability.issued",
        "tool.call.executed",
        "outbox.event.created",
    ]


def test_kernel_health_and_ledger_hash_formula():
    kernel = HarnessKernel(
        pdp=PolicyDecisionPoint(clock=FakeClock()),
        capability=CapabilityService(private_key=private_key(), clock=FakeClock()),
        replay=ReplayGuard(clock=FakeClock()),
        ledger=EvidenceLedger(clock=FakeClock(), private_key=private_key()),
    )
    assert kernel.health()["status"] == "ok"


async def test_ledger_hash_matches_spec_formula():
    ledger = EvidenceLedger(clock=FakeClock(), private_key=private_key())
    entry = await ledger.append(ledger_event())
    expected = digest_of(
        {
            "prev_event_hash": "0" * 64,
            "project_id": "prj_demo_001",
            "actor_id": "user_demo_005",
            "event_type": "tool.call.executed",
            "resource_type": "execution_run",
            "resource_id": "run_1",
            "payload_digest": DIGEST_A,
            "occurred_at": NOW.isoformat(),
        }
    )
    assert entry["event_hash"] == expected
