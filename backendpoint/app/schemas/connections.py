from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.common import ApiModel

ConnectionType = Literal[
    "mysql",
    "postgresql",
    "oracle",
    "doris",
    "clickhouse",
    "csv",
    "excel",
    "json",
    "parquet",
    "s3",
    "minio",
    "rest_api",
]
Environment = Literal["prod", "preprod", "test"]

DATABASE_TYPES = {"mysql", "postgresql", "oracle", "doris", "clickhouse"}
NETWORK_TYPES = DATABASE_TYPES | {"s3", "minio", "rest_api"}
FILE_TYPES = {"csv", "excel", "json", "parquet"}


def _reject_embedded_credentials(value: str | None, field: str) -> None:
    if value is None:
        return
    if "@" in value or "://" in value:
        raise ValueError(f"{field} must not contain credentials")


def _reject_private_material(value: dict[str, Any] | None, field: str) -> None:
    if value is None:
        return
    forbidden = {"private_key", "password", "passwd", "pwd", "secret", "token"}
    for key in value:
        if str(key).lower() in forbidden:
            raise ValueError(f"{field} must not contain secret material")
    for item in value.values():
        if isinstance(item, dict):
            _reject_private_material(item, field)


class ConnectionCreateRequest(ApiModel):
    name: str = Field(min_length=1, max_length=128)
    type: ConnectionType
    env: Environment
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, max_length=128)
    username: str | None = Field(default=None, max_length=128)
    secret_ref: str | None = Field(default=None, max_length=512)
    readonly: bool
    tls: dict[str, Any] | None = None
    file_source: dict[str, Any] | None = None

    @field_validator("name", "database", "secret_ref")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is not None and value.strip() == "":
            raise ValueError("must not be blank")
        return value

    @field_validator("host")
    @classmethod
    def _host_safe(cls, value: str | None) -> str | None:
        _reject_embedded_credentials(value, "host")
        return value

    @field_validator("tls", "file_source")
    @classmethod
    def _no_private_material(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        _reject_private_material(value, "object")
        return value

    @model_validator(mode="after")
    def _conditional_fields(self) -> "ConnectionCreateRequest":
        if self.type in DATABASE_TYPES:
            missing = [
                field
                for field in ("host", "port", "database")
                if getattr(self, field) is None
            ]
            if missing:
                raise ValueError(f"missing required fields for database connection: {', '.join(missing)}")
        if self.type in NETWORK_TYPES and self.host is None:
            raise ValueError("host is required for network connections")
        if self.type in NETWORK_TYPES and self.file_source is None and self.type not in DATABASE_TYPES:
            raise ValueError("file_source is required for file or API connections")
        if self.type in FILE_TYPES and self.file_source is None:
            raise ValueError("file_source is required for file connections")
        return self


class ConnectionUpdateRequest(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    type: ConnectionType | None = None
    env: Environment | None = None
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, max_length=128)
    username: str | None = Field(default=None, max_length=128)
    secret_ref: str | None = Field(default=None, max_length=512)
    readonly: bool | None = None
    tls: dict[str, Any] | None = None
    file_source: dict[str, Any] | None = None

    @field_validator("name", "database", "secret_ref")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is not None and value.strip() == "":
            raise ValueError("must not be blank")
        return value

    @field_validator("host")
    @classmethod
    def _host_safe(cls, value: str | None) -> str | None:
        _reject_embedded_credentials(value, "host")
        return value

    @field_validator("tls", "file_source")
    @classmethod
    def _no_private_material(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        _reject_private_material(value, "object")
        return value

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "ConnectionUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        return self


class ConnectionTestRequest(ApiModel):
    timeout_ms: int | None = Field(default=None, gt=0, le=600000)


class ConnectionItem(ApiModel):
    id: str
    name: str
    type: str
    env: str
    status: str
    host_masked: str
    source_target: str
    last_tested_at: str | None
    secret_state: str


class ConnectionListData(ApiModel):
    items: list[ConnectionItem]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


class ConnectionCreateData(ApiModel):
    id: str
    status: str
    secret_state: str
    created_at: str


class ConnectionUpdateData(ApiModel):
    id: str
    status: str
    secret_state: str
    updated_at: str


class ConnectionTestData(ApiModel):
    success: bool
    latency_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = None
    tested_at: str


class ProfileRequest(ApiModel):
    schemas: list[str] = Field(min_length=1)
    tables: list[str] = Field(min_length=1)
    sample_rows: int = Field(ge=0)
    readonly: bool

    @model_validator(mode="after")
    def _readonly_required(self) -> "ProfileRequest":
        if self.readonly is not True:
            raise ValueError("readonly must be true")
        return self


class ProfileData(ApiModel):
    profile_status: str
    sampled_at: str | None = None
    tables: list[dict[str, Any]]
    columns: list[dict[str, Any]]
    masked_samples: list[dict[str, Any]] | None = None
