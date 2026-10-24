from __future__ import annotations

from app.container import Container
from tests.support import PROJECT_ID, assert_envelope, assert_error, headers


async def _start_generation(client, thread_id: str, key: str, prompt: str = "同步订单"):
    return await client.post(
        "/api/v1/versions/ver_demo_002/generation",
        json={
            "prompt": prompt,
            "source_profile_ref": "profile_demo_src_001",
            "target_profile_ref": "profile_demo_dst_001",
            "provider": "deepseek",
            "thread_id": thread_id,
        },
        headers=headers(key=key),
    )


async def test_api_08_creates_pipeline_with_ledger_event(client, container: Container):
    response = await client.post(
        "/api/v1/pipelines",
        json={
            "project_id": PROJECT_ID,
            "name": "新建订单同步",
            "code": "orders_sync_new",
            "description": "MySQL 到 Doris",
        },
        headers=headers(key="idem_pipeline_001"),
    )
    data = assert_envelope(response, 201)
    assert data["pipeline_id"].startswith("pipe_")
    assert data["status"] == "draft"
    assert container.repository.get_pipeline(data["pipeline_id"])["code"] == "orders_sync_new"

    # pipeline.created is in Spec 12.2 (Spec 9.2/12.2) and enters the staging chain.
    events = container.repository.list_audit_events(PROJECT_ID)
    assert [event["event_type"] for event in events] == ["pipeline.created"]


async def test_api_08_is_idempotent(client):
    body = {
        "project_id": PROJECT_ID,
        "name": "幂等 Pipeline",
        "code": "idem_pipeline_replay",
    }
    first = assert_envelope(
        await client.post(
            "/api/v1/pipelines", json=body, headers=headers(key="idem_pipeline_replay")
        ),
        201,
    )
    second = assert_envelope(
        await client.post(
            "/api/v1/pipelines", json=body, headers=headers(key="idem_pipeline_replay")
        ),
        201,
    )
    assert second == first


async def test_api_08_conflicts_validation_and_permissions(client):
    duplicate = await client.post(
        "/api/v1/pipelines",
        json={"project_id": PROJECT_ID, "name": "重复", "code": "orders_sync"},
        headers=headers(key="idem_pipeline_002"),
    )
    assert_error(duplicate, 409, "API-409")

    secret_description = await client.post(
        "/api/v1/pipelines",
        json={
            "project_id": PROJECT_ID,
            "name": "含密钥",
            "code": "secret_description",
            "description": "password=abc123",
        },
        headers=headers(key="idem_pipeline_003"),
    )
    assert_error(secret_description, 422, "API-422")

    checker = await client.post(
        "/api/v1/pipelines",
        json={"project_id": PROJECT_ID, "name": "无权限", "code": "checker_pipeline"},
        headers=headers("user_demo_002", key="idem_pipeline_004"),
    )
    assert_error(checker, 403, "ROLE-403")

    other_project = await client.post(
        "/api/v1/pipelines",
        json={"project_id": "prj_demo_999", "name": "跨项目", "code": "cross_project"},
        headers=headers(key="idem_pipeline_005"),
    )
    assert_error(other_project, 403, "AUTH-403")


async def test_api_09_generation_interrupts_for_clarification(client, container: Container):
    response = await _start_generation(client, "thread_demo_answer_001", "idem_gen_001")
    data = assert_envelope(response, 201)
    assert data["status"] == "interrupted"
    assert data["thread_id"] == "thread_demo_answer_001"
    assert data["agent_run_id"].startswith("agent_")
    assert data["interrupt"]["question"]
    assert data["interrupt"]["fields"] == [{"name": "create_target", "type": "boolean"}]
    assert data["design_digest"] is None

    run = container.repository.get_agent_run(data["agent_run_id"])
    assert run["status"] == "interrupted"
    assert run["prompt"] is None
    # prompt_digest is run-scoped runtime state, not a Spec 10.1 column.
    assert len(container.state.agent_states[data["agent_run_id"]]["prompt_digest"]) == 64

    event_types = [
        event["event_type"]
        for event in container.repository.list_audit_events(PROJECT_ID)
    ]
    assert event_types == ["agent.run.started", "agent.run.interrupted"]


async def test_api_09_rejects_immutable_version(client):
    response = await client.post(
        "/api/v1/versions/ver_demo_001/generation",
        json={
            "prompt": "同步订单",
            "source_profile_ref": "profile_src",
            "target_profile_ref": "profile_dst",
        },
        headers=headers(key="idem_gen_002"),
    )
    assert_error(response, 409, "GEN-409")


async def test_api_09_rejects_concurrent_thread(client):
    first = await _start_generation(client, "thread_concurrent", "idem_gen_003")
    assert_envelope(first, 201)
    second = await _start_generation(client, "thread_concurrent", "idem_gen_004")
    assert_error(second, 409, "GEN-409")


async def test_api_09_rejects_secret_prompt(client):
    response = await client.post(
        "/api/v1/versions/ver_demo_002/generation",
        json={
            "prompt": "连接串 password=topsecret",
            "source_profile_ref": "profile_src",
            "target_profile_ref": "profile_dst",
        },
        headers=headers(key="idem_gen_005"),
    )
    assert_error(response, 422, "GEN-422")


async def test_api_09_permissions_and_validation(client):
    checker = await client.post(
        "/api/v1/versions/ver_demo_002/generation",
        json={
            "prompt": "同步订单",
            "source_profile_ref": "profile_src",
            "target_profile_ref": "profile_dst",
        },
        headers=headers("user_demo_002", key="idem_gen_006"),
    )
    assert_error(checker, 403, "ROLE-403")

    non_member = await client.post(
        "/api/v1/versions/ver_demo_002/generation",
        json={
            "prompt": "同步订单",
            "source_profile_ref": "profile_src",
            "target_profile_ref": "profile_dst",
        },
        headers=headers("user_demo_007", key="idem_gen_007"),
    )
    assert_error(non_member, 403, "AUTH-403")

    missing_prompt = await client.post(
        "/api/v1/versions/ver_demo_002/generation",
        json={"source_profile_ref": "profile_src", "target_profile_ref": "profile_dst"},
        headers=headers(key="idem_gen_008"),
    )
    assert_error(missing_prompt, 422, "GEN-422")


async def test_api_10_completes_state_machine_and_exposes_design(client, container: Container):
    started = assert_envelope(
        await _start_generation(client, "thread_answer_001", "idem_gen_009"),
        201,
    )
    response = await client.post(
        f"/api/v1/agent-runs/{started['agent_run_id']}/answers",
        json={"answers": {"create_target": True}, "thread_id": "thread_answer_001"},
        headers=headers(),
    )
    data = assert_envelope(response)
    assert data["status"] == "completed"
    assert data["design_ready"] is True
    assert data["next_question"] is None
    assert data["checkpoint_ref"].startswith("ckpt_")

    run = container.repository.get_agent_run(started["agent_run_id"])
    assert run["status"] == "completed"
    assert run["step_count"] == 2

    design = assert_envelope(
        await client.get("/api/v1/versions/ver_demo_002/design", headers=headers())
    )
    assert set(design["gate_result"].values()) == {"not_run"}
    assert "topsecret" not in str(design)

    resumed = [
        event
        for event in container.repository.list_audit_events(PROJECT_ID)
        if event["event_type"] == "agent.run.resumed"
    ]
    assert len(resumed) == 1


async def test_api_10_validates_thread_and_answers(client):
    started = assert_envelope(
        await _start_generation(client, "thread_answer_002", "idem_gen_010"),
        201,
    )
    run_id = started["agent_run_id"]

    wrong_thread = await client.post(
        f"/api/v1/agent-runs/{run_id}/answers",
        json={"answers": {"create_target": True}, "thread_id": "thread_wrong"},
        headers=headers(),
    )
    assert_error(wrong_thread, 422, "GEN-422")

    missing_answer = await client.post(
        f"/api/v1/agent-runs/{run_id}/answers",
        json={"answers": {"other": True}, "thread_id": "thread_answer_002"},
        headers=headers(),
    )
    assert_error(missing_answer, 422, "GEN-422")

    wrong_type = await client.post(
        f"/api/v1/agent-runs/{run_id}/answers",
        json={"answers": {"create_target": "yes"}, "thread_id": "thread_answer_002"},
        headers=headers(),
    )
    assert_error(wrong_type, 422, "GEN-422")


async def test_api_10_restricts_to_run_initiator(client):
    started = assert_envelope(
        await _start_generation(client, "thread_answer_003", "idem_gen_011"),
        201,
    )
    run_id = started["agent_run_id"]

    other_maker = await client.post(
        f"/api/v1/agent-runs/{run_id}/answers",
        json={"answers": {"create_target": True}, "thread_id": "thread_answer_003"},
        headers=headers("user_demo_006"),
    )
    assert_error(other_maker, 403, "ROLE-403")

    checker = await client.post(
        f"/api/v1/agent-runs/{run_id}/answers",
        json={"answers": {"create_target": True}, "thread_id": "thread_answer_003"},
        headers=headers("user_demo_002"),
    )
    assert_error(checker, 403, "ROLE-403")


async def test_api_10_rejects_repeat_answer(client):
    started = assert_envelope(
        await _start_generation(client, "thread_answer_004", "idem_gen_012"),
        201,
    )
    run_id = started["agent_run_id"]
    body = {"answers": {"create_target": True}, "thread_id": "thread_answer_004"}
    first = await client.post(
        f"/api/v1/agent-runs/{run_id}/answers", json=body, headers=headers()
    )
    assert_envelope(first)
    second = await client.post(
        f"/api/v1/agent-runs/{run_id}/answers", json=body, headers=headers()
    )
    assert_error(second, 409, "GEN-409")


async def test_api_10_unknown_run_returns_404(client):
    response = await client.post(
        "/api/v1/agent-runs/agent_missing/answers",
        json={"answers": {"create_target": True}, "thread_id": "thread_missing"},
        headers=headers(),
    )
    assert_error(response, 404, "API-404")


async def test_api_11_returns_masked_design(client):
    response = await client.get("/api/v1/versions/ver_demo_001/design", headers=headers())
    data = assert_envelope(response)
    assert data["gate_result"] == {
        "syntax": "passed",
        "schema": "passed",
        "masking": "passed",
        "budget": "passed",
    }
    assert "10.20.*.*" in data["hocon_text"]
    assert "mask_phone" in str(data["etl_plan_json"])


async def test_api_11_design_not_ready_and_permissions(client):
    not_ready = await client.get(
        "/api/v1/versions/ver_demo_002/design", headers=headers()
    )
    assert_error(not_ready, 409, "API-409")

    missing = await client.get(
        "/api/v1/versions/ver_missing/design", headers=headers()
    )
    assert_error(missing, 404, "API-404")

    non_member = await client.get(
        "/api/v1/versions/ver_demo_001/design", headers=headers("user_demo_007")
    )
    assert_error(non_member, 403, "AUTH-403")
