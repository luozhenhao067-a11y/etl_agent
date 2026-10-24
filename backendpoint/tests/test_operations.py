from __future__ import annotations

from copy import deepcopy

from app.container import Container
from tests.support import assert_envelope, assert_error, headers


async def test_api_15_returns_run_detail_with_masked_logs(client, container: Container):
    container.state.run_extras["run_demo_001"]["recent_logs"].append(
        "phone=13812345678 email=alice@example.com ip=10.20.30.40 password=abc123"
    )
    response = await client.get("/api/v1/execution-runs/run_demo_001", headers=headers())
    data = assert_envelope(response)
    assert set(data) == {
        "status",
        "engine_job_id",
        "metrics",
        "quality_report",
        "supervision",
        "started_at",
        "finished_at",
        "recent_logs",
    }
    assert data["status"] == "running"
    assert data["engine_job_id"] == "job_demo_001"
    assert data["metrics"]["input_records"] == 823410
    assert data["metrics"]["duration_seconds"] == 120
    assert data["quality_report"]["samples_masked"] is True
    assert data["supervision"]["status"] == "within_budget"

    serialized = str(response.json())
    assert "13812345678" not in serialized
    assert "alice@example.com" not in serialized
    assert "10.20.30.40" not in serialized
    assert "abc123" not in serialized
    assert "password=***" in serialized
    assert "capability_token_digest" not in serialized
    assert "a" * 64 not in serialized


async def test_api_15_missing_and_cross_project(client):
    missing = await client.get(
        "/api/v1/execution-runs/run_missing", headers=headers()
    )
    assert_error(missing, 404, "API-404")

    non_member = await client.get(
        "/api/v1/execution-runs/run_demo_001", headers=headers("user_demo_007")
    )
    assert_error(non_member, 403, "AUTH-403")


async def test_api_16_returns_503_without_mutating_run(client, container: Container):
    before = deepcopy(container.repository.get_execution_run("run_demo_001"))
    response = await client.post(
        "/api/v1/execution-runs/run_demo_001/cancel",
        json={"reason": "停止演示任务", "idempotency_key": "idem_cancel_001"},
        headers=headers("user_demo_004", key="idem_cancel_001"),
    )
    body = assert_error(response, 503, "OPS-503")
    assert body["details"] == {"dependency": "harness", "status": "not_implemented"}
    assert "cancelled_at" not in response.json()
    assert "external_ref" not in response.json()
    assert container.repository.get_execution_run("run_demo_001") == before

    # Dependency failures are retryable and must not be replayed as success.
    retry = await client.post(
        "/api/v1/execution-runs/run_demo_001/cancel",
        json={"reason": "停止演示任务", "idempotency_key": "idem_cancel_001"},
        headers=headers("user_demo_004", key="idem_cancel_001"),
    )
    assert_error(retry, 503, "OPS-503")


async def test_api_16_rejects_terminal_and_invalid_requests(client):
    terminal = await client.post(
        "/api/v1/execution-runs/run_demo_002/cancel",
        json={"reason": "已结束", "idempotency_key": "idem_cancel_002"},
        headers=headers("user_demo_004", key="idem_cancel_002"),
    )
    assert_error(terminal, 409, "OPS-409")

    blank_reason = await client.post(
        "/api/v1/execution-runs/run_demo_001/cancel",
        json={"reason": "", "idempotency_key": "idem_cancel_003"},
        headers=headers("user_demo_004", key="idem_cancel_003"),
    )
    assert_error(blank_reason, 400, "API-400")

    mismatch = await client.post(
        "/api/v1/execution-runs/run_demo_001/cancel",
        json={"reason": "停止", "idempotency_key": "body_key"},
        headers=headers("user_demo_004", key="header_key"),
    )
    assert_error(mismatch, 422, "OPS-422")


async def test_api_16_permissions_and_missing_run(client):
    maker = await client.post(
        "/api/v1/execution-runs/run_demo_001/cancel",
        json={"reason": "停止", "idempotency_key": "idem_cancel_004"},
        headers=headers("user_demo_001", key="idem_cancel_004"),
    )
    assert_error(maker, 403, "OPS-403")

    non_member = await client.post(
        "/api/v1/execution-runs/run_demo_001/cancel",
        json={"reason": "停止", "idempotency_key": "idem_cancel_005"},
        headers=headers("user_demo_007", key="idem_cancel_005"),
    )
    assert_error(non_member, 403, "AUTH-403")

    missing = await client.post(
        "/api/v1/execution-runs/run_missing/cancel",
        json={"reason": "停止", "idempotency_key": "idem_cancel_006"},
        headers=headers("user_demo_004", key="idem_cancel_006"),
    )
    assert_error(missing, 404, "API-404")


async def test_api_17_returns_503_without_mutating_shadow(client, container: Container):
    before = deepcopy(container.repository.get_execution_run("run_demo_003"))
    response = await client.post(
        "/api/v1/execution-runs/run_demo_003/rollback",
        json={
            "reason": "影子表回滚",
            "confirmation": "ROLLBACK",
            "idempotency_key": "idem_rollback_001",
        },
        headers=headers("user_demo_004", key="idem_rollback_001"),
    )
    body = assert_error(response, 503, "OPS-503")
    assert body["details"] == {"dependency": "harness", "status": "not_implemented"}
    assert "rollback_status" not in response.json()
    assert "ledger_event_id" not in response.json()
    assert container.repository.get_execution_run("run_demo_003") == before


async def test_api_17_rejects_runs_that_cannot_rollback(client):
    for run_id, key in (("run_demo_001", "idem_rollback_002"), ("run_demo_002", "idem_rollback_003")):
        response = await client.post(
            f"/api/v1/execution-runs/{run_id}/rollback",
            json={
                "reason": "回滚",
                "confirmation": "ROLLBACK",
                "idempotency_key": key,
            },
            headers=headers("user_demo_004", key=key),
        )
        assert_error(response, 409, "OPS-409")


async def test_api_17_validates_confirmation_and_key(client):
    invalid_confirmation = await client.post(
        "/api/v1/execution-runs/run_demo_003/rollback",
        json={
            "reason": "回滚",
            "confirmation": "rollback",
            "idempotency_key": "idem_rollback_004",
        },
        headers=headers("user_demo_004", key="idem_rollback_004"),
    )
    assert_error(invalid_confirmation, 422, "OPS-422")

    mismatch = await client.post(
        "/api/v1/execution-runs/run_demo_003/rollback",
        json={
            "reason": "回滚",
            "confirmation": "ROLLBACK",
            "idempotency_key": "body_key",
        },
        headers=headers("user_demo_004", key="header_key"),
    )
    assert_error(mismatch, 422, "OPS-422")


async def test_api_17_permissions_and_missing_run(client):
    maker = await client.post(
        "/api/v1/execution-runs/run_demo_003/rollback",
        json={
            "reason": "回滚",
            "confirmation": "ROLLBACK",
            "idempotency_key": "idem_rollback_005",
        },
        headers=headers("user_demo_001", key="idem_rollback_005"),
    )
    assert_error(maker, 403, "OPS-403")

    non_member = await client.post(
        "/api/v1/execution-runs/run_demo_003/rollback",
        json={
            "reason": "回滚",
            "confirmation": "ROLLBACK",
            "idempotency_key": "idem_rollback_006",
        },
        headers=headers("user_demo_007", key="idem_rollback_006"),
    )
    assert_error(non_member, 403, "AUTH-403")

    missing = await client.post(
        "/api/v1/execution-runs/run_missing/rollback",
        json={
            "reason": "回滚",
            "confirmation": "ROLLBACK",
            "idempotency_key": "idem_rollback_007",
        },
        headers=headers("user_demo_004", key="idem_rollback_007"),
    )
    assert_error(missing, 404, "API-404")


async def test_api_18_returns_503_without_fake_benchmark(client, container: Container):
    before = set(container.state.benchmark_runs)
    response = await client.post(
        "/api/v1/benchmarks/run",
        json={
            "suite_id": "suite_demo_001",
            "layer": "L0",
            "dataset_version": "ds_demo_v1",
            "idempotency_key": "idem_bench_001",
        },
        headers=headers("user_demo_003", key="idem_bench_001"),
    )
    body = assert_error(response, 503, "BENCH-503")
    assert body["details"] == {"dependency": "harness", "status": "not_implemented"}
    assert "benchmark_run_id" not in response.json()
    assert "started_at" not in response.json()
    assert set(container.state.benchmark_runs) == before


async def test_api_18_idempotency_scope_follows_contract(client):
    # Contract §8: the idempotency scope is the benchmark target
    # (suite_id + layer + dataset_version), not the actor. The same key on
    # the same target replays the first result; the same key on a different
    # target is a fresh request — not a payload-mismatch 409.
    key = "idem_bench_scope"
    request_headers = headers("user_demo_003", key=key)

    def body(dataset_version: str) -> dict:
        return {
            "suite_id": "suite_demo_001",
            "layer": "L0",
            "dataset_version": dataset_version,
            "idempotency_key": key,
        }

    first = await client.post(
        "/api/v1/benchmarks/run", json=body("ds_demo_v1"), headers=request_headers
    )
    assert_error(first, 503, "BENCH-503")

    replay = await client.post(
        "/api/v1/benchmarks/run", json=body("ds_demo_v1"), headers=request_headers
    )
    assert_error(replay, 503, "BENCH-503")

    other_target = await client.post(
        "/api/v1/benchmarks/run", json=body("ds_demo_v2"), headers=request_headers
    )
    assert_error(other_target, 503, "BENCH-503")


async def test_api_18_rejects_already_running_suite(client):
    response = await client.post(
        "/api/v1/benchmarks/run",
        json={
            "suite_id": "suite_demo_001",
            "layer": "L2",
            "dataset_version": "ds_demo_v2",
            "idempotency_key": "idem_bench_002",
        },
        headers=headers("user_demo_003", key="idem_bench_002"),
    )
    body = assert_error(response, 409, "BENCH-409")
    assert body["details"]["suite_id"] == "suite_demo_001"


async def test_api_18_validates_key_and_layer(client):
    mismatch = await client.post(
        "/api/v1/benchmarks/run",
        json={
            "suite_id": "suite_demo_001",
            "layer": "L0",
            "dataset_version": "ds_demo_v1",
            "idempotency_key": "body_key",
        },
        headers=headers("user_demo_003", key="header_key"),
    )
    assert_error(mismatch, 422, "BENCH-422")

    invalid_layer = await client.post(
        "/api/v1/benchmarks/run",
        json={
            "suite_id": "suite_demo_001",
            "layer": "L9",
            "dataset_version": "ds_demo_v1",
            "idempotency_key": "idem_bench_003",
        },
        headers=headers("user_demo_003", key="idem_bench_003"),
    )
    assert_error(invalid_layer, 422, "BENCH-422")


async def test_api_18_requires_checker2_and_project_membership(client):
    checker1 = await client.post(
        "/api/v1/benchmarks/run",
        json={
            "suite_id": "suite_demo_001",
            "layer": "L0",
            "dataset_version": "ds_demo_v1",
            "idempotency_key": "idem_bench_004",
        },
        headers=headers("user_demo_002", key="idem_bench_004"),
    )
    assert_error(checker1, 403, "BENCH-403")

    non_member = await client.post(
        "/api/v1/benchmarks/run",
        json={
            "suite_id": "suite_demo_001",
            "layer": "L0",
            "dataset_version": "ds_demo_v1",
            "idempotency_key": "idem_bench_005",
        },
        headers=headers("user_demo_007", key="idem_bench_005"),
    )
    assert_error(non_member, 403, "AUTH-403")
