"""In-memory idempotency table.

Same key + same canonical payload replays the first result. Same key with a
different payload returns ``409``. The store is process-local and replaced by
PostgreSQL in a later delivery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.errors import ApiError
from app.core.utils import digest_of, new_correlation_id


@dataclass
class IdempotencyRecord:
    digest: str
    status_code: int
    data: Any | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_details: dict[str, Any] = field(default_factory=dict)


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], IdempotencyRecord] = {}

    def get(self, scope: str, key: str) -> IdempotencyRecord | None:
        return self._records.get((scope, key))

    def put(self, scope: str, key: str, record: IdempotencyRecord) -> None:
        self._records[(scope, key)] = record

    def clear(self) -> None:
        self._records.clear()


def require_idempotency_key(request: Request) -> str:
    raw = request.headers.get("Idempotency-Key")
    if raw is None or raw.strip() == "":
        raise ApiError(400, "API-400", "Idempotency-Key header is required", {"header": "Idempotency-Key"})
    key = raw.strip()
    if len(key) > 200:
        raise ApiError(400, "API-400", "Idempotency-Key header is invalid", {"header": "Idempotency-Key"})
    return key


def optional_idempotency_key(request: Request) -> str | None:
    raw = request.headers.get("Idempotency-Key")
    if raw is None:
        return None
    key = raw.strip()
    return key or None


def body_digest(payload: Any) -> str:
    return digest_of(payload)


def replay_if_present(
    store: InMemoryIdempotencyStore,
    scope: str,
    key: str,
    digest: str,
    conflict_code: str,
    request: Request,
) -> JSONResponse | None:
    record = store.get(scope, key)
    if record is None:
        return None
    if record.digest != digest:
        raise ApiError(
            409,
            conflict_code,
            "idempotency key reused with a different payload",
            {"reason": "payload_mismatch"},
        )
    # Dependency failures are retryable (contract 4.3); keep the key/digest for
    # conflict detection but let the caller retry the operation.
    if record.status_code >= 500:
        return None
    correlation_id = getattr(request.state, "correlation_id", None) or new_correlation_id()
    if record.error_code is not None:
        return JSONResponse(
            status_code=record.status_code,
            content={
                "error_code": record.error_code,
                "message": record.error_message or "request failed",
                "correlation_id": correlation_id,
                "details": record.error_details,
            },
            headers={"X-Correlation-Id": correlation_id},
        )
    return JSONResponse(
        status_code=record.status_code,
        content={"data": record.data, "correlation_id": correlation_id},
        headers={"X-Correlation-Id": correlation_id},
    )


def remember_success(
    store: InMemoryIdempotencyStore,
    scope: str,
    key: str,
    digest: str,
    status_code: int,
    data: Any,
) -> None:
    store.put(scope, key, IdempotencyRecord(digest=digest, status_code=status_code, data=data))


def remember_error(
    store: InMemoryIdempotencyStore,
    scope: str,
    key: str,
    digest: str,
    error: ApiError,
) -> None:
    store.put(
        scope,
        key,
        IdempotencyRecord(
            digest=digest,
            status_code=error.status_code,
            error_code=error.error_code,
            error_message=error.message,
            error_details=error.details,
        ),
    )
