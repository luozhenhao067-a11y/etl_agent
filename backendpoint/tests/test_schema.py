from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.models.tables import Base

import harness.models  # noqa: F401  (registers the migration-0002 tables)

BACKEND_ROOT = Path(__file__).resolve().parents[1]

BUSINESS_TABLES = {
    "users",
    "projects",
    "project_memberships",
    "project_role_grants",
    "pipelines",
    "pipeline_versions",
    "pipeline_artifacts",
    "agent_runs",
    "approval_requests",
    "execution_runs",
    "file_assets",
    "preparations",
    "runtime_supervision_snapshots",
    "audit_events",
}

# Migration 0002 (P-06/P-09 confirmed 2026-10-24): Transactional Outbox
# carrier and Evidence Ledger checkpoints.
HARNESS_TABLES = {
    "outbox_events",
    "ledger_checkpoints",
}


def test_models_declare_the_specified_and_harness_tables():
    assert set(Base.metadata.tables) == BUSINESS_TABLES | HARNESS_TABLES


def _migrate_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Config, str]:
    database_path = tmp_path / "schema.db"
    url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(config, "head")
    return config, url


def _seed(engine) -> None:
    now = "2026-10-23T00:00:00+00:00"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users VALUES "
                "('u1','u1','User','u@example.com','active',:now,:now)"
            ),
            {"now": now},
        )
        connection.execute(
            text("INSERT INTO projects VALUES ('p1','P','P',NULL,:now,:now)"),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO pipelines VALUES "
                "('pl1','p1','P','c',NULL,'active',:now,:now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO pipeline_versions VALUES "
                "('v1','pl1',1,NULL,'hocon',:digest,1,:now,:now)"
            ),
            {"digest": "a" * 64, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO audit_events "
                "(id, project_id, actor_id, event_type, resource_type, "
                "resource_id, payload_digest, prev_event_hash, event_hash, "
                "created_at) VALUES "
                "('e1','p1','u1','connection.created','connection','c1',"
                ":payload,:prev,:event,:now)"
            ),
            {
                "payload": "b" * 64,
                "prev": "0" * 64,
                "event": "c" * 64,
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO approval_requests VALUES "
                "('a1','prep1','v1','data_checker','approved','approved','u1',"
                ":now,:now,:now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO execution_runs VALUES "
                "('r1','v1','prep1',NULL,'succeeded',NULL,0,0,0,0,NULL,NULL,"
                ":now,:now)"
            ),
            {"now": now},
        )


def test_migration_creates_thirteen_tables_triggers_and_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _, url = _migrate_sqlite(tmp_path, monkeypatch)
    engine = create_engine(url)

    table_names = set(inspect(engine).get_table_names())
    assert table_names - {"alembic_version"} == BUSINESS_TABLES | HARNESS_TABLES

    with engine.connect() as connection:
        triggers = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='trigger'")
            ).scalars()
        )
    assert triggers == {
        "trg_audit_events_no_update",
        "trg_audit_events_no_delete",
        "trg_pipeline_versions_immutable",
        "trg_pipeline_versions_no_delete",
        "trg_approval_requests_decision",
    }

    _seed(engine)

    blocked = [
        "UPDATE audit_events SET event_type='tampered' WHERE id='e1'",
        "DELETE FROM audit_events WHERE id='e1'",
        "UPDATE pipeline_versions SET hocon_text='tampered' WHERE id='v1'",
        "UPDATE pipeline_versions SET is_immutable=0 WHERE id='v1'",
        "DELETE FROM pipeline_versions WHERE id='v1'",
        "UPDATE approval_requests SET decision='rejected' WHERE id='a1'",
        "UPDATE execution_runs SET input_records=-1 WHERE id='r1'",
    ]
    for statement in blocked:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text(statement))

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO pipeline_versions VALUES "
                    "('v2','pl1',2,NULL,'h',:digest,0,"
                    "'2026-10-23T00:00:00+00:00',"
                    "'2026-10-23T00:00:00+00:00')"
                ),
                {"digest": "NOT-A-DIGEST"},
            )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO execution_runs VALUES "
                    "('r2','v1','prep1',NULL,'failed',NULL,-1,0,0,0,NULL,NULL,"
                    "'2026-10-23T00:00:00+00:00','2026-10-23T00:00:00+00:00')"
                )
            )

    engine.dispose()


def test_migration_downgrade_leaves_no_business_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config, url = _migrate_sqlite(tmp_path, monkeypatch)
    command.downgrade(config, "base")

    engine = create_engine(url)
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    with engine.connect() as connection:
        trigger_count = connection.execute(
            text("SELECT count(*) FROM sqlite_master WHERE type='trigger'")
        ).scalar_one()
    assert trigger_count == 0
    engine.dispose()
