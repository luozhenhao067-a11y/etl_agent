from __future__ import annotations

from pydantic import Field

from app.schemas.common import ApiModel


class ComponentStatus(ApiModel):
    name: str
    status: str
    latency_ms: int | None = Field(default=None, ge=0)


class HealthData(ApiModel):
    status: str
    components: list[ComponentStatus]
    version: str
    time: str
