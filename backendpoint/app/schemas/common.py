"""Shared response envelope and error schema."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ErrorBody(BaseModel):
    error_code: str
    message: str
    correlation_id: str
    details: dict[str, Any]


class Envelope(ApiModel, Generic[T]):
    data: T
    correlation_id: str


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorBody, "description": "request field or header error"},
    401: {"model": ErrorBody, "description": "authentication required"},
    403: {"model": ErrorBody, "description": "permission denied"},
    404: {"model": ErrorBody, "description": "resource not found"},
    409: {"model": ErrorBody, "description": "conflict or state not allowed"},
    422: {"model": ErrorBody, "description": "semantic validation failed"},
    500: {"model": ErrorBody, "description": "internal error"},
    503: {"model": ErrorBody, "description": "dependency unavailable"},
}
