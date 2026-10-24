"""Shared Harness vocabulary and validation.

P0-P3 business semantics and per-level approval differences are still pending
(P-13). The table below is therefore an explicit provisional policy input, not
a claim that those business rules are frozen. It never lowers the four-eye
minimum for execution-class tools.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.core.masking import contains_secret_material

Clock = Callable[[], datetime]
ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

ENVIRONMENTS = {"prod", "preprod", "test"}
RISK_LEVELS = {"P0", "P1", "P2", "P3"}
DEFAULT_POLICY_VERSION = "pending-p13.v1"
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")

CAPABILITY_CONSUMED = "CONSUMED"
CAPABILITY_EXPIRED = "EXPIRED"
CAPABILITY_ISSUED = "ISSUED"
CAPABILITY_PRESENTED = "PRESENTED"
CAPABILITY_REJECTED = "REJECTED"

OUTBOX_PENDING = "PENDING"
OUTBOX_PUBLISHED = "PUBLISHED"
OUTBOX_RETRYING = "RETRYING"
OUTBOX_CONSUMED = "CONSUMED"
OUTBOX_DEAD_LETTER = "DEAD_LETTER"

REPLAY_UNSEEN = "UNSEEN"
REPLAY_RESERVED = "RESERVED"
REPLAY_CONSUMED = "CONSUMED"
REPLAY_REJECTED = "REJECTED"
REPLAY_EXPIRED = "EXPIRED"

_RESERVED_SECRET_KEYS = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "secret_value",
    "token",
    "access_token",
    "refresh_token",
    "capability",
    "capability_token",
    "authorization",
    "private_key",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def epoch_seconds(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.astimezone(timezone.utc).timestamp())


def is_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(DIGEST_RE.fullmatch(value))


@dataclass(frozen=True)
class ToolSpec:
    name: str
    side_effect: bool
    requires_capability: bool
    replay_required: bool
    risk_level: str
    required_slots: tuple[str, ...]


# Provisional policy input for the kernel. P-13 remains open; callers may
# replace this table when the business policy is confirmed. Execution-class
# tools always carry both approval slots.
DEFAULT_TOOL_SPECS: dict[str, ToolSpec] = {
    "conn.test": ToolSpec("conn.test", False, False, False, "P3", ()),
    "metadata.profile": ToolSpec("metadata.profile", False, False, False, "P3", ()),
    "file.parse": ToolSpec("file.parse", False, False, False, "P3", ()),
    "benchmark.run": ToolSpec("benchmark.run", True, False, True, "P2", ()),
    "etl.execute": ToolSpec(
        "etl.execute", True, True, True, "P1", ("data_checker", "security_checker")
    ),
    "table.swap": ToolSpec(
        "table.swap", True, True, True, "P0", ("data_checker", "security_checker")
    ),
    "run.cancel": ToolSpec("run.cancel", True, False, True, "P1", ()),
    "shadow.rollback": ToolSpec("shadow.rollback", True, False, True, "P1", ()),
    "resource.cleanup": ToolSpec("resource.cleanup", True, False, True, "P2", ()),
    "secret.materialize": ToolSpec(
        "secret.materialize",
        True,
        True,
        True,
        "P0",
        ("data_checker", "security_checker"),
    ),
}


def tool_specs() -> dict[str, ToolSpec]:
    return dict(DEFAULT_TOOL_SPECS)


def require_tool_name(tool: Any) -> str:
    if not isinstance(tool, str) or not TOOL_NAME_RE.fullmatch(tool):
        raise ValueError("invalid tool name")
    return tool


def require_nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def assert_no_secret_material(value: Any, path: str = "intent") -> None:
    """Reject obvious plaintext credential material in an internal request.

    ``secret_ref`` is allowed because resource scopes may contain references;
    the check targets values and credential-bearing keys, not reference names.
    """

    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in _RESERVED_SECRET_KEYS:
                raise ValueError(f"{path}.{key_text} must not contain secret material")
            assert_no_secret_material(item, f"{path}.{key_text}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            assert_no_secret_material(item, f"{path}[{index}]")
        return
    if isinstance(value, str) and contains_secret_material(value):
        raise ValueError(f"{path} must not contain secret material")


def safe_digest(value: Any, field: str) -> str:
    if not is_digest(value):
        raise ValueError(f"{field} must be a 64-character lowercase SHA256")
    return value


def result_status(value: Any) -> bool:
    return value in {"SUCCEEDED", "FAILED", "REJECTED", "UNKNOWN"}
