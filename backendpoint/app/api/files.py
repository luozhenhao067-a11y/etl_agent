from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from app.api.deps import (
    dependency_unavailable,
    envelope,
    get_actor,
    get_container,
    harness_error_to_api,
)
from app.container import Container
from app.core.errors import ApiError
from app.core.harness.errors import HarnessError
from app.core.idempotency import (
    remember_error,
    remember_success,
    replay_if_present,
    require_idempotency_key,
)
from app.core.masking import contains_secret_material
from app.core.security import Actor, ensure_project_access, require_role
from app.core.utils import digest_of, new_id, now_iso
from app.schemas.common import ERROR_RESPONSES, Envelope
from app.schemas.files import FileAssetData

router = APIRouter(tags=["API-07"])

_ALLOWED_FORMATS = {"csv", "excel", "json", "parquet"}
_ALLOWED_SOURCES = {"local", "object_storage"}
_EXTENSIONS = {
    "csv": {".csv"},
    "excel": {".xlsx", ".xls"},
    "json": {".json"},
    "parquet": {".parquet"},
}
_CHUNK = 1024 * 1024


@router.post(
    "/api/v1/file-assets",
    response_model=Envelope[FileAssetData],
    responses=ERROR_RESPONSES,
    status_code=201,
    summary="API-07 upload and parse a file asset",
)
async def create_file_asset(
    request: Request,
    format: str = Form(...),
    source: str = Form(...),
    project_id: str = Form(...),
    file: UploadFile | None = File(default=None),
    object_storage_path: str | None = Form(default=None),
    actor: Actor = Depends(get_actor),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    # Contract 3.5: authentication, project membership, role, then payload.
    ensure_project_access(container, actor, project_id)
    require_role(actor, {"maker"})

    if format not in _ALLOWED_FORMATS:
        raise ApiError(422, "FILE-422", "unsupported file format", {"field": "format"})
    if source not in _ALLOWED_SOURCES:
        raise ApiError(422, "FILE-422", "unsupported file source", {"field": "source"})
    if source == "local" and file is None:
        raise ApiError(422, "FILE-422", "file is required when source=local", {"field": "file"})
    if source == "object_storage":
        if object_storage_path is None or object_storage_path.strip() == "":
            raise ApiError(
                422,
                "FILE-422",
                "object_storage_path is required when source=object_storage",
                {"field": "object_storage_path"},
            )
        if contains_secret_material(object_storage_path):
            raise ApiError(422, "FILE-422", "path must not contain credentials", {"field": "object_storage_path"})

    file_digest: str | None = None
    file_size = 0
    file_name: str | None = None
    suffix = ""
    if source == "local" and file is not None:
        file_name = file.filename or "upload"
        suffix = PurePosixPath(file_name).suffix.lower()
        if suffix not in _EXTENSIONS[format]:
            raise ApiError(
                422,
                "FILE-422",
                "file extension does not match the declared format",
                {"field": "file"},
            )
        hasher = hashlib.sha256()
        while True:
            chunk = await file.read(_CHUNK)
            if not chunk:
                break
            file_size += len(chunk)
            hasher.update(chunk)
        if file_size > container.settings.max_file_size_bytes:
            raise ApiError(
                413,
                "FILE-413",
                "file exceeds the configured size limit",
                {"max_bytes": container.settings.max_file_size_bytes},
            )
        if file_size == 0:
            raise ApiError(422, "FILE-422", "file is empty", {"field": "file"})
        file_digest = hasher.hexdigest()

    key = require_idempotency_key(request)
    digest_payload = {
        "project_id": project_id,
        "format": format,
        "source": source,
        "object_storage_path": object_storage_path,
        "file_digest": file_digest,
        "file_size": file_size,
    }
    digest = digest_of(digest_payload)
    scope = f"file:upload:{actor.user_id}:{project_id}"
    replayed = replay_if_present(
        container.idempotency, scope, key, digest, "API-409", request
    )
    if replayed is not None:
        return replayed  # type: ignore[return-value]

    # file.parse is a Harness Tool Broker tool (Spec 3.6/8.4): the upload is
    # stored under the managed file storage directory and parsed by the
    # registered adapter. The stub harness never reaches this point (PDP
    # raises first), so memory mode keeps its fail-closed contract.
    asset_id = new_id("file")
    target: Path | None = None
    if source == "local" and file is not None:
        target = (Path(container.settings.file_storage_dir) / f"{asset_id}{suffix}").resolve()
    intent = {
        "tool": "file.parse",
        "actor_id": actor.user_id,
        "project_id": project_id,
        "environment": container.settings.data_environment,
        "resource_scope": {
            "file_format": format,
            "source": source,
            "file_digest": file_digest,
            "file_size": file_size,
            "file_path": str(target) if target is not None else None,
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
            "FILE-503", "harness", "file parsing dependency is unavailable"
        )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None

    if target is None:
        # object_storage source: no managed object-store adapter exists in
        # this deployment, so no path is stored and nothing is parsed.
        error = dependency_unavailable(
            "FILE-503", "object_storage", "no object storage adapter is available"
        )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        await file.seek(0)
        with target.open("wb") as sink:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                sink.write(chunk)
    except OSError:
        await file.close()
        error = ApiError(503, "FILE-503", "file storage write failed", {})
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None
    await file.close()

    def _unlink_quietly() -> None:
        try:
            target.unlink(missing_ok=True)  # type: ignore[union-attr]
        except OSError:
            pass

    try:
        result = await container.harness.execute_tool(intent, policy_decision=decision)
    except HarnessError as exc:
        _unlink_quietly()
        error = harness_error_to_api(exc)
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None
    except NotImplementedError:
        _unlink_quietly()
        error = dependency_unavailable(
            "FILE-503", "harness", "file parsing tool is not available"
        )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error from None
    if result["status"] != "SUCCEEDED":
        _unlink_quietly()
        if result.get("domain_code") == "TB-424":
            error = ApiError(422, "FILE-422", "file could not be parsed", {"field": "file"})
        else:
            error = dependency_unavailable(
                "FILE-503", "harness", "file parsing tool did not complete"
            )
        remember_error(container.idempotency, scope, key, digest, error)
        raise error

    output = result["output"] or {}
    file_schema = output.get("file_schema") or {}
    created_at = now_iso()
    container.repository.create_file_asset(
        {
            "id": asset_id,
            "project_id": project_id,
            "file_name": file_name or "upload",
            "file_path": str(target),
            "file_size": file_size,
            "file_format": format,
            "schema_json": file_schema,
            "created_at": created_at,
            "updated_at": created_at,
        }
    )
    await container.harness.append_ledger(
        {
            "project_id": project_id,
            "actor_id": actor.user_id,
            "event_type": "file.asset.uploaded",
            "resource_type": "file_asset",
            "resource_id": asset_id,
            "payload_digest": digest_of(
                {
                    "file_asset_id": asset_id,
                    "file_format": format,
                    "file_size": file_size,
                    "source": source,
                }
            ),
        }
    )
    await container.harness.append_ledger(
        {
            "project_id": project_id,
            "actor_id": actor.user_id,
            "event_type": "file.asset.parsed",
            "resource_type": "file_asset",
            "resource_id": asset_id,
            "payload_digest": digest_of(
                {
                    "file_asset_id": asset_id,
                    "field_count": len(file_schema.get("fields") or []),
                    "row_count": file_schema.get("row_count"),
                }
            ),
        }
    )

    data = FileAssetData(
        id=asset_id,
        status="parsed",
        file_format=format,
        file_schema=file_schema,
        created_at=created_at,
    )
    remember_success(container.idempotency, scope, key, digest, 201, data.model_dump(by_alias=True))
    return envelope(request, data.model_dump(by_alias=True))
