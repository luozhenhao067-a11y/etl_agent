from __future__ import annotations

import pytest

from app.config import Settings
from app.core.masking import (
    contains_secret_material,
    mask_email,
    mask_host,
    mask_jdbc_url,
    mask_phone,
    sanitize_log_line,
)
from tests.support import (
    PROJECT_ID,
    assert_error,
    assert_envelope,
    connection_body,
    headers,
)

EXPECTED_PATHS = {
    "/health": {"get"},
    "/api/v1/projects/{project_id}/connections": {"get"},
    "/api/v1/connections": {"post"},
    "/api/v1/connections/{id}": {"put"},
    "/api/v1/connections/{id}/tests": {"post"},
    "/api/v1/connections/{id}/profiles": {"post"},
    "/api/v1/file-assets": {"post"},
    "/api/v1/pipelines": {"post"},
    "/api/v1/versions/{version_id}/generation": {"post"},
    "/api/v1/agent-runs/{run_id}/answers": {"post"},
    "/api/v1/versions/{version_id}/design": {"get"},
    "/api/v1/versions/{version_id}/prepare": {"post"},
    "/api/v1/approval-requests/{approval_id}/decisions": {"post"},
    "/api/v1/preparations/{preparation_id}/commit": {"post"},
    "/api/v1/execution-runs/{id}": {"get"},
    "/api/v1/execution-runs/{id}/cancel": {"post"},
    "/api/v1/execution-runs/{id}/rollback": {"post"},
    "/api/v1/benchmarks/run": {"post"},
}


async def test_openapi_covers_api_01_to_18(client):
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    actual = {
        path: {method for method in operations if method in {"get", "post", "put"}}
        for path, operations in spec["paths"].items()
    }
    assert actual == EXPECTED_PATHS


async def test_openapi_creation_statuses_match_contract(client):
    spec = (await client.get("/openapi.json")).json()
    assert "201" in spec["paths"]["/api/v1/connections"]["post"]["responses"]
    assert "201" in spec["paths"]["/api/v1/file-assets"]["post"]["responses"]
    assert "201" in spec["paths"]["/api/v1/pipelines"]["post"]["responses"]
    assert "201" in spec["paths"]["/api/v1/versions/{version_id}/generation"]["post"]["responses"]
    assert "201" in spec["paths"]["/api/v1/versions/{version_id}/prepare"]["post"]["responses"]
    assert "201" in spec["paths"]["/api/v1/preparations/{preparation_id}/commit"]["post"]["responses"]
    assert "201" in spec["paths"]["/api/v1/benchmarks/run"]["post"]["responses"]


async def test_docs_page_is_available(client):
    response = await client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "swagger-ui" in response.text.lower()


def test_settings_reject_wildcard_cors_origin():
    with pytest.raises(ValueError, match="wildcard"):
        Settings(cors_origins=("*",))


async def test_cors_preflight_allows_frontend_origin_without_wildcard(client):
    origin = "http://localhost:5173"
    response = await client.options(
        f"/api/v1/projects/{PROJECT_ID}/connections",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization, X-Correlation-Id, Idempotency-Key",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"
    allowed = response.headers["access-control-allow-headers"].lower()
    for name in ("authorization", "x-correlation-id", "idempotency-key", "content-type"):
        assert name in allowed
    assert "*" not in response.headers["access-control-allow-origin"]


async def test_health_requires_authentication(client):
    response = await client.get("/health")
    assert_error(response, 401, "AUTH-401")


async def test_health_reports_degraded_without_faking_dependencies(client):
    response = await client.get("/health", headers=headers())
    data = assert_envelope(response)
    assert data["status"] == "degraded"
    components = {item["name"]: item["status"] for item in data["components"]}
    assert components["api"] == "ok"
    assert components["database"] == "not_configured"
    assert components["harness"] == "not_implemented"
    assert components["secret_provider"] == "not_implemented"
    assert components["execution_engine"] == "not_implemented"


async def test_correlation_id_is_echoed(client):
    correlation_id = "corr_contract_test_001"
    response = await client.get(
        f"/api/v1/projects/{PROJECT_ID}/connections",
        headers=headers(correlation_id=correlation_id),
    )
    data = assert_envelope(response)
    assert len(data["items"]) >= 1
    assert response.headers["X-Correlation-Id"] == correlation_id


async def test_correlation_id_is_generated_when_absent(client):
    response = await client.get(
        f"/api/v1/projects/{PROJECT_ID}/connections", headers=headers()
    )
    assert_envelope(response)
    generated = response.headers["X-Correlation-Id"]
    assert generated.startswith("corr_")
    assert response.json()["correlation_id"] == generated


async def test_invalid_correlation_id_is_rejected(client):
    response = await client.get(
        f"/api/v1/projects/{PROJECT_ID}/connections",
        headers=headers(correlation_id="bad id with spaces"),
    )
    body = assert_error(response, 400, "API-400")
    assert body["details"] == {"header": "X-Correlation-Id"}


async def test_unknown_path_uses_unified_error(client):
    response = await client.get("/api/v1/not-a-contract-path", headers=headers())
    assert_error(response, 404, "API-404")


async def test_malformed_json_uses_unified_error(client):
    response = await client.post(
        "/api/v1/connections",
        headers=headers(key="idem_malformed_json", content_type=True),
        content="{",
    )
    assert_error(response, 400, "API-400")


async def test_missing_authorization_uses_unified_error(client):
    response = await client.get(f"/api/v1/projects/{PROJECT_ID}/connections")
    assert_error(response, 401, "AUTH-401")


async def test_invalid_authorization_uses_unified_error(client):
    response = await client.get(
        f"/api/v1/projects/{PROJECT_ID}/connections",
        headers={"Authorization": "Bearer not_a_user"},
    )
    assert_error(response, 401, "AUTH-401")


def test_masking_helpers():
    assert mask_phone("13812345678") == "138****5678"
    assert mask_email("alice@example.com") == "a***@example.com"
    assert mask_host("10.20.30.40") == "10.20.*.*"
    assert "***" in mask_jdbc_url("jdbc:mysql://user:pass@db.example.com:3306/orders")
    assert "pass" not in mask_jdbc_url("jdbc:mysql://user:pass@db.example.com:3306/orders")

    line = sanitize_log_line(
        "phone=13812345678 email=alice@example.com ip=10.20.30.40 password=abc123"
    )
    assert "13812345678" not in line
    assert "alice@example.com" not in line
    assert "10.20.30.40" not in line
    assert "abc123" not in line
    assert "password=***" in line

    assert contains_secret_material("password=abc123")
    assert contains_secret_material("jdbc:mysql://user:pass@db:3306/x")
    assert not contains_secret_material("把 MySQL 订单表同步到 Doris")


async def test_required_write_endpoints_reject_missing_idempotency_key(client):
    # API-05 and API-10 are contract exceptions and are tested separately.
    cases = [
        ("post", "/api/v1/connections", connection_body("missing_key_conn"), "user_demo_001"),
        ("put", "/api/v1/connections/conn_demo_001", {"name": "mysql_orders_v2"}, "user_demo_001"),
        (
            "post",
            "/api/v1/connections/conn_demo_001/profiles",
            {"schemas": ["sales"], "tables": ["orders"], "sample_rows": 5, "readonly": True},
            "user_demo_001",
        ),
        (
            "post",
            "/api/v1/pipelines",
            {"project_id": PROJECT_ID, "name": "缺键项目", "code": "missing_key_pipeline"},
            "user_demo_001",
        ),
        (
            "post",
            "/api/v1/versions/ver_demo_002/generation",
            {
                "prompt": "同步订单",
                "source_profile_ref": "profile_src",
                "target_profile_ref": "profile_dst",
            },
            "user_demo_001",
        ),
        (
            "post",
            "/api/v1/versions/ver_demo_001/prepare",
            {
                "schedule": {"mode": "manual"},
                "budget": {"max_input_rows": 10},
                "quality_contract_ref": "qc_demo_001",
            },
            "user_demo_001",
        ),
        (
            "post",
            "/api/v1/approval-requests/apr_demo_001/decisions",
            {"decision": "approve", "idempotency_key": "body_key_001"},
            "user_demo_002",
        ),
        (
            "post",
            "/api/v1/preparations/prep_demo_005/commit",
            {"idempotency_key": "body_key_002"},
            "user_demo_004",
        ),
        (
            "post",
            "/api/v1/execution-runs/run_demo_001/cancel",
            {"reason": "取消", "idempotency_key": "body_key_003"},
            "user_demo_004",
        ),
        (
            "post",
            "/api/v1/execution-runs/run_demo_003/rollback",
            {
                "reason": "回滚",
                "confirmation": "ROLLBACK",
                "idempotency_key": "body_key_004",
            },
            "user_demo_004",
        ),
        (
            "post",
            "/api/v1/benchmarks/run",
            {
                "suite_id": "suite_demo_001",
                "layer": "L0",
                "dataset_version": "ds_demo_v1",
                "idempotency_key": "body_key_005",
            },
            "user_demo_003",
        ),
    ]

    for method, path, body, user_id in cases:
        response = await client.request(
            method.upper(), path, json=body, headers=headers(user_id)
        )
        assert_error(response, 400, "API-400")


@pytest.mark.parametrize(
    ("method", "path", "first", "second", "user_id", "conflict_code"),
    [
        (
            "post",
            "/api/v1/connections",
            connection_body("idem_conn_a"),
            connection_body("idem_conn_b"),
            "user_demo_001",
            "CONN-409",
        ),
        (
            "put",
            "/api/v1/connections/conn_demo_001",
            {"name": "idem_update_a"},
            {"name": "idem_update_b"},
            "user_demo_001",
            "CONN-409",
        ),
        (
            "post",
            "/api/v1/connections/conn_demo_001/profiles",
            {"schemas": ["sales"], "tables": ["orders"], "sample_rows": 1, "readonly": True},
            {"schemas": ["sales"], "tables": ["customers"], "sample_rows": 1, "readonly": True},
            "user_demo_001",
            "API-409",
        ),
        (
            "post",
            "/api/v1/pipelines",
            {"project_id": PROJECT_ID, "name": "幂等A", "code": "idem_pipeline_a"},
            {"project_id": PROJECT_ID, "name": "幂等B", "code": "idem_pipeline_b"},
            "user_demo_001",
            "API-409",
        ),
        (
            "post",
            "/api/v1/versions/ver_demo_002/generation",
            {
                "prompt": "需求 A",
                "source_profile_ref": "profile_src",
                "target_profile_ref": "profile_dst",
            },
            {
                "prompt": "需求 B",
                "source_profile_ref": "profile_src",
                "target_profile_ref": "profile_dst",
            },
            "user_demo_001",
            "GEN-409",
        ),
        (
            "post",
            "/api/v1/versions/ver_demo_001/prepare",
            {
                "schedule": {"mode": "manual"},
                "budget": {"max_input_rows": 10},
                "quality_contract_ref": "qc_demo_001",
            },
            {
                "schedule": {"mode": "manual"},
                "budget": {"max_input_rows": 20},
                "quality_contract_ref": "qc_demo_001",
            },
            "user_demo_001",
            "PREP-409",
        ),
        (
            "post",
            "/api/v1/approval-requests/apr_demo_001/decisions",
            {"decision": "approve", "opinion": "A", "idempotency_key": "idem_conflict_key_001"},
            {"decision": "approve", "opinion": "B", "idempotency_key": "idem_conflict_key_001"},
            "user_demo_002",
            "APR-409",
        ),
        (
            "post",
            "/api/v1/execution-runs/run_demo_001/cancel",
            {"reason": "原因 A", "idempotency_key": "idem_conflict_key_001"},
            {"reason": "原因 B", "idempotency_key": "idem_conflict_key_001"},
            "user_demo_004",
            "OPS-409",
        ),
        (
            "post",
            "/api/v1/execution-runs/run_demo_003/rollback",
            {
                "reason": "原因 A",
                "confirmation": "ROLLBACK",
                "idempotency_key": "idem_conflict_key_001",
            },
            {
                "reason": "原因 B",
                "confirmation": "ROLLBACK",
                "idempotency_key": "idem_conflict_key_001",
            },
            "user_demo_004",
            "OPS-409",
        ),
    ],
)
async def test_same_key_with_different_payload_conflicts(
    client,
    method,
    path,
    first,
    second,
    user_id,
    conflict_code,
):
    key = "idem_conflict_key_001"
    first_response = await client.request(
        method.upper(), path, json=first, headers=headers(user_id, key=key)
    )
    assert first_response.status_code in {200, 201, 503}, first_response.text

    second_response = await client.request(
        method.upper(), path, json=second, headers=headers(user_id, key=key)
    )
    assert_error(second_response, 409, conflict_code)
