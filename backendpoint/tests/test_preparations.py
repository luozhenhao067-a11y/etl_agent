from __future__ import annotations

from app.container import Container
from tests.support import PROJECT_ID, assert_envelope, assert_error, headers

PREPARE_BODY = {
    "schedule": {"mode": "manual"},
    "budget": {"max_input_rows": 100000, "max_duration_seconds": 600},
    "quality_contract_ref": "qc_demo_001",
}


async def test_api_12_returns_503_without_fake_preparation(client, container: Container):
    before = set(container.state.preparations)
    response = await client.post(
        "/api/v1/versions/ver_demo_001/prepare",
        json=PREPARE_BODY,
        headers=headers(key="idem_prepare_001"),
    )
    body = assert_error(response, 503, "API-503")
    assert body["details"] == {"dependency": "harness", "status": "not_implemented"}
    assert "preparation_id" not in response.json()
    assert "approval_slots" not in response.json()
    assert set(container.state.preparations) == before


async def test_api_12_requires_immutable_version_and_passing_gate(client):
    draft = await client.post(
        "/api/v1/versions/ver_demo_002/prepare",
        json=PREPARE_BODY,
        headers=headers(key="idem_prepare_002"),
    )
    assert_error(draft, 409, "PREP-409")


async def test_api_12_rejects_failed_gate(client, container: Container):
    container.state.designs["ver_demo_001"]["gate_result"]["masking"] = "failed"
    response = await client.post(
        "/api/v1/versions/ver_demo_001/prepare",
        json=PREPARE_BODY,
        headers=headers(key="idem_prepare_003"),
    )
    body = assert_error(response, 422, "PREP-422")
    assert body["details"]["reason"] == "gate_not_passed"


async def test_api_12_validation_and_permissions(client):
    empty_schedule = await client.post(
        "/api/v1/versions/ver_demo_001/prepare",
        json={**PREPARE_BODY, "schedule": {}},
        headers=headers(key="idem_prepare_004"),
    )
    assert_error(empty_schedule, 422, "PREP-422")

    negative_budget = await client.post(
        "/api/v1/versions/ver_demo_001/prepare",
        json={**PREPARE_BODY, "budget": {"max_input_rows": -1}},
        headers=headers(key="idem_prepare_005"),
    )
    assert_error(negative_budget, 422, "PREP-422")

    checker = await client.post(
        "/api/v1/versions/ver_demo_001/prepare",
        json=PREPARE_BODY,
        headers=headers("user_demo_002", key="idem_prepare_006"),
    )
    assert_error(checker, 403, "ROLE-403")

    non_member = await client.post(
        "/api/v1/versions/ver_demo_001/prepare",
        json=PREPARE_BODY,
        headers=headers("user_demo_007", key="idem_prepare_007"),
    )
    assert_error(non_member, 403, "AUTH-403")


async def test_api_13_records_decision_and_audit(client, container: Container):
    response = await client.post(
        "/api/v1/approval-requests/apr_demo_001/decisions",
        json={
            "decision": "approve",
            "opinion": "字段映射与脱敏规则已核对",
            "idempotency_key": "idem_decision_001",
        },
        headers=headers("user_demo_002", key="idem_decision_001"),
    )
    data = assert_envelope(response)
    assert data["approval_id"] == "apr_demo_001"
    assert data["status"] == "APPROVED"
    assert data["next_slot_status"] == "PENDING"

    approval = container.repository.get_approval("apr_demo_001")
    assert approval["status"] == "APPROVED"
    assert approval["approver_id"] == "user_demo_002"
    assert container.state.preparations["prep_demo_001"]["status"] == "PARTIAL_APPROVED"

    events = container.repository.list_audit_events(PROJECT_ID)
    assert [event["event_type"] for event in events] == ["approval.decision.recorded"]
    assert "opinion" not in events[0]
    assert len(events[0]["payload_digest"]) == 64


async def test_api_13_same_key_same_payload_replays_first_result(
    client, container: Container
):
    body = {
        "decision": "approve",
        "opinion": "同意",
        "idempotency_key": "idem_decision_replay",
    }
    request_headers = headers("user_demo_002", key="idem_decision_replay")
    first = assert_envelope(
        await client.post(
            "/api/v1/approval-requests/apr_demo_001/decisions",
            json=body,
            headers=request_headers,
        )
    )
    second = assert_envelope(
        await client.post(
            "/api/v1/approval-requests/apr_demo_001/decisions",
            json=body,
            headers=request_headers,
        )
    )
    assert second == first
    events = container.repository.list_audit_events(PROJECT_ID)
    assert [event["event_type"] for event in events] == ["approval.decision.recorded"]
    assert container.repository.get_approval("apr_demo_001")["status"] == "APPROVED"


async def test_api_13_completes_when_both_slots_approved(client, container: Container):
    first = assert_envelope(
        await client.post(
            "/api/v1/approval-requests/apr_demo_001/decisions",
            json={
                "decision": "approve",
                "opinion": "同意",
                "idempotency_key": "idem_decision_010",
            },
            headers=headers("user_demo_002", key="idem_decision_010"),
        )
    )
    assert first["status"] == "APPROVED"
    assert container.state.preparations["prep_demo_001"]["status"] == "PARTIAL_APPROVED"

    second = assert_envelope(
        await client.post(
            "/api/v1/approval-requests/apr_demo_002/decisions",
            json={"decision": "approve", "idempotency_key": "idem_decision_011"},
            headers=headers("user_demo_003", key="idem_decision_011"),
        )
    )
    assert second["status"] == "APPROVED"
    assert container.state.preparations["prep_demo_001"]["status"] == "APPROVED"

    events = container.repository.list_audit_events(PROJECT_ID)
    assert [event["event_type"] for event in events] == [
        "approval.decision.recorded",
        "approval.decision.recorded",
        "approval.completed",
    ]
    assert events[2]["resource_type"] == "preparation"
    assert events[2]["resource_id"] == "prep_demo_001"
    assert len(events[2]["payload_digest"]) == 64
    assert events[2]["prev_event_hash"] == events[1]["event_hash"]


async def test_api_13_blocks_self_approval(client, container: Container):
    response = await client.post(
        "/api/v1/approval-requests/apr_demo_001/decisions",
        json={
            "decision": "approve",
            "idempotency_key": "idem_decision_002",
        },
        headers=headers("user_demo_001", key="idem_decision_002"),
    )
    body = assert_error(response, 403, "APR-403")
    assert body["details"]["reason"] == "SELF_APPROVAL_FORBIDDEN"
    assert container.repository.get_approval("apr_demo_001")["status"] == "PENDING"

    events = container.repository.list_audit_events(PROJECT_ID)
    assert [event["event_type"] for event in events] == [
        "approval.self_approval_blocked"
    ]


async def test_api_13_blocks_actor_holding_another_slot(client):
    response = await client.post(
        "/api/v1/approval-requests/apr_demo_006/decisions",
        json={
            "decision": "approve",
            "idempotency_key": "idem_decision_003",
        },
        headers=headers("user_demo_002", key="idem_decision_003"),
    )
    body = assert_error(response, 409, "APR-409")
    assert body["details"]["reason"] == "ROLE_SLOT_CONFLICT"


async def test_api_13_enforces_slot_role_and_grant(client):
    wrong_slot = await client.post(
        "/api/v1/approval-requests/apr_demo_002/decisions",
        json={"decision": "approve", "idempotency_key": "idem_decision_004"},
        headers=headers("user_demo_002", key="idem_decision_004"),
    )
    body = assert_error(wrong_slot, 403, "APR-403")
    assert body["details"]["reason"] == "ROLE_GRANT_MISSING"


async def test_api_13_decision_is_immutable(client):
    response = await client.post(
        "/api/v1/approval-requests/apr_demo_003/decisions",
        json={"decision": "approve", "idempotency_key": "idem_decision_005"},
        headers=headers("user_demo_002", key="idem_decision_005"),
    )
    body = assert_error(response, 409, "APR-409")
    assert body["details"]["reason"] == "DECISION_IMMUTABLE"


async def test_api_13_validates_key_and_decision(client):
    mismatch = await client.post(
        "/api/v1/approval-requests/apr_demo_001/decisions",
        json={"decision": "approve", "idempotency_key": "body_key"},
        headers=headers("user_demo_002", key="header_key"),
    )
    assert_error(mismatch, 422, "APR-422")

    invalid_decision = await client.post(
        "/api/v1/approval-requests/apr_demo_001/decisions",
        json={"decision": "abstain", "idempotency_key": "idem_decision_006"},
        headers=headers("user_demo_002", key="idem_decision_006"),
    )
    assert_error(invalid_decision, 422, "APR-422")

    non_member = await client.post(
        "/api/v1/approval-requests/apr_demo_001/decisions",
        json={"decision": "approve", "idempotency_key": "idem_decision_007"},
        headers=headers("user_demo_007", key="idem_decision_007"),
    )
    assert_error(non_member, 403, "AUTH-403")


async def test_api_14_returns_503_without_execution_run_or_capability(client, container: Container):
    # Backend-neutral side-effect probe: no execution run may be created on
    # the fail-closed path (works for both the memory and SQL repositories).
    before_runs = len(container.repository.list_execution_runs())
    response = await client.post(
        "/api/v1/preparations/prep_demo_005/commit",
        json={"idempotency_key": "idem_commit_001"},
        headers=headers("user_demo_004", key="idem_commit_001"),
    )
    body = assert_error(response, 503, "CMT-503")
    assert body["details"] == {"dependency": "harness", "status": "not_implemented"}
    assert "execution_run_id" not in response.json()
    assert "capability_digest" not in response.json()
    assert len(container.repository.list_execution_runs()) == before_runs
    assert "commit" not in container.state.preparations["prep_demo_005"]


async def test_api_14_rejects_already_committed(client):
    response = await client.post(
        "/api/v1/preparations/prep_demo_002/commit",
        json={"idempotency_key": "idem_commit_002"},
        headers=headers("user_demo_004", key="idem_commit_002"),
    )
    body = assert_error(response, 409, "CMT-409")
    assert body["details"]["reason"] == "ALREADY_COMMITTED"


async def test_api_14_rejects_incomplete_approval(client):
    response = await client.post(
        "/api/v1/preparations/prep_demo_001/commit",
        json={"idempotency_key": "idem_commit_003"},
        headers=headers("user_demo_004", key="idem_commit_003"),
    )
    body = assert_error(response, 409, "CMT-409")
    assert body["details"]["reason"] == "APPROVAL_INCOMPLETE"
    assert set(body["details"]["missing_slots"]) == {"data_checker", "security_checker"}


async def test_api_14_enforces_duty_separation(client, container: Container):
    # Same approver in two slots is not 2/2 independent approval.
    container.repository.update_approval(
        "apr_demo_009", {"approver_id": "user_demo_002"}
    )
    container.repository.update_approval(
        "apr_demo_010", {"approver_id": "user_demo_002"}
    )
    response = await client.post(
        "/api/v1/preparations/prep_demo_005/commit",
        json={"idempotency_key": "idem_commit_004"},
        headers=headers("user_demo_004", key="idem_commit_004"),
    )
    body = assert_error(response, 409, "CMT-409")
    assert body["details"]["reason"] == "APPROVAL_INCOMPLETE"


async def test_api_14_permissions_and_key_match(client):
    maker = await client.post(
        "/api/v1/preparations/prep_demo_005/commit",
        json={"idempotency_key": "idem_commit_005"},
        headers=headers("user_demo_001", key="idem_commit_005"),
    )
    assert_error(maker, 403, "CMT-403")

    non_member = await client.post(
        "/api/v1/preparations/prep_demo_005/commit",
        json={"idempotency_key": "idem_commit_006"},
        headers=headers("user_demo_007", key="idem_commit_006"),
    )
    assert_error(non_member, 403, "AUTH-403")

    mismatch = await client.post(
        "/api/v1/preparations/prep_demo_005/commit",
        json={"idempotency_key": "body_key"},
        headers=headers("user_demo_004", key="header_key"),
    )
    assert_error(mismatch, 422, "API-422")
