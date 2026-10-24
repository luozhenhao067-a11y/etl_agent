from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field

from app.schemas.common import ApiModel


class FileAssetData(ApiModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    status: str
    file_format: str
    file_schema: dict[str, Any] = Field(alias="schema_json")
    created_at: str
