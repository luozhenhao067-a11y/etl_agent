"""Small shared helpers."""

from __future__ import annotations

import hashlib
import itertools
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

CST = timezone(timedelta(hours=8))
ZERO_HASH = "0" * 64


def now() -> datetime:
    return datetime.now(CST)


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=CST)
    else:
        # Normalise every aware value to the project's CST offset so DB
        # round-trips return the same string the writer sent, regardless of
        # the server session timezone.
        value = value.astimezone(CST)
    return value.isoformat(timespec="seconds")


_ID_SEQ = itertools.count()


def new_id(prefix: str) -> str:
    # Nanosecond timestamp plus a process-wide sequence: lexicographic order
    # equals creation order, so "(created_at, id)" is a stable total order
    # even for rows created within the same second — required by the audit
    # hash chain once rows live in PostgreSQL instead of ordered dicts.
    return f"{prefix}_{time.time_ns():019d}{next(_ID_SEQ):03d}"


def new_correlation_id() -> str:
    return f"corr_{uuid.uuid4().hex[:16]}"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def digest_of(value: Any) -> str:
    return sha256_hex(canonical_json(value))
