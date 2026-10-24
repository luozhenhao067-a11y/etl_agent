from __future__ import annotations

from app.container import Container
from tests.support import (
    OTHER_PROJECT_ID,
    PROJECT_ID,
    assert_envelope,
    assert_error,
    connection_body,
    headers,
)


async def test_api_02_lists_connections_with_masked_fields(client):
    response = await client.get(
        f"/api/v1/projects/{PROJECT_ID}/connections", headers=headers()
    )
    data = assert_envelope(response)
    assert data["total"] == 7
    assert data["page"] == 1
    assert data["page_size"] == 20
    first = data["items"][0]
    assert first["id"] == "conn_demo_001"
    assert set(first) == {
        "id",
        "name",
        "type",
        "env",
        "status",
        "host_masked",
        "source_target",
        "last_tested_at",
        "secret_state",
    }
    assert "*" in first["host_masked"]
    assert "secret_ref" not in first


async def test_api_02_filters_and_paginates(client):
    response = await client.get(
        f"/api/v1/projects/{PROJECT_ID}/connections",
        params={"type": "mysql", "env": "prod", "page": 1, "page_size": 1},
        headers=headers(),
    )
    data = assert_envelope(response)
    assert data["total"] == 1
    assert data["items"][0]["id"] == "conn_demo_001"

    second_page = await client.get(
        f"/api/v1/projects/{PROJECT_ID}/connections",
        params={"page": 2, "page_size": 3},
        headers=headers("user_demo_005"),
    )
    page_data = assert_envelope(second_page)
    assert page_data["total"] == 7
    assert len(page_data["items"]) == 3
    assert page_data["items"][0]["id"] == "conn_demo_004"


async def test_api_02_page_size_upper_bound(client):
    response = await client.get(
        f"/api/v1/projects/{PROJECT_ID}/connections",
        params={"page_size": 101},
        headers=headers(),
    )
    body = assert_error(response, 400, "API-400")
    assert body["details"]["field"] == "page_size"


async def test_api_02_invalid_query_is_rejected(client):
    response = await client.get(
        f"/api/v1/projects/{PROJECT_ID}/connections",
        params={"page": 0},
        headers=headers(),
    )
    assert_error(response, 400, "API-400")

    bad_env = await client.get(
        f"/api/v1/projects/{PROJECT_ID}/connections",
        params={"env": "staging"},
        headers=headers(),
    )
    assert_error(bad_env, 400, "API-400")


async def test_api_02_unknown_query_is_rejected(client):
    # Contract API-02 allows only type/env/status/page/page_size. An unknown
    # parameter such as q must not be silently ignored.
    response = await client.get(
        f"/api/v1/projects/{PROJECT_ID}/connections",
        params={"q": "orders"},
        headers=headers(),
    )
    body = assert_error(response, 400, "API-400")
    assert body["details"]["field"] == "q"


async def test_api_02_project_isolation(client):
    other_project = await client.get(
        f"/api/v1/projects/{OTHER_PROJECT_ID}/connections", headers=headers()
    )
    assert_error(other_project, 403, "AUTH-403")

    non_member = await client.get(
        f"/api/v1/projects/{PROJECT_ID}/connections", headers=headers("user_demo_007")
    )
    assert_error(non_member, 403, "AUTH-403")

    missing_project = await client.get(
        "/api/v1/projects/prj_does_not_exist/connections", headers=headers()
    )
    assert_error(missing_project, 404, "API-404")


async def test_api_03_creates_connection_with_mask_and_audit(client, container: Container):
    response = await client.post(
        "/api/v1/connections",
        json=connection_body("mysql_created"),
        headers=headers(key="idem_create_conn_001"),
    )
    data = assert_envelope(response, 201)
    assert data["id"].startswith("conn_")
    assert data["status"] == "active"
    assert data["secret_state"] == "configured"

    created = container.state.connections[data["id"]]
    assert created["host_masked"] == "db.***"
    assert created["secret_ref_digest"] is not None
    assert "secret_ref" not in created
    assert "username" not in created or created["username"] is None

    listing = await client.get(
        f"/api/v1/projects/{PROJECT_ID}/connections", headers=headers()
    )
    item = next(
        row for row in assert_envelope(listing)["items"] if row["id"] == data["id"]
    )
    assert item["host_masked"] == "db.***"
    assert "db.internal.example" not in str(item)

    events = container.repository.list_audit_events(PROJECT_ID)
    assert [event["event_type"] for event in events] == [
        "connection.created",
        "secret.ref.bound",
    ]
    assert len(events[0]["payload_digest"]) == 64
    assert "payload" not in events[0]
    assert events[1]["resource_id"] == data["id"]
    assert events[1]["prev_event_hash"] == events[0]["event_hash"]


async def test_api_03_is_idempotent(client):
    body = connection_body("mysql_idempotent")
    key = "idem_create_conn_002"
    first = await client.post(
        "/api/v1/connections", json=body, headers=headers(key=key)
    )
    first_data = assert_envelope(first, 201)
    second = await client.post(
        "/api/v1/connections", json=body, headers=headers(key=key)
    )
    second_data = assert_envelope(second, 201)
    assert second_data == first_data


async def test_api_03_duplicate_name_conflicts(client):
    response = await client.post(
        "/api/v1/connections",
        json=connection_body("mysql_orders"),
        headers=headers(key="idem_create_conn_003"),
    )
    body = assert_error(response, 409, "CONN-409")
    assert body["details"] == {"field": "name"}


async def test_api_03_semantic_validation(client):
    missing_db_fields = await client.post(
        "/api/v1/connections",
        json=connection_body("mysql_bad", port=None, database=None),
        headers=headers(key="idem_create_conn_004"),
    )
    assert_error(missing_db_fields, 422, "CONN-422")

    credential_in_host = await client.post(
        "/api/v1/connections",
        json=connection_body("mysql_bad_host", host="mysql://user:pass@db"),
        headers=headers(key="idem_create_conn_005"),
    )
    assert_error(credential_in_host, 422, "CONN-422")

    bad_enum = await client.post(
        "/api/v1/connections",
        json=connection_body("mysql_bad_type", type="mongodb"),
        headers=headers(key="idem_create_conn_006"),
    )
    assert_error(bad_enum, 422, "CONN-422")


async def test_api_03_requires_maker(client):
    response = await client.post(
        "/api/v1/connections",
        json=connection_body("mysql_checker"),
        headers=headers("user_demo_002", key="idem_create_conn_007"),
    )
    assert_error(response, 403, "ROLE-403")


async def test_api_04_updates_connection_and_audit_chain(client, container: Container):
    created = assert_envelope(
        await client.post(
            "/api/v1/connections",
            json=connection_body("mysql_chain"),
            headers=headers(key="idem_create_chain"),
        ),
        201,
    )
    connection_id = created["id"]

    response = await client.put(
        f"/api/v1/connections/{connection_id}",
        json={"name": "mysql_chain_v2", "env": "preprod"},
        headers=headers(key="idem_update_chain"),
    )
    data = assert_envelope(response)
    assert data["id"] == connection_id
    assert data["status"] == "active"
    assert container.state.connections[connection_id]["name"] == "mysql_chain_v2"

    events = container.repository.list_audit_events(PROJECT_ID)
    assert [event["event_type"] for event in events] == [
        "connection.created",
        "secret.ref.bound",
        "connection.updated",
    ]
    assert events[2]["prev_event_hash"] == events[1]["event_hash"]
    assert events[2]["event_hash"] != events[1]["event_hash"]


async def test_api_04_is_idempotent(client):
    key = "idem_update_replay"
    body = {"name": "mysql_orders_replay"}
    first = await client.put(
        "/api/v1/connections/conn_demo_001", json=body, headers=headers(key=key)
    )
    first_data = assert_envelope(first)
    second = await client.put(
        "/api/v1/connections/conn_demo_001", json=body, headers=headers(key=key)
    )
    assert assert_envelope(second) == first_data


async def test_api_04_duplicate_and_invalid_payload(client):
    duplicate = await client.put(
        "/api/v1/connections/conn_demo_001",
        json={"name": "doris_orders"},
        headers=headers(key="idem_update_dup"),
    )
    assert_error(duplicate, 409, "CONN-409")

    invalid = await client.put(
        "/api/v1/connections/conn_demo_001",
        json={"port": 70000},
        headers=headers(key="idem_update_invalid"),
    )
    assert_error(invalid, 422, "CONN-422")

    blank = await client.put(
        "/api/v1/connections/conn_demo_001",
        json={},
        headers=headers(key="idem_update_empty"),
    )
    assert_error(blank, 422, "CONN-422")


async def test_api_04_permissions_and_missing_resource(client):
    checker = await client.put(
        "/api/v1/connections/conn_demo_001",
        json={"name": "checker_change"},
        headers=headers("user_demo_002", key="idem_update_checker"),
    )
    assert_error(checker, 403, "ROLE-403")

    missing = await client.put(
        "/api/v1/connections/conn_missing",
        json={"name": "ghost"},
        headers=headers(key="idem_update_missing"),
    )
    assert_error(missing, 404, "API-404")


async def test_api_05_returns_503_without_fake_success(client):
    response = await client.post(
        "/api/v1/connections/conn_demo_001/tests",
        json={"timeout_ms": 5000},
        headers=headers(),
    )
    body = assert_error(response, 503, "CONN-503")
    assert body["details"] == {
        "dependency": "harness",
        "status": "not_implemented",
    }
    assert "success" not in response.json()
    assert "latency_ms" not in response.json()


async def test_api_05_validation_permission_and_missing_resource(client):
    invalid_timeout = await client.post(
        "/api/v1/connections/conn_demo_001/tests",
        json={"timeout_ms": 0},
        headers=headers(),
    )
    assert_error(invalid_timeout, 422, "CONN-422")

    too_large = await client.post(
        "/api/v1/connections/conn_demo_001/tests",
        json={"timeout_ms": 600001},
        headers=headers(),
    )
    assert_error(too_large, 422, "CONN-422")

    checker = await client.post(
        "/api/v1/connections/conn_demo_001/tests",
        json={},
        headers=headers("user_demo_002"),
    )
    assert_error(checker, 403, "ROLE-403")

    missing = await client.post(
        "/api/v1/connections/conn_missing/tests", json={}, headers=headers()
    )
    assert_error(missing, 404, "API-404")


async def test_api_06_returns_503_and_never_fabricates_a_profile(client):
    response = await client.post(
        "/api/v1/connections/conn_demo_001/profiles",
        json={"schemas": ["sales"], "tables": ["orders"], "sample_rows": 20, "readonly": True},
        headers=headers(key="idem_profile_001"),
    )
    body = assert_error(response, 503, "META-503")
    assert body["details"] == {"dependency": "harness", "status": "not_implemented"}
    assert "profile_status" not in response.json()
    assert "masked_samples" not in response.json()


async def test_api_06_validation_and_permissions(client):
    not_readonly = await client.post(
        "/api/v1/connections/conn_demo_001/profiles",
        json={"schemas": ["sales"], "tables": ["orders"], "sample_rows": 1, "readonly": False},
        headers=headers(key="idem_profile_002"),
    )
    assert_error(not_readonly, 422, "META-422")

    empty_scope = await client.post(
        "/api/v1/connections/conn_demo_001/profiles",
        json={"schemas": [], "tables": ["orders"], "sample_rows": 1, "readonly": True},
        headers=headers(key="idem_profile_003"),
    )
    assert_error(empty_scope, 422, "META-422")

    checker = await client.post(
        "/api/v1/connections/conn_demo_001/profiles",
        json={"schemas": ["sales"], "tables": ["orders"], "sample_rows": 1, "readonly": True},
        headers=headers("user_demo_002", key="idem_profile_004"),
    )
    assert_error(checker, 403, "META-403")

    missing = await client.post(
        "/api/v1/connections/conn_missing/profiles",
        json={"schemas": ["sales"], "tables": ["orders"], "sample_rows": 1, "readonly": True},
        headers=headers(key="idem_profile_005"),
    )
    assert_error(missing, 404, "API-404")
