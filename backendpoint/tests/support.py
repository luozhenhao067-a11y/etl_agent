from __future__ import annotations

from typing import Any

from httpx import Response

PROJECT_ID = "prj_demo_001"
OTHER_PROJECT_ID = "prj_demo_999"


def headers(
    user_id: str = "user_demo_001",
    *,
    key: str | None = None,
    correlation_id: str | None = None,
    content_type: bool = False,
) -> dict[str, str]:
    result = {"Authorization": f"Bearer {user_id}"}
    if key is not None:
        result["Idempotency-Key"] = key
    if correlation_id is not None:
        result["X-Correlation-Id"] = correlation_id
    if content_type:
        result["Content-Type"] = "application/json"
    return result


def error_code(response: Response) -> str:
    return response.json()["error_code"]


def assert_error(response: Response, status_code: int, code: str) -> dict[str, Any]:
    assert response.status_code == status_code, response.text
    body = response.json()
    assert set(body) == {"error_code", "message", "correlation_id", "details"}
    assert body["error_code"] == code
    assert body["correlation_id"] == response.headers["X-Correlation-Id"]
    return body


def assert_envelope(response: Response, status_code: int = 200) -> dict[str, Any]:
    assert response.status_code == status_code, response.text
    body = response.json()
    assert set(body) == {"data", "correlation_id"}
    assert body["correlation_id"] == response.headers["X-Correlation-Id"]
    return body["data"]


def connection_body(name: str = "mysql_new", **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": name,
        "type": "mysql",
        "env": "test",
        "host": "db.internal.example",
        "port": 3306,
        "database": "orders",
        "username": "etl_reader",
        "secret_ref": "vault://kv/projects/prj_demo_001/connections/mysql_new",
        "readonly": True,
    }
    body.update(overrides)
    return body
