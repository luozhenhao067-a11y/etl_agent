from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import ValidationError

from app.api.deps import (
    dependency_unavailable,
    envelope,
    get_actor,
    get_connection_or_404,
    get_container,
    harness_error_to_api,
)
from app.container import Container
from app.core.errors import ApiError
from app.core.harness.errors import HarnessError
from app.core.idempotency import (
    body_digest,
    remember_error,
    remember_success,
    replay_if_present,
    require_idempotency_key,
)
from app.core.masking import mask_host, mask_structure, sanitize_log_line
from app.core.security import Actor, ensure_project_access, require_role
from app.core.utils import digest_of, new_id, now_iso
from app.schemas.common import ERROR_RESPONSES, Envelope
from app.schemas.connections import (
    ConnectionCreateData,
    ConnectionCreateRequest,
    ConnectionItem,
    ConnectionListData,
    ConnectionTestData,
    ConnectionTestRequest,
    ConnectionUpdateData,
    ConnectionUpdateRequest,
    Environment,
    ProfileData,
    ProfileRequest,
)

router = APIRouter(tags=["API-02..API-06"])

_DB_TYPES = {"mysql", "postgresql", "oracle", "doris", "clickhouse"}
_TARGET_TYPES = {"doris"}


def _present(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "type": row["type"],
        "env": row["env"],
        "status": row["status"],
        "host_masked": sanitize_log_line(row["host_masked"]),
        "source_target": row["source_target"],
        "last_tested_at": row.get("last_tested_at"),
        "secret_state": row["secret_state"],
    }


def _connection_names(container: Container, project_id: str, exclude_id: str | None = None) -> set[str]:
    return {
        row["name"].casefold()
        for row in container.state.connections.values()
        if row["project_id"] == project_id and row["id"] != exclude_id
    }


@router.get(
    "/api/v1/projects/{project_id}/connections",
    response_model=Envelope[ConnectionListData],
    responses=ERROR_RESPONSES,
    summary="API-02 list project connections",
)
async def list_connections(
    request: Request,
    project_id: str,
    connection_type: str | None = Query(default=None, alias="type"),
    env: Environment | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1),
    actor: Actor = Depends(get_actor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    ensure_project_access(container, actor, project_id)
    # Contract API-02 allows only the five query parameters listed in its
    # whitelist. FastAPI ignores unknown query parameters by default, so reject
    # them explicitly instead of silently accepting a non-contract filter.
    allowed_query = {"type", "env", "status", "page", "page_size"}
    unsupported = sorted(set(request.query_params.keys()) - allowed_query)
    if unsupported:
        raise ApiError(
            400,
            "API-400",
            "unsupported query parameter",
            {"field": unsupported[0]},
        )
    if page_size > container.settings.page_size_max:
        raise ApiError(
            400,
            "API-400",
            "page_size exceeds the configured maximum",
            {"field": "page_size", "max": container.settings.page_size_max},
        )

    rows = [
        row
        for row in container.state.connections.values()
        if row["project_id"] == project_id
        and (connection_type is None or row["type"] == connection_type)
        and (env is None or row["env"] == env)
        and (status is None or row["status"] == status)
    ]
    rows.sort(key=lambda item: item["id"])
    total = len(rows)
    start = (page - 1) * page_size
    items = [_present(row) for row in rows[start : start + page_size]]
    data = ConnectionListData(
        items=[ConnectionItem(**item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )
    return envelope(request, data.model_dump())


@router.post(
    "/api/v1/connections",
    response_model=Envelope[ConnectionCreateData],
    responses=ERROR_RESPONSES,
    status_code=201,
    summary="API-03 create connection",
)
async def create_connection(
    request: Request,
    payload: ConnectionCreateRequest,
    response: Response,
    actor: Actor = Depends(get_actor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    # Contract 3.5: authentication, project membership, role, then payload.
    ensure_project_access(container, actor, actor.project_id or "")
    require_role(actor, {"maker"})
    project_id = actor.project_id or ""
    key = require_idempotency_key(request)
    digest = body_digest(payload.model_dump())

    replayed = replay_if_present(
        container.idempotency,
        f"conn:create:{actor.user_id}:{project_id}",
        key,
        digest,
        "CONN-409",
        request,
    )
    if replayed is not None:
        response.status_code = replayed.status_code
        return replayed  # type: ignore[return-value]

    if payload.name.casefold() in _connection_names(container, project_id):
        raise ApiError(409, "CONN-409", "connection name already exists", {"field": "name"})

    now = now_iso()
    connection_id = new_id("conn")
    secret_digest = digest_of(payload.secret_ref) if payload.secret_ref else None
    row = {
        "id": connection_id,
        "project_id": project_id,
        "name": payload.name,
        "type": payload.type,
        "env": payload.env,
        "status": "active",
        "host_masked": mask_host(payload.host) if payload.host else "***",
        "source_target": "target" if payload.type in _TARGET_TYPES else "source",
        "last_tested_at": None,
        "secret_state": "configured" if payload.secret_ref else "not_configured",
        "secret_ref_digest": secret_digest,
        "port": payload.port,
        "database": payload.database,
        "readonly": payload.readonly,
        "tls": mask_structure(payload.tls) if payload.tls else None,
        "file_source": mask_structure(payload.file_source) if payload.file_source else None,
        "created_at": now,
        "updated_at": now,
    }
    container.state.connections[connection_id] = row

    await container.record_audit(
        project_id=project_id,
        actor_id=actor.user_id,
        event_type="connection.created",
        resource_type="connection",
        resource_id=connection_id,
        payload={
            "connection_id": connection_id,
            "type": payload.type,
            "env": payload.env,
            "secret_ref_digest": secret_digest,
        },
    )

    # Contract 9.1: binding a Secret reference is its own auditable step. It
    # only fires when a secret_ref was actually provided — a connection
    # created without one never binds anything.
    if secret_digest is not None:
        await container.record_audit(
            project_id=project_id,
            actor_id=actor.user_id,
            event_type="secret.ref.bound",
            resource_type="connection",
            resource_id=connection_id,
            payload={
                "connection_id": connection_id,
                "type": payload.type,
                "env": payload.env,
                "secret_ref_digest": secret_digest,
            },
        )

    data = {
        "id": connection_id,
        "status": row["status"],
        "secret_state": row["secret_state"],
        "created_at": now,
    }
    remember_success(
        container.idempotency,
        f"conn:create:{actor.user_id}:{project_id}",
        key,
        digest,
        201,
        data,
    )
    return envelope(request, data)


@router.put(
    "/api/v1/connections/{id}",
    response_model=Envelope[ConnectionUpdateData],
    responses=ERROR_RESPONSES,
    summary="API-04 update connection",
)
async def update_connection(
    request: Request,
    id: str,
    payload: ConnectionUpdateRequest,
    response: Response,
    actor: Actor = Depends(get_actor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    ensure_project_access(container, actor, actor.project_id or "")
    require_role(actor, {"maker"})
    connection_id = id
    row = get_connection_or_404(container, actor, connection_id)
    key = require_idempotency_key(request)
    digest = body_digest(payload.model_dump(exclude_unset=True))
    scope = f"conn:update:{actor.user_id}:{connection_id}"

    replayed = replay_if_present(
        container.idempotency, scope, key, digest, "CONN-409", request
    )
    if replayed is not None:
        response.status_code = replayed.status_code
        return replayed  # type: ignore[return-value]

    provided = payload.model_dump(exclude_unset=True)
    if "name" in provided and provided["name"].casefold() in _connection_names(
        container, row["project_id"], exclude_id=connection_id
    ):
        raise ApiError(409, "CONN-409", "connection name already exists", {"field": "name"})

    merged = {
        "name": provided.get("name", row["name"]),
        "type": provided.get("type", row["type"]),
        "env": provided.get("env", row["env"]),
        "host": row.get("host_masked") if "host" not in provided else provided["host"],
        "port": provided.get("port", row.get("port")),
        "database": provided.get("database", row.get("database")),
        "username": provided.get("username", row.get("username")),
        "secret_ref": provided.get("secret_ref", row.get("secret_ref_digest")),
        "readonly": provided.get("readonly", row.get("readonly", True)),
        "tls": provided.get("tls", row.get("tls")),
        "file_source": provided.get("file_source", row.get("file_source")),
    }
    try:
        ConnectionCreateRequest(**merged)
    except ValidationError:
        raise ApiError(
            422,
            "CONN-422",
            "invalid connection parameter",
            {"fields": {"request": "invalid"}},
        ) from None

    if "name" in provided:
        row["name"] = provided["name"]
    if "type" in provided:
        row["type"] = provided["type"]
    if "env" in provided:
        row["env"] = provided["env"]
    if "host" in provided:
        row["host_masked"] = mask_host(provided["host"]) if provided["host"] else "***"
    if "port" in provided:
        row["port"] = provided["port"]
    if "database" in provided:
        row["database"] = provided["database"]
    if "readonly" in provided:
        row["readonly"] = provided["readonly"]
    if "tls" in provided:
        row["tls"] = mask_structure(provided["tls"]) if provided["tls"] else None
    if "file_source" in provided:
        row["file_source"] = (
            mask_structure(provided["file_source"]) if provided["file_source"] else None
        )
    if "secret_ref" in provided:
        row["secret_ref_digest"] = digest_of(provided["secret_ref"]) if provided["secret_ref"] else None
        row["secret_state"] = "configured" if provided["secret_ref"] else "not_configured"
    row["updated_at"] = now_iso()

    await container.record_audit(
        project_id=row["project_id"],
        actor_id=actor.user_id,
        event_type="connection.updated",
        resource_type="connection",
        resource_id=connection_id,
        payload={
            "connection_id": connection_id,
            "changed_fields": sorted(provided.keys()),
            "change_digest": digest,
        },
    )

    data = {
        "id": connection_id,
        "status": row["status"],
        "secret_state": row["secret_state"],
        "updated_at": row["updated_at"],
    }
    remember_success(container.idempotency, scope, key, digest, 200, data)
    return envelope(request, data)


@router.post(
    "/api/v1/connections/{id}/tests",
    response_model=Envelope[ConnectionTestData],
    responses=ERROR_RESPONSES,
    summary="API-05 test connection",
)
async def test_connection(
    request: Request,
    id: str,
    payload: ConnectionTestRequest | None = None,
    actor: Actor = Depends(get_actor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    ensure_project_access(container, actor, actor.project_id or "")
    require_role(actor, {"maker"})
    connection_id = id
    row = get_connection_or_404(container, actor, connection_id)
    if payload is not None and payload.timeout_ms is not None:
        if payload.timeout_ms > 600000:
            raise ApiError(
                422,
                "CONN-422",
                "timeout_ms exceeds the supported maximum",
                {"field": "timeout_ms"},
            )

    # conn.test is a Harness Tool Broker tool (Spec 3.6): the PDP decision is
    # bound to this exact intent, then the registered adapter performs the
    # real probe (SecretPort materialisation + driver connect). No fake
    # latency, success flag or test timestamp is ever produced.
    intent = {
        "tool": "conn.test",
        "actor_id": actor.user_id,
        "project_id": row["project_id"],
        "env": row["env"],
        "resource_scope": {
            "connection_id": connection_id,
            "db_type": row["type"],
            "timeout_ms": payload.timeout_ms if payload is not None else None,
        },
    }
    try:
        decision = await container.harness.pdp_decide(intent)
    except HarnessError as exc:
        raise harness_error_to_api(exc) from None
    except NotImplementedError:
        raise dependency_unavailable(
            "CONN-503", "harness", "connection test dependency is unavailable"
        ) from None

    try:
        result = await container.harness.execute_tool(intent, policy_decision=decision)
    except HarnessError as exc:
        raise harness_error_to_api(exc) from None
    except NotImplementedError:
        raise dependency_unavailable(
            "CONN-503", "harness", "connection test tool is not available"
        ) from None
    if result["status"] != "SUCCEEDED":
        raise dependency_unavailable(
            "CONN-503", "harness", "connection test tool did not complete"
        )

    output = result["output"] or {}
    tested_at = now_iso()
    row["last_tested_at"] = tested_at
    data = ConnectionTestData(
        success=bool(output.get("success")),
        latency_ms=output.get("latency_ms"),
        error_code=output.get("error_code"),
        tested_at=tested_at,
    )
    await container.harness.append_ledger(
        {
            "project_id": row["project_id"],
            "actor_id": actor.user_id,
            "event_type": "connection.tested",
            "resource_type": "connection",
            "resource_id": connection_id,
            "payload_digest": digest_of(
                {
                    "connection_id": connection_id,
                    "success": data.success,
                    "error_code": data.error_code,
                }
            ),
        }
    )
    return envelope(request, data.model_dump())


@router.post(
    "/api/v1/connections/{id}/profiles",
    response_model=Envelope[ProfileData],
    responses=ERROR_RESPONSES,
    summary="API-06 request metadata profile",
)
async def profile_connection(
    request: Request,
    id: str,
    payload: ProfileRequest,
    actor: Actor = Depends(get_actor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    ensure_project_access(container, actor, actor.project_id or "")
    require_role(actor, {"maker"}, code="META-403")
    connection_id = id
    connection = get_connection_or_404(container, actor, connection_id)
    key = require_idempotency_key(request)
    digest = body_digest(payload.model_dump())
    scope = f"meta:profile:{actor.user_id}:{connection_id}"
    replay_if_present(
        container.idempotency,
        scope,
        key,
        digest,
        "API-409",
        request,
    )

    # metadata.profile is a Harness Tool Broker tool (Spec 3.6/8.3): the PDP
    # decision is bound to this exact intent, then the registered adapter
    # performs the read-only information_schema probe with masked samples.
    intent = {
        "tool": "metadata.profile",
        "actor_id": actor.user_id,
        "project_id": connection["project_id"],
        "env": connection["env"],
        "resource_scope": {
            "connection_id": connection_id,
            "db_type": connection["type"],
            "profile": payload.model_dump(),
        },
    }
    try:
        decision = await container.harness.pdp_decide(intent)
    except HarnessError as exc:
        error = harness_error_to_api(exc)
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None
    except NotImplementedError:
        error = dependency_unavailable(
            "META-503", "harness", "metadata profile dependency is unavailable"
        )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None

    await container.harness.append_ledger(
        {
            "project_id": connection["project_id"],
            "actor_id": actor.user_id,
            "event_type": "metadata.profile.requested",
            "resource_type": "connection",
            "resource_id": connection_id,
            "payload_digest": digest_of(
                {
                    "connection_id": connection_id,
                    "schemas": list(payload.schemas),
                    "tables": list(payload.tables),
                    "sample_rows": payload.sample_rows,
                }
            ),
        }
    )

    try:
        result = await container.harness.execute_tool(intent, policy_decision=decision)
    except HarnessError as exc:
        error = harness_error_to_api(exc)
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None
    except NotImplementedError:
        error = dependency_unavailable(
            "META-503", "harness", "metadata profile tool is not available"
        )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None
    if result["status"] != "SUCCEEDED":
        error = dependency_unavailable(
            "META-503", "harness", "metadata profile tool did not complete"
        )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error

    output = result["output"] or {}
    data = ProfileData(
        profile_status=output.get("profile_status") or "failed",
        sampled_at=output.get("sampled_at"),
        tables=output.get("tables") or [],
        columns=output.get("columns") or [],
        masked_samples=output.get("masked_samples"),
    )
    container.state.profiles[connection_id] = data.model_dump()
    await container.harness.append_ledger(
        {
            "project_id": connection["project_id"],
            "actor_id": actor.user_id,
            "event_type": "metadata.profile.completed",
            "resource_type": "connection",
            "resource_id": connection_id,
            "payload_digest": digest_of(
                {
                    "connection_id": connection_id,
                    "table_count": len(data.tables),
                    "column_count": len(data.columns),
                    "profile_status": data.profile_status,
                }
            ),
        }
    )
    remember_success(container.idempotency, scope, key, digest, 200, data.model_dump())
    return envelope(request, data.model_dump())
