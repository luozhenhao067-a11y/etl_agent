"""Database-facing tool adapters: ``conn.test`` and ``metadata.profile``.

Spec 8.3: both tools are read-only managed probes; SecretProvider only ever
returns a reference/handle, so the handlers materialise the connection DSN
through the SecretPort at call time and never persist or log it. Only the
drivers this deployment genuinely ships (PostgreSQL via psycopg) are offered;
every other ``db_type`` fails closed instead of pretending to probe.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Callable

from app.core.harness.broker import ToolUnavailableError
from app.core.harness.errors import HarnessError
from app.core.harness.models import isoformat, utcnow
from app.core.masking import mask_structure

Clock = Callable[[], datetime]

# Driver coverage of this deployment. psycopg ships with the backend; the
# remaining contract types (mysql, oracle, doris, clickhouse, minio, rest_api)
# have no adapter here and fail closed (TB-503), never a fabricated probe.
SUPPORTED_DB_TYPES = {"postgresql"}
_POSTGRES_PREFIXES = ("postgresql://", "postgres://")

_TABLES_SQL = (
    "SELECT table_schema, table_name, table_type FROM information_schema.tables "
    "WHERE table_schema = ANY(%s) AND table_name = ANY(%s) "
    "ORDER BY table_schema, table_name"
)
_COLUMNS_SQL = (
    "SELECT table_schema, table_name, column_name, data_type, is_nullable, "
    "ordinal_position FROM information_schema.columns "
    "WHERE table_schema = ANY(%s) AND table_name = ANY(%s) "
    "ORDER BY table_schema, table_name, ordinal_position"
)


def _quote_ident(name: str) -> str:
    """Quote an SQL identifier (values come from information_schema itself)."""

    return '"' + name.replace('"', '""') + '"'


class _PostgresConnection:
    """Minimal query wrapper so the probe surface stays driver-agnostic."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def query(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        with self._raw.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [description.name for description in cursor.description or ()]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def close(self) -> None:
        self._raw.close()


def _connect_postgres(dsn: str, timeout_seconds: float, readonly: bool) -> Any:
    import psycopg

    raw = psycopg.connect(
        dsn, connect_timeout=max(1, int(timeout_seconds)), autocommit=True
    )
    if readonly:
        raw.execute("SET default_transaction_read_only = on")
    return _PostgresConnection(raw)


def _close_quietly(connection: Any) -> None:
    try:
        connection.close()
    except Exception:  # noqa: BLE001 - close must never mask the probe result
        pass


def _classify_error(exc: BaseException) -> str:
    """A stable, de-identified failure code (contract: 失败原因脱敏).

    The exception text may contain host, DSN or credential fragments, so only
    the exception class drives the classification.
    """

    name = type(exc).__name__
    if "InvalidPassword" in name or "InsufficientPrivilege" in name:
        return "AUTH_FAILED"
    if "Timeout" in name:
        return "TIMEOUT"
    return "CONNECTION_FAILED"


async def _materialize_dsn(
    secret: Any, connection_id: str, intent: dict[str, Any], db_type: Any
) -> str:
    if db_type not in SUPPORTED_DB_TYPES:
        raise ToolUnavailableError(
            f"no database driver adapter is available for {db_type}"
        )
    try:
        dsn = await secret.materialize(
            f"secret://connections/{connection_id}",
            {
                "connection_id": connection_id,
                "env": intent.get("environment") or intent.get("env"),
            },
        )
    except NotImplementedError as exc:
        raise ToolUnavailableError("secret provider is unavailable") from exc
    if not isinstance(dsn, str) or not dsn.lower().startswith(_POSTGRES_PREFIXES):
        raise ToolUnavailableError(
            "the materialized secret is not a DSN this driver can use"
        )
    return dsn


def make_conn_test_handler(
    *, secret: Any, connector: Callable[[str, float, bool], Any] | None = None, clock: Clock = utcnow
) -> Any:
    """``conn.test``: real connection attempt, latency and de-identified code."""

    connect = connector or _connect_postgres

    async def handler(intent: dict[str, Any]) -> dict[str, Any]:
        scope = intent["resource_scope"]
        connection_id = scope["connection_id"]
        timeout_seconds = min(float(scope.get("timeout_ms") or 5000), 600000) / 1000
        dsn = await _materialize_dsn(secret, connection_id, intent, scope.get("db_type"))

        started = time.perf_counter()
        try:
            connection = await asyncio.to_thread(connect, dsn, timeout_seconds, False)
        except Exception as exc:  # noqa: BLE001 - classified, never leaked
            latency_ms = int((time.perf_counter() - started) * 1000)
            return {
                "success": False,
                "latency_ms": latency_ms,
                "error_code": _classify_error(exc),
            }
        latency_ms = int((time.perf_counter() - started) * 1000)
        await asyncio.to_thread(_close_quietly, connection)
        return {"success": True, "latency_ms": latency_ms, "error_code": None}

    return handler


def make_metadata_profile_handler(
    *, secret: Any, connector: Callable[[str, float, bool], Any] | None = None, clock: Clock = utcnow
) -> Any:
    """``metadata.profile``: read-only information_schema probe + masked samples."""

    connect = connector or _connect_postgres

    async def handler(intent: dict[str, Any]) -> dict[str, Any]:
        scope = intent["resource_scope"]
        profile = scope.get("profile") or {}
        if profile.get("readonly") is not True:
            raise HarnessError(422, "META-422", "readonly must be true")
        connection_id = scope["connection_id"]
        schemas = list(profile.get("schemas") or [])
        tables = list(profile.get("tables") or [])
        sample_rows = max(0, int(profile.get("sample_rows") or 0))
        dsn = await _materialize_dsn(secret, connection_id, intent, scope.get("db_type"))

        try:
            connection = await asyncio.to_thread(connect, dsn, 30.0, True)
        except Exception as exc:  # noqa: BLE001 - classified, never leaked
            return {
                "profile_status": "failed",
                "sampled_at": isoformat(clock()),
                "tables": [],
                "columns": [],
                "error_code": _classify_error(exc),
            }

        try:
            table_rows = await asyncio.to_thread(
                connection.query, _TABLES_SQL, [schemas, tables]
            )
            column_rows = await asyncio.to_thread(
                connection.query, _COLUMNS_SQL, [schemas, tables]
            )
            masked_samples: list[dict[str, Any]] = []
            if sample_rows > 0:
                for table in table_rows:
                    sample_sql = (
                        f"SELECT * FROM {_quote_ident(table['table_schema'])}"
                        f".{_quote_ident(table['table_name'])} LIMIT %s"
                    )
                    rows = await asyncio.to_thread(
                        connection.query, sample_sql, [sample_rows]
                    )
                    masked_samples.extend(mask_structure(row) for row in rows)
        finally:
            await asyncio.to_thread(_close_quietly, connection)

        return {
            "profile_status": "completed",
            "sampled_at": isoformat(clock()),
            "tables": table_rows,
            "columns": column_rows,
            "masked_samples": masked_samples or None,
        }

    return handler


__all__ = [
    "SUPPORTED_DB_TYPES",
    "make_conn_test_handler",
    "make_metadata_profile_handler",
]
