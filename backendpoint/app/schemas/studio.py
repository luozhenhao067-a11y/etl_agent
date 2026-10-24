from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.schemas.common import ApiModel

Provider = Literal["openai_compatible", "deepseek", "qwen"]


class PipelineCreateRequest(ApiModel):
    project_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=1024)


class PipelineCreateData(ApiModel):
    pipeline_id: str
    status: str
    created_at: str


class GenerationRequest(ApiModel):
    prompt: str = Field(min_length=1, max_length=8000)
    source_profile_ref: str = Field(min_length=1, max_length=255)
    target_profile_ref: str = Field(min_length=1, max_length=255)
    provider: Provider | None = None
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)


class InterruptField(ApiModel):
    name: str
    type: str


class Interrupt(ApiModel):
    question: str
    fields: list[InterruptField]


class GenerationData(ApiModel):
    agent_run_id: str
    thread_id: str
    status: str
    interrupt: Interrupt | None = None
    design_digest: str | None = None


class AnswersRequest(ApiModel):
    answers: dict[str, Any] = Field(min_length=1)
    thread_id: str = Field(min_length=1)


class AnswersData(ApiModel):
    status: str
    next_question: dict[str, Any] | None = None
    design_ready: bool
    checkpoint_ref: str | None = None


class DesignData(ApiModel):
    etl_plan_json: dict[str, Any]
    hocon_text: str
    dag: dict[str, Any]
    quality_contract: dict[str, Any]
    gate_result: dict[str, Any]
    diff: dict[str, Any] | None = None
    masking: dict[str, Any] | None = None
