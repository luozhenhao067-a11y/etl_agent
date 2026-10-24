"""LocalAsyncExecAdapter tests — the real ExecPort implementation.

Covers the managed simulated lifecycle (SUBMITTED → RUNNING → terminal),
deterministic metrics, cancellation, and the fail-closed refusals (missing
artifact, unknown job, failure injection marker).
"""

from __future__ import annotations

import asyncio

import pytest

from app.adapters.local.exec import LocalAsyncExecAdapter
from app.core.harness.errors import HarnessError


def _command(**overrides):
    command = {
        "execution_run_id": "run_t100",
        "preparation_id": "prep_t100",
        "version_id": "ver_t100",
        "artifact_digest": "a" * 64,
        "hocon": "env { parallelism = 1 }\nsource { } sink { }",
    }
    command.update(overrides)
    return command


async def test_submit_reaches_succeeded_with_deterministic_metrics():
    adapter = LocalAsyncExecAdapter(duration_seconds=0.05)
    result = await adapter.submit_job(_command())
    assert result["engine_job_id"].startswith("eng_")
    assert result["status"] == "SUBMITTED"

    await asyncio.sleep(0.2)
    report = await adapter.query_status(result["engine_job_id"])
    assert report["status"] == "SUCCEEDED"
    assert report["simulated"] is True
    assert report["input_records"] > 0
    assert report["error_records"] >= 0
    assert report["output_records"] == report["input_records"] - report["error_records"]
    assert report["bytes_processed"] > 0

    # Deterministic: the same artifact binding yields the same metrics.
    other = LocalAsyncExecAdapter(duration_seconds=0.05)
    other_result = await other.submit_job(_command())
    await asyncio.sleep(0.2)
    other_report = await other.query_status(other_result["engine_job_id"])
    assert {
        k: other_report[k]
        for k in ("input_records", "output_records", "error_records", "bytes_processed")
    } == {
        k: report[k]
        for k in ("input_records", "output_records", "error_records", "bytes_processed")
    }


async def test_failure_marker_ends_failed_with_error_code():
    adapter = LocalAsyncExecAdapter(duration_seconds=0.05)
    result = await adapter.submit_job(_command(hocon="source {} # exec-engine:fail"))
    await asyncio.sleep(0.2)
    report = await adapter.query_status(result["engine_job_id"])
    assert report["status"] == "FAILED"
    assert report["error_code"] == "EXEC-500"


async def test_cancel_stops_a_running_job():
    adapter = LocalAsyncExecAdapter(duration_seconds=5.0)
    result = await adapter.submit_job(_command())
    await asyncio.sleep(0.05)
    cancelled = await adapter.cancel_job(result["engine_job_id"], "operator asked")
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "operator asked"
    report = await adapter.query_status(result["engine_job_id"])
    assert report["status"] == "CANCELLED"


async def test_cancel_of_terminal_job_is_idempotent():
    adapter = LocalAsyncExecAdapter(duration_seconds=0.05)
    result = await adapter.submit_job(_command())
    await asyncio.sleep(0.2)
    cancelled = await adapter.cancel_job(result["engine_job_id"], "late cancel")
    assert cancelled["status"] == "SUCCEEDED"
    assert cancelled["cancel_reason"] is None


async def test_missing_artifact_refused():
    adapter = LocalAsyncExecAdapter()
    with pytest.raises(HarnessError) as excinfo:
        await adapter.submit_job(_command(hocon="   "))
    assert excinfo.value.error_code == "EXEC-422"
    with pytest.raises(HarnessError) as excinfo:
        await adapter.submit_job(_command(execution_run_id=""))
    assert excinfo.value.error_code == "EXEC-422"


async def test_unknown_job_is_an_honest_404():
    adapter = LocalAsyncExecAdapter()
    with pytest.raises(HarnessError) as excinfo:
        await adapter.query_status("eng_missing")
    assert (excinfo.value.status_code, excinfo.value.error_code) == (404, "EXEC-404")
