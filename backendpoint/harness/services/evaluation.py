"""Benchmark 评测服务 (Spec 11.1 ``run_benchmark``, API-18).

Production binds this step to a Celery 评测任务; here it is the real in-process
service behind the accepted ``benchmark.run`` tool call: one ``asyncio`` task
per accepted run executes the L0/L1/L2 evaluation pass and closes the run out
with the Spec 12.2 registered ``benchmark.run.completed`` ledger event, whose
payload digest covers ``benchmark_run_id`` + 层 + 套件 + 指标摘要.

Contract boundaries kept (API-18 / Spec 11.x):

- the API-18 response returns immediately with ``status=running`` — the
  evaluation is asynchronous; results are append-only;
- only aggregate metrics leave the service — never sample texts, prompts,
  secrets or per-case raw records (契约 §6 API-18 脱敏规则);
- L2 runs shadow-only (``shadow_execution: true``) and never touches
  production tables — nothing in this service writes any pipeline table;
- metrics are deterministic per (suite, layer, dataset_version) — the same
  evaluated triple always yields the same aggregate numbers, so re-runs are
  comparable instead of being re-rolled noise.

The evaluation itself simulates the three-layer pass (L0 static injection,
L1 fault injection, L2 shadow execution) because no dataset infrastructure
exists in the environment yet; the simulation is declared in the ledger
payload (``simulated: true``) rather than passed off as a live run.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from app.core.harness.errors import HarnessError
from app.core.harness.models import Clock, isoformat, utcnow
from app.core.utils import digest_of

# Spec 11.x layers; API-18 enumerates them exactly (L0/L1/L2).
_LAYERS = ("L0", "L1", "L2")

_LEDGER_ACTOR = "benchmark-service"

EVENT_COMPLETED = "benchmark.run.completed"


class BenchmarkEvaluationService:
    """Runs accepted benchmark evaluations to completion (append-only)."""

    def __init__(
        self,
        *,
        append_ledger: Callable[[dict[str, Any]], Awaitable[None]],
        runs: dict[str, dict[str, Any]],
        clock: Clock = utcnow,
        duration_seconds: float = 1.0,
    ) -> None:
        self._append_ledger = append_ledger
        self._runs = runs
        self._clock = clock
        self._duration = max(0.0, duration_seconds)
        self._tasks: set[asyncio.Task] = set()

    def start(
        self,
        *,
        benchmark_run_id: str,
        suite_id: str,
        layer: str,
        dataset_version: str,
        project_id: str,
        actor_id: str,
    ) -> asyncio.Task:
        """Schedule the evaluation; the API-18 caller returns 201 right away."""

        task = asyncio.create_task(
            self.run(
                benchmark_run_id=benchmark_run_id,
                suite_id=suite_id,
                layer=layer,
                dataset_version=dataset_version,
                project_id=project_id,
                actor_id=actor_id,
            ),
            name=f"benchmark-eval:{benchmark_run_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def run(
        self,
        *,
        benchmark_run_id: str,
        suite_id: str,
        layer: str,
        dataset_version: str,
        project_id: str,
        actor_id: str,
    ) -> dict[str, Any]:
        """Evaluate one accepted run and record ``benchmark.run.completed``.

        Never raises for evaluation outcomes: a failed evaluation is still a
        completed evaluation pass and must close the run out (fail honestly)
        with the registered ledger event.
        """

        started = self._clock()
        try:
            layer = self._require_layer(layer)
            if not suite_id.strip() or not dataset_version.strip():
                raise HarnessError(422, "BENCH-422", "suite_id/dataset_version required")

            if self._duration:
                # L0 static injection, L1 fault injection, L2 shadow execution
                # run as one timed pass in the simulated evaluator.
                await asyncio.sleep(self._duration)

            metrics = self._evaluate(
                suite_id=suite_id.strip(),
                layer=layer,
                dataset_version=dataset_version.strip(),
            )
            summary: dict[str, Any] = {
                "status": "succeeded",
                "layer": layer,
                "shadow_execution": layer == "L2",
                "metrics": metrics,
                "simulated": True,
            }
        except Exception as exc:  # noqa: BLE001 — the run must close out
            summary = {
                "status": "failed",
                "failure_code": getattr(exc, "error_code", "BENCH-500"),
                "message": str(exc)[:200],
                "simulated": True,
            }

        completed_at = isoformat(self._clock())
        duration_ms = int((self._clock() - started).total_seconds() * 1000)
        record = self._runs.get(benchmark_run_id)
        if record is not None:
            record["status"] = summary["status"]
            record["completed_at"] = completed_at
            record["duration_ms"] = duration_ms
            if "metrics" in summary:
                record["metrics"] = summary["metrics"]

        # Spec 12.2: payload 覆盖 benchmark_run_id、层、套件、指标摘要.
        await self._append_ledger(
            {
                "project_id": project_id,
                "actor_id": actor_id or _LEDGER_ACTOR,
                "event_type": EVENT_COMPLETED,
                "resource_type": "benchmark_run",
                "resource_id": benchmark_run_id,
                "payload_digest": digest_of(
                    {
                        "benchmark_run_id": benchmark_run_id,
                        "suite_id": suite_id,
                        "layer": layer if isinstance(layer, str) else None,
                        "dataset_version": dataset_version,
                        "summary": summary,
                    }
                ),
            }
        )
        return {"benchmark_run_id": benchmark_run_id, **summary}

    # -- evaluation pass ---------------------------------------------------

    @staticmethod
    def _require_layer(layer: str) -> str:
        if layer not in _LAYERS:
            raise HarnessError(
                422, "BENCH-422", f"layer must be one of {'/'.join(_LAYERS)}"
            )
        return layer

    @staticmethod
    def _evaluate(*, suite_id: str, layer: str, dataset_version: str) -> dict[str, Any]:
        """Deterministic aggregate metrics for the evaluated triple.

        All values are aggregates (rates in %, latencies in ms) derived from
        the SHA-256 of the evaluation scope; no per-sample records exist.
        """

        seed = digest_of(
            {
                "suite_id": suite_id,
                "layer": layer,
                "dataset_version": dataset_version,
            }
        )
        lanes = [int(seed[i * 8 : (i + 1) * 8], 16) for i in range(4)]
        accuracy = round(85 + lanes[0] % 1_500 / 100, 2)
        schema_coverage = round(88 + lanes[1] % 1_200 / 100, 2)
        p0_interception = round(90 + lanes[2] % 1_000 / 100, 2)
        p1_interception = round(75 + lanes[3] % 2_000 / 100, 2)
        latency_p50 = 100 + lanes[0] % 400
        latency_p95 = latency_p50 + 100 + lanes[1] % 300
        latency_p99 = latency_p95 + 50 + lanes[2] % 200
        # Harder layers exercise more cases; the case counts stay aggregates.
        case_count = (50 + lanes[3] % 51) * (_LAYERS.index(layer) + 1)
        return {
            "case_count": case_count,
            "accuracy": accuracy,
            "schema_coverage": schema_coverage,
            "p0_interception_rate": p0_interception,
            "p1_interception_rate": p1_interception,
            "latency_ms_p50": latency_p50,
            "latency_ms_p95": latency_p95,
            "latency_ms_p99": latency_p99,
        }

    # -- shutdown ------------------------------------------------------------

    async def aclose(self) -> None:
        """Wait for in-flight evaluations (application shutdown)."""

        pending = [t for t in self._tasks if not t.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


__all__ = ["BenchmarkEvaluationService", "EVENT_COMPLETED"]
