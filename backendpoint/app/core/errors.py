"""Unified error structure and exception handlers (contract 2.4 / 2.5)."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.masking import sanitize_details
from app.core.utils import new_correlation_id

logger = logging.getLogger("etl_agent.api")


class ApiError(Exception):
    """A contract-shaped API error."""

    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details = details or {}


def _correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", None) or new_correlation_id()


def error_content(request: Request, error: ApiError) -> dict[str, Any]:
    return {
        "error_code": error.error_code,
        "message": error.message,
        "correlation_id": _correlation_id(request),
        "details": sanitize_details(error.details),
    }


def error_response(request: Request, error: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=error_content(request, error),
        headers={"X-Correlation-Id": _correlation_id(request)},
    )


def _validation_target(request: Request) -> tuple[int, str]:
    """Map Pydantic failures to the domain code used by the contract.

    Transport-level malformed JSON stays ``400 API-400``. Field-level semantic
    failures use the domain 422 code where the contract defines one.
    """

    path = request.url.path
    method = request.method.upper()

    if method == "GET":
        return 400, "API-400"
    if method == "POST" and path == "/api/v1/connections":
        return 422, "CONN-422"
    if method == "PUT" and re.fullmatch(r"/api/v1/connections/[^/]+", path):
        return 422, "CONN-422"
    if method == "POST" and re.fullmatch(r"/api/v1/connections/[^/]+/tests", path):
        return 422, "CONN-422"
    if method == "POST" and re.fullmatch(r"/api/v1/connections/[^/]+/profiles", path):
        return 422, "META-422"
    if method == "POST" and path == "/api/v1/file-assets":
        return 422, "FILE-422"
    if method == "POST" and path == "/api/v1/pipelines":
        return 422, "API-422"
    if method == "POST" and re.fullmatch(r"/api/v1/versions/[^/]+/generation", path):
        return 422, "GEN-422"
    if method == "POST" and re.fullmatch(r"/api/v1/agent-runs/[^/]+/answers", path):
        return 422, "GEN-422"
    if method == "POST" and re.fullmatch(r"/api/v1/versions/[^/]+/prepare", path):
        return 422, "PREP-422"
    if method == "POST" and re.fullmatch(r"/api/v1/approval-requests/[^/]+/decisions", path):
        return 422, "APR-422"
    if method == "POST" and re.fullmatch(r"/api/v1/execution-runs/[^/]+/rollback", path):
        return 422, "OPS-422"
    if method == "POST" and path == "/api/v1/benchmarks/run":
        return 422, "BENCH-422"
    # Commit and cancel do not list a 422 code in the contract.
    return 400, "API-400"


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        raw_errors = exc.errors()
        is_json_error = any(item.get("type") == "json_invalid" for item in raw_errors)
        if is_json_error:
            error = ApiError(400, "API-400", "malformed JSON request body", {"reason": "json_invalid"})
            return error_response(request, error)

        fields: dict[str, str] = {}
        for item in raw_errors:
            location = [str(part) for part in item.get("loc", ()) if part not in {"body", "query", "path", "header"}]
            field = ".".join(location) or "request"
            fields[field] = "invalid"
        status_code, error_code = _validation_target(request)
        error = ApiError(status_code, error_code, "request validation failed", {"fields": fields})
        return error_response(request, error)

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            error = ApiError(404, "API-404", "resource not found", {})
            return error_response(request, error)
        error = ApiError(exc.status_code, "API-400", "request rejected", {})
        return error_response(request, error)

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled API error correlation_id=%s", _correlation_id(request))
        error = ApiError(500, "API-500", "internal server error", {})
        return error_response(request, error)
