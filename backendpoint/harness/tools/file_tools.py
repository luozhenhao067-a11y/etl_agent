"""``file.parse`` tool adapter (Spec 8.4): parse a stored upload's schema.

The upload path (API-07) stores the bytes under the managed file storage
directory and hands the absolute path to this tool through the intent. Only
the parsers this deployment genuinely ships are offered (stdlib csv/json);
excel/parquet fail closed until a real parser adapter exists.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app.core.harness.broker import ToolDependencyError, ToolUnavailableError
from app.core.harness.models import utcnow

Clock = Callable[[], datetime]

_SUPPORTED_FORMATS = {"csv", "json"}
_INFER_LIMIT = 100


def _field_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _parse_csv(data: bytes) -> dict[str, Any]:
    text = data.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or not any(cell.strip() for cell in rows[0]):
        raise ValueError("csv has no header row")
    header = rows[0]
    # Duplicate column names would collapse in downstream mappings.
    seen: dict[str, int] = {}
    names = []
    for name in header:
        count = seen.get(name, 0)
        names.append(name if count == 0 else f"{name}_{count + 1}")
        seen[name] = count + 1
    sample = next(
        (row for row in rows[1:_INFER_LIMIT + 1] if any(cell.strip() for cell in row)),
        [],
    )
    fields = [
        {"name": name, "type": _field_type(_coerce(cell))}
        for name, cell in zip(names, sample)
    ]
    # Pad fields the sample row did not cover.
    fields += [{"name": name, "type": "string"} for name in names[len(fields):]]
    return {"fields": fields, "row_count": max(len(rows) - 1, 0)}


def _coerce(cell: str) -> Any:
    text = cell.strip()
    for caster in (int, float):
        try:
            return caster(text)
        except ValueError:
            continue
    return text


def _parse_json(data: bytes) -> dict[str, Any]:
    obj = json.loads(data.decode("utf-8-sig"))
    if isinstance(obj, list):
        records = [row for row in obj if isinstance(row, dict)]
        if not records:
            raise ValueError("json array carries no objects")
        fields: dict[str, str] = {}
        for record in records[:_INFER_LIMIT]:
            for key, value in record.items():
                fields.setdefault(str(key), _field_type(value))
        return {"fields": [{"name": k, "type": t} for k, t in fields.items()], "row_count": len(obj)}
    if isinstance(obj, dict):
        return {
            "fields": [{"name": str(k), "type": _field_type(v)} for k, v in obj.items()],
            "row_count": 1,
        }
    raise ValueError("json must be an object or an array of objects")


def make_file_parse_handler(*, clock: Clock = utcnow) -> Any:
    """``file.parse``: infer the field schema of the stored file."""

    async def handler(intent: dict[str, Any]) -> dict[str, Any]:
        scope = intent["resource_scope"]
        file_format = scope.get("file_format")
        if file_format not in _SUPPORTED_FORMATS:
            raise ToolUnavailableError(
                f"no {file_format} parser adapter is available"
            )
        try:
            data = Path(scope["file_path"]).read_bytes()
        except OSError as exc:
            raise ToolDependencyError("stored file could not be read") from exc
        try:
            if file_format == "csv":
                schema = _parse_csv(data)
            else:
                schema = _parse_json(data)
        except (ValueError, csv.Error, UnicodeDecodeError) as exc:
            raise ToolDependencyError("file could not be parsed") from exc
        return {"file_schema": schema}

    return handler


__all__ = ["make_file_parse_handler"]
