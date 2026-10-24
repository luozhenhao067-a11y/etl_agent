from __future__ import annotations

from app.container import Container
from tests.support import PROJECT_ID, assert_error, headers


def _form(project_id: str = PROJECT_ID, format: str = "csv", source: str = "local"):
    return {"project_id": project_id, "format": format, "source": source}


async def test_api_07_returns_503_and_does_not_store_or_parse(client, container: Container):
    before = len(container.repository.list_file_assets(PROJECT_ID))
    response = await client.post(
        "/api/v1/file-assets",
        data=_form(),
        files={"file": ("orders.csv", b"order_id,phone\n1,13800000000\n", "text/csv")},
        headers=headers(key="idem_file_001"),
    )
    body = assert_error(response, 503, "FILE-503")
    assert body["details"] == {"dependency": "harness", "status": "not_implemented"}
    assert "schema_json" not in response.json()
    assert "id" not in response.json()
    assert len(container.repository.list_file_assets(PROJECT_ID)) == before


async def test_api_07_requires_idempotency_key(client):
    response = await client.post(
        "/api/v1/file-assets",
        data=_form(),
        files={"file": ("orders.csv", b"a,b\n1,2\n", "text/csv")},
        headers=headers(),
    )
    assert_error(response, 400, "API-400")


async def test_api_07_validates_format_extension_and_content(client):
    bad_format = await client.post(
        "/api/v1/file-assets",
        data=_form(format="xml"),
        files={"file": ("orders.csv", b"a,b\n", "text/csv")},
        headers=headers(key="idem_file_002"),
    )
    assert_error(bad_format, 422, "FILE-422")

    bad_extension = await client.post(
        "/api/v1/file-assets",
        data=_form(),
        files={"file": ("orders.txt", b"a,b\n", "text/plain")},
        headers=headers(key="idem_file_003"),
    )
    assert_error(bad_extension, 422, "FILE-422")

    empty_file = await client.post(
        "/api/v1/file-assets",
        data=_form(),
        files={"file": ("orders.csv", b"", "text/csv")},
        headers=headers(key="idem_file_004"),
    )
    assert_error(empty_file, 422, "FILE-422")

    missing_file = await client.post(
        "/api/v1/file-assets",
        data=_form(),
        headers=headers(key="idem_file_005"),
    )
    assert_error(missing_file, 422, "FILE-422")


async def test_api_07_enforces_file_size_limit(client):
    response = await client.post(
        "/api/v1/file-assets",
        data=_form(),
        files={"file": ("big.csv", b"x" * 65, "text/csv")},
        headers=headers(key="idem_file_006"),
    )
    body = assert_error(response, 413, "FILE-413")
    assert body["details"]["max_bytes"] == 64


async def test_api_07_object_storage_path(client):
    response = await client.post(
        "/api/v1/file-assets",
        data={
            **_form(source="object_storage"),
            "object_storage_path": "s3://bucket/prefix/orders.csv",
        },
        headers=headers(key="idem_file_007"),
    )
    assert_error(response, 503, "FILE-503")

    credential_path = await client.post(
        "/api/v1/file-assets",
        data={
            **_form(source="object_storage"),
            "object_storage_path": "s3://user:pass@bucket/orders.csv",
        },
        headers=headers(key="idem_file_008"),
    )
    assert_error(credential_path, 422, "FILE-422")


async def test_api_07_permissions_and_project_boundary(client):
    checker = await client.post(
        "/api/v1/file-assets",
        data=_form(),
        files={"file": ("orders.csv", b"a,b\n", "text/csv")},
        headers=headers("user_demo_002", key="idem_file_009"),
    )
    assert_error(checker, 403, "ROLE-403")

    other_project = await client.post(
        "/api/v1/file-assets",
        data=_form(project_id="prj_demo_999"),
        files={"file": ("orders.csv", b"a,b\n", "text/csv")},
        headers=headers(key="idem_file_010"),
    )
    assert_error(other_project, 403, "AUTH-403")


async def test_api_07_idempotency_conflict(client):
    key = "idem_file_conflict"
    first = await client.post(
        "/api/v1/file-assets",
        data=_form(),
        files={"file": ("orders.csv", b"a,b\n1,2\n", "text/csv")},
        headers=headers(key=key),
    )
    assert_error(first, 503, "FILE-503")

    second = await client.post(
        "/api/v1/file-assets",
        data=_form(),
        files={"file": ("orders.csv", b"a,b\n3,4\n", "text/csv")},
        headers=headers(key=key),
    )
    assert_error(second, 409, "API-409")
