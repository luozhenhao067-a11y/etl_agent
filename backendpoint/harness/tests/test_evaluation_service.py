"""Benchmark 评测服务 tests (API-18, Spec 11.1 run_benchmark / 12.2 events).

Covers the asynchronous completion path: the registered
``benchmark.run.completed`` ledger event with the aggregate metrics summary,
the L2 shadow-only declaration, layer validation, and the honest failure
close-out.
"""

from __future__ import annotations

import pytest

from harness.services.evaluation import EVENT_COMPLETED, BenchmarkEvaluationService


def _service(**overrides):
    appended: list[dict] = []
    runs: dict[str, dict] = {}

    async def append_ledger(entry: dict) -> None:
        appended.append(entry)

    kwargs = {"append_ledger": append_ledger, "runs": runs, "duration_seconds": 0.0}
    kwargs.update(overrides)
    return BenchmarkEvaluationService(**kwargs), appended, runs


async def test_completed_event_records_metrics_summary():
    service, appended, runs = _service()
    runs["bench_1"] = {"benchmark_run_id": "bench_1", "status": "running"}

    result = await service.run(
        benchmark_run_id="bench_1",
        suite_id="suite_demo_001",
        layer="L0",
        dataset_version="ds_demo_v1",
        project_id="prj_1",
        actor_id="checker2",
    )

    assert result["status"] == "succeeded"
    assert result["simulated"] is True
    metrics = result["metrics"]
    for key in (
        "accuracy",
        "schema_coverage",
        "p0_interception_rate",
        "p1_interception_rate",
        "latency_ms_p50",
        "latency_ms_p95",
        "latency_ms_p99",
    ):
        assert key in metrics
    assert metrics["latency_ms_p50"] <= metrics["latency_ms_p95"] <= metrics["latency_ms_p99"]

    assert len(appended) == 1
    entry = appended[0]
    assert entry["event_type"] == EVENT_COMPLETED
    assert entry["resource_type"] == "benchmark_run"
    assert entry["resource_id"] == "bench_1"
    assert entry["project_id"] == "prj_1"
    assert runs["bench_1"]["status"] == "succeeded"
    assert "metrics" in runs["bench_1"]
    assert "payload_digest" in entry


async def test_metrics_are_deterministic_per_scope():
    service, _, _ = _service()
    first = await service.run(
        benchmark_run_id="b1",
        suite_id="s",
        layer="L1",
        dataset_version="v1",
        project_id="p",
        actor_id="a",
    )
    second = await service.run(
        benchmark_run_id="b2",
        suite_id="s",
        layer="L1",
        dataset_version="v1",
        project_id="p",
        actor_id="a",
    )
    assert first["metrics"] == second["metrics"]
    other = await service.run(
        benchmark_run_id="b3",
        suite_id="s",
        layer="L1",
        dataset_version="v2",
        project_id="p",
        actor_id="a",
    )
    assert other["metrics"] != first["metrics"]


async def test_l2_is_declared_shadow_execution():
    service, appended, _ = _service()
    result = await service.run(
        benchmark_run_id="b1",
        suite_id="s",
        layer="L2",
        dataset_version="v1",
        project_id="p",
        actor_id="a",
    )
    assert result["shadow_execution"] is True
    assert appended[0]["event_type"] == EVENT_COMPLETED


async def test_invalid_layer_fails_the_run_honestly():
    service, appended, runs = _service()
    runs["b1"] = {"benchmark_run_id": "b1", "status": "running"}
    result = await service.run(
        benchmark_run_id="b1",
        suite_id="s",
        layer="L9",
        dataset_version="v1",
        project_id="p",
        actor_id="a",
    )
    assert result["status"] == "failed"
    assert result["failure_code"] == "BENCH-422"
    # The run still closes out with the registered event — no dangling runs.
    assert appended[0]["event_type"] == EVENT_COMPLETED
    assert runs["b1"]["status"] == "failed"


async def test_start_schedules_and_completes():
    service, appended, runs = _service(duration_seconds=0.01)
    runs["b1"] = {"benchmark_run_id": "b1", "status": "running"}
    task = service.start(
        benchmark_run_id="b1",
        suite_id="s",
        layer="L0",
        dataset_version="v1",
        project_id="p",
        actor_id="a",
    )
    await task
    await service.aclose()
    assert runs["b1"]["status"] == "succeeded"
    assert len(appended) == 1
