"""Mock authentication and authorisation.

The contract leaves the authentication mechanism pending (P-26). This delivery
therefore accepts only synthetic demo users: ``Authorization: Bearer
<user_demo_xxx>``. No JWT is minted, no password is checked, and no external
identity provider is called. Role switching means switching demo user.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.core.errors import ApiError

AUTH_HEADER = "Authorization"


@dataclass(frozen=True)
class Actor:
    user_id: str
    username: str
    display_name: str
    role: str
    project_id: str | None
    role_slots: tuple[str, ...]

    @property
    def is_project_member(self) -> bool:
        return self.project_id is not None


def _unauthorized(reason: str) -> ApiError:
    return ApiError(401, "AUTH-401", "authentication required", {"reason": reason})


def authenticate(request: Request, container) -> Actor:
    raw = request.headers.get(AUTH_HEADER)
    if raw is None or raw.strip() == "":
        raise _unauthorized("missing_credentials")
    parts = raw.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise _unauthorized("invalid_credentials")
    token = parts[1].strip()
    if token == "":
        raise _unauthorized("invalid_credentials")
    if token.startswith("mock:"):
        token = token[len("mock:") :]
    elif token.startswith("mock_"):
        token = token[len("mock_") :]

    repo = container.repository
    user = repo.get_user(token)
    if user is None:
        user = repo.get_user_by_username(token)
    if user is None or user.get("status") != "active":
        raise _unauthorized("invalid_credentials")

    project_id = container.settings.default_project_id
    membership = repo.get_membership(project_id, user["id"])
    if membership is None:
        return Actor(
            user_id=user["id"],
            username=user["username"],
            display_name=user.get("display_name") or user["username"],
            role="none",
            project_id=None,
            role_slots=(),
        )

    grants = repo.list_role_grants(project_id, user["id"])
    return Actor(
        user_id=user["id"],
        username=user["username"],
        display_name=user.get("display_name") or user["username"],
        role=membership["role"],
        project_id=project_id,
        role_slots=tuple(sorted(grant["role_slot"] for grant in grants)),
    )


def ensure_project_access(container, actor: Actor, project_id: str) -> None:
    if not actor.is_project_member:
        raise ApiError(
            403,
            "AUTH-403",
            "project access denied",
            {"reason": "not_project_member"},
        )
    if container.repository.get_project(project_id) is None:
        raise ApiError(404, "API-404", "project not found", {})
    if actor.project_id != project_id:
        raise ApiError(
            403,
            "AUTH-403",
            "project access denied",
            {"reason": "cross_project_access"},
        )


def require_role(actor: Actor, allowed: set[str], code: str = "ROLE-403") -> None:
    if actor.role not in allowed:
        raise ApiError(403, code, "role is not allowed to perform this action", {"reason": "role_not_allowed"})


def require_maker(actor: Actor, code: str = "ROLE-403") -> None:
    require_role(actor, {"maker"}, code)


def require_ops(actor: Actor, code: str = "OPS-403") -> None:
    require_role(actor, {"ops"}, code)


def require_checker2(actor: Actor, code: str = "BENCH-403") -> None:
    require_role(actor, {"checker2"}, code)
