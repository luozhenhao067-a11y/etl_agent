"""Shared dependencies and access helpers for API routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Request

from app.container import Container
from app.core.errors import ApiError
from app.core.harness.errors import HarnessError
from app.core.security import Actor, authenticate, ensure_project_access, require_role


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_actor(
    request: Request,
    container: Container = Depends(get_container),
) -> Actor:
    return authenticate(request, container)


def get_current_user(actor: Actor = Depends(get_actor)) -> Actor:
    """Contract-facing name for the switchable mock current-user dependency."""
    return actor


def correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", "")


def envelope(request: Request, data: Any) -> dict[str, Any]:
    return {"data": data, "correlation_id": correlation_id(request)}


def dependency_unavailable(code: str, dependency: str, message: str) -> ApiError:
    return ApiError(
        503,
        code,
        message,
        {"dependency": dependency, "status": "not_implemented"},
    )


def harness_error_to_api(exc: HarnessError) -> ApiError:
    """Map a kernel HarnessError (Spec 3.10) onto the public error envelope."""
    return ApiError(exc.status_code, exc.error_code, exc.message, dict(exc.details))


def get_connection_or_404(container: Container, actor: Actor, connection_id: str) -> dict[str, Any]:
    row = container.state.connections.get(connection_id)
    if row is None:
        raise ApiError(404, "API-404", "connection not found", {})
    # A resource in another project is an authorisation failure, not a missing
    # resource. Contract 3.2 requires AUTH-403 for cross-project access.
    ensure_project_access(container, actor, row["project_id"])
    return row


def get_version_or_404(container: Container, actor: Actor, version_id: str) -> tuple[dict[str, Any], str]:
    repo = container.repository
    version = repo.get_version(version_id)
    if version is None:
        raise ApiError(404, "API-404", "version not found", {})
    pipeline = repo.get_pipeline(version["pipeline_id"])
    if pipeline is None:
        raise ApiError(404, "API-404", "version not found", {})
    project_id = pipeline["project_id"]
    ensure_project_access(container, actor, project_id)
    return version, project_id


def get_execution_run_or_404(
    container: Container, actor: Actor, run_id: str
) -> tuple[dict[str, Any], dict[str, Any], str]:
    repo = container.repository
    run = repo.get_execution_run(run_id)
    if run is None:
        raise ApiError(404, "API-404", "execution run not found", {})
    version = repo.get_version(run["version_id"])
    if version is None:
        raise ApiError(404, "API-404", "execution run not found", {})
    pipeline = repo.get_pipeline(version["pipeline_id"])
    if pipeline is None:
        raise ApiError(404, "API-404", "execution run not found", {})
    project_id = pipeline["project_id"]
    ensure_project_access(container, actor, project_id)
    return run, version, project_id


def get_preparation_or_404(
    container: Container, actor: Actor, preparation_id: str
) -> dict[str, Any]:
    preparation = container.state.preparations.get(preparation_id)
    if preparation is None:
        raise ApiError(404, "API-404", "preparation not found", {})
    ensure_project_access(container, actor, preparation["project_id"])
    return preparation


def require_maker_or(actor: Actor, code: str) -> None:
    require_role(actor, {"maker"}, code)
