from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from app.schemas.common import ApiModel


class PrepareRequest(ApiModel):
    schedule: dict[str, Any]
    budget: dict[str, Any]
    quality_contract_ref: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def _budget_required(self) -> "PrepareRequest":
        if not self.schedule:
            raise ValueError("schedule must not be empty")
        if not self.budget:
            raise ValueError("budget must not be empty")
        for key, value in self.budget.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value < 0:
                raise ValueError(f"budget.{key} must not be negative")
        return self


class ApprovalSlot(ApiModel):
    role_slot: str
    approver_id: str
    # 契约: item 字段待确认 — the backing approval_request id, so API-13 is
    # drivable from the API-12 response alone.
    approval_id: str | None = None


class PrepareData(ApiModel):
    preparation_id: str
    fingerprint: str
    risk_level: str
    approval_slots: list[ApprovalSlot]
    rollback_plan: dict[str, Any]
    status: str


class DecisionRequest(ApiModel):
    decision: Literal["approve", "reject"]
    opinion: str | None = Field(default=None, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class DecisionData(ApiModel):
    approval_id: str
    status: str
    decided_at: str
    next_slot_status: str | None = None


class CommitRequest(ApiModel):
    idempotency_key: str = Field(min_length=1, max_length=200)


class CommitData(ApiModel):
    execution_run_id: str
    status: str
    committed_at: str
    capability_digest: str


class Metrics(ApiModel):
    input_records: int = Field(ge=0)
    output_records: int = Field(ge=0)
    error_records: int = Field(ge=0)
    bytes_processed: int = Field(ge=0)
    duration_seconds: int | None = Field(default=None, ge=0)


class QualityReport(ApiModel):
    status: str
    error_codes: list[dict[str, Any]]
    samples_masked: bool


class Supervision(ApiModel):
    status: str
    actions: list[str]


class ExecutionRunData(ApiModel):
    status: str
    engine_job_id: str | None = None
    metrics: Metrics
    quality_report: QualityReport | None = None
    supervision: Supervision | None = None
    started_at: str | None = None
    finished_at: str | None = None
    recent_logs: list[str] | None = None


class CancelRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class CancelData(ApiModel):
    status: str
    cancelled_at: str | None = None
    external_ref: str | None = None


class RollbackRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=2000)
    confirmation: Literal["ROLLBACK"]
    idempotency_key: str = Field(min_length=1, max_length=200)


class RollbackData(ApiModel):
    rollback_status: str
    ledger_event_id: str
    finished_at: str


class BenchmarkRequest(ApiModel):
    suite_id: str = Field(min_length=1, max_length=128)
    layer: Literal["L0", "L1", "L2"]
    dataset_version: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=200)


class BenchmarkData(ApiModel):
    benchmark_run_id: str
    status: str
    started_at: str
