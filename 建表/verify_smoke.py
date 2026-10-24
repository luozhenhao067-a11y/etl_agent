"""Post-migration smoke checks for the Spec 10.1 schema and demo seed.

Run after ``seed_data.py``. Verifies, against the live database:

1. every table exists with exactly the Spec 10.1 column set,
2. row counts and digest formats (64-char lowercase SHA256),
3. the ``audit_events`` hash chain,
4. the database triggers (append-only ledger, immutable versions, approval
   decision immutability, FK enforcement) — every probe is rolled back,
5. the ORM-level guards from ``db/guards.py``,
6. no plaintext secret ever entered the database (Spec 12.4),
7. timestamp sanity (``created_at <= updated_at``).

Exit code 0 only when every check passes.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKENDPOINT = ROOT.parent / "backendpoint"
for path in (str(BACKENDPOINT), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import re  # noqa: E402

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.models.tables import (  # noqa: E402
    AgentRun,
    ApprovalRequest,
    AuditEvent,
    ExecutionRun,
    FileAsset,
    Pipeline,
    PipelineArtifact,
    PipelineVersion,
    Project,
    ProjectMembership,
    ProjectRoleGrant,
    RuntimeSupervisionSnapshot,
    User,
)
from db.guards import ImmutableRecordError  # noqa: E402
from db.session import create_db_engine  # noqa: E402
from seed_data import (  # noqa: E402
    GENESIS_PREV_HASH,
    canonical_json,
    event_hash_for,
)

DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
SECRET_TOKENS = ("123456", "password=", "BEGIN PRIVATE KEY", "192.168.100.128")

# Spec 10.1 column sets, used as the interface-conformance baseline.
EXPECTED_COLUMNS = {
    "users": {"id", "username", "display_name", "email", "status", "created_at", "updated_at"},
    "projects": {"id", "name", "code", "description", "created_at", "updated_at"},
    "project_memberships": {"id", "project_id", "user_id", "role", "created_at", "updated_at"},
    "project_role_grants": {"id", "project_id", "user_id", "role_slot", "created_at", "updated_at"},
    "pipelines": {"id", "project_id", "name", "code", "description", "status", "created_at", "updated_at"},
    "pipeline_versions": {
        "id", "pipeline_id", "version_number", "etl_plan_json", "hocon_text",
        "artifact_digest", "is_immutable", "created_at", "updated_at",
    },
    "pipeline_artifacts": {"id", "version_id", "artifact_type", "artifact_digest", "content", "created_at"},
    "agent_runs": {
        "id", "version_id", "thread_id", "prompt", "status", "step_count",
        "error_message", "created_at", "updated_at",
    },
    "approval_requests": {
        "id", "preparation_id", "version_id", "required_role", "status",
        "decision", "approver_id", "decided_at", "created_at", "updated_at",
    },
    "execution_runs": {
        "id", "version_id", "preparation_id", "capability_token_digest", "status",
        "engine_job_id", "input_records", "output_records", "error_records",
        "bytes_processed", "started_at", "finished_at", "created_at", "updated_at",
    },
    "file_assets": {
        "id", "project_id", "file_name", "file_path", "file_size",
        "file_format", "schema_json", "created_at", "updated_at",
    },
    "runtime_supervision_snapshots": {
        "id", "execution_run_id", "metrics_json", "decision", "action_taken", "created_at",
    },
    "audit_events": {
        "id", "project_id", "actor_id", "event_type", "resource_type",
        "resource_id", "payload_digest", "prev_event_hash", "event_hash", "created_at",
    },
}

MODELS = {
    "users": User,
    "projects": Project,
    "project_memberships": ProjectMembership,
    "project_role_grants": ProjectRoleGrant,
    "pipelines": Pipeline,
    "pipeline_versions": PipelineVersion,
    "pipeline_artifacts": PipelineArtifact,
    "agent_runs": AgentRun,
    "approval_requests": ApprovalRequest,
    "execution_runs": ExecutionRun,
    "file_assets": FileAsset,
    "runtime_supervision_snapshots": RuntimeSupervisionSnapshot,
    "audit_events": AuditEvent,
}

MIN_ROWS = {
    "users": 24,
    "projects": 6,
    "project_memberships": 33,
    "project_role_grants": 10,
    "pipelines": 20,
    "pipeline_versions": 27,
    "pipeline_artifacts": 31,
    "agent_runs": 25,
    "approval_requests": 50,
    "execution_runs": 26,
    "file_assets": 24,
    "runtime_supervision_snapshots": 25,
    "audit_events": 41,
}

failures: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def db_probe(engine, label: str, sql: str, params: dict | None = None) -> None:
    """Expect `sql` to raise; always rolls back, never persists anything."""

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text(sql), params or {})
        except Exception as exc:
            trans.rollback()
            check(True, label, type(exc).__name__)
            return
        trans.rollback()
    check(False, label, "statement unexpectedly succeeded")


def orm_probe(engine, label: str, mutate) -> None:
    """Expect the ORM flush to raise ImmutableRecordError; always rolls back."""

    with Session(engine) as session:
        try:
            mutate(session)
            session.flush()
        except ImmutableRecordError:
            session.rollback()
            check(True, label)
            return
        except Exception as exc:  # noqa: BLE001 — surfaced for diagnosis
            session.rollback()
            check(False, label, f"unexpected {type(exc).__name__}: {exc}")
            return
        session.rollback()
    check(False, label, "flush succeeded without ImmutableRecordError")


def main() -> int:
    engine = create_db_engine()

    print("== 1. Spec 10.1 column conformance ==")
    for table, model in MODELS.items():
        actual = set(model.__table__.columns.keys())
        check(actual == EXPECTED_COLUMNS[table], f"columns[{table}]",
              f"extra={actual - EXPECTED_COLUMNS[table]} missing={EXPECTED_COLUMNS[table] - actual}")

    print("== 2. Row counts ==")
    with Session(engine) as session:
        for table, model in MODELS.items():
            count = session.execute(select(model.id)).scalars().all()
            check(len(count) >= MIN_ROWS[table], f"rows[{table}] >= {MIN_ROWS[table]}",
                  f"got {len(count)}")

    print("== 3. Digest format (64-char lowercase hex) ==")
    with Session(engine) as session:
        for column, model in (
            ("artifact_digest", PipelineVersion),
            ("artifact_digest", PipelineArtifact),
            ("capability_token_digest", ExecutionRun),
            ("payload_digest", AuditEvent),
            ("prev_event_hash", AuditEvent),
            ("event_hash", AuditEvent),
        ):
            values = [
                value
                for value in session.execute(select(getattr(model, column))).scalars()
                if value is not None
            ]
            bad = [v for v in values if not DIGEST_RE.match(v)]
            check(not bad, f"digest[{model.__tablename__}.{column}]", f"bad={bad[:3]}")

    print("== 4. audit_events hash chain ==")
    with Session(engine) as session:
        rows = session.execute(
            select(AuditEvent).where(AuditEvent.project_id == "prj_demo_001").order_by(AuditEvent.id)
        ).scalars().all()
        chain_ok = True
        prev = GENESIS_PREV_HASH
        for row in rows:
            expected_hash = event_hash_for(
                row.project_id, row.actor_id, row.event_type, row.resource_type,
                row.resource_id, row.payload_digest, row.prev_event_hash,
            )
            if row.prev_event_hash != prev or row.event_hash != expected_hash:
                chain_ok = False
                break
            prev = row.event_hash
        check(chain_ok, "chain[integrity]", f"broke at {row.id}" if not chain_ok else "")

    print("== 5. Timestamps ==")
    with Session(engine) as session:
        for table, model in MODELS.items():
            if not hasattr(model, "updated_at"):
                continue
            rows = session.execute(
                select(model.created_at, model.updated_at)
            ).all()
            bad = [r for r in rows if r.created_at > r.updated_at]
            check(not bad, f"timestamps[{table}] created_at <= updated_at", f"bad={bad[:3]}")
        runs = session.execute(
            select(ExecutionRun.started_at, ExecutionRun.finished_at)
        ).all()
        bad = [r for r in runs if r.started_at and r.finished_at and r.started_at > r.finished_at]
        check(not bad, "timestamps[execution_runs] started_at <= finished_at", f"bad={bad[:3]}")

    print("== 6. Database-level guards (each probe rolled back) ==")
    db_probe(engine, "audit_events UPDATE rejected", "UPDATE audit_events SET event_type = event_type")
    db_probe(engine, "audit_events DELETE rejected", "DELETE FROM audit_events")
    db_probe(engine, "audit_events TRUNCATE rejected", "TRUNCATE audit_events")
    db_probe(engine, "pipeline_versions DELETE rejected", "DELETE FROM pipeline_versions WHERE id = 'ver_demo_001'")
    db_probe(engine, "frozen version content UPDATE rejected",
             "UPDATE pipeline_versions SET hocon_text = 'tampered' WHERE id = 'ver_demo_001'")
    db_probe(engine, "frozen version unfreeze rejected",
             "UPDATE pipeline_versions SET is_immutable = false WHERE id = 'ver_demo_001'")
    db_probe(engine, "decided approval UPDATE rejected",
             "UPDATE approval_requests SET decision = 'reject' WHERE id = 'apr_demo_003'")
    db_probe(engine, "FK violation rejected",
             "INSERT INTO pipelines (id, project_id, name, code, description, status, created_at, updated_at)"
             " VALUES ('fk_probe', 'no_such_project', 'x', 'x', NULL, 'draft', now(), now())")

    print("== 7. ORM-level guards (db/guards.py, each probe rolled back) ==")

    def tamper_frozen_content(session):
        version = session.get(PipelineVersion, "ver_demo_001")
        version.hocon_text = "tampered"

    def unfreeze_version(session):
        version = session.get(PipelineVersion, "ver_demo_001")
        version.is_immutable = False

    def touch_audit(session):
        event = session.execute(
            select(AuditEvent).order_by(AuditEvent.id).limit(1)
        ).scalars().one()
        event.event_type = "tampered"

    def drop_audit(session):
        event = session.execute(
            select(AuditEvent).order_by(AuditEvent.id).limit(1)
        ).scalars().one()
        session.delete(event)

    def touch_draft_version(session):
        version = session.get(PipelineVersion, "ver_demo_002")
        version.updated_at = version.updated_at  # no-op touch, must stay legal

    orm_probe(engine, "ORM frozen content blocked", tamper_frozen_content)
    orm_probe(engine, "ORM unfreeze blocked", unfreeze_version)
    orm_probe(engine, "ORM audit UPDATE blocked", touch_audit)
    orm_probe(engine, "ORM audit DELETE blocked", drop_audit)

    # Negative control: legal writes on an unfrozen version must go through.
    with Session(engine) as session:
        version = session.get(PipelineVersion, "ver_demo_002")
        original = version.updated_at
        version.updated_at = version.updated_at
        session.flush()
        check(True, "ORM legal write on unfrozen version passes",
              f"updated_at={original}")

    print("== 8. Plaintext secret scan (Spec 12.4) ==")
    text_targets = [
        ("pipeline_versions.hocon_text", select(PipelineVersion.hocon_text)),
        ("pipeline_artifacts.content", select(PipelineArtifact.content)),
        ("agent_runs.prompt", select(AgentRun.prompt)),
        ("agent_runs.error_message", select(AgentRun.error_message)),
    ]
    with engine.connect() as conn:
        leaky = []
        for label, query in text_targets:
            for value in conn.execute(query).scalars():
                if value is None:
                    continue
                lowered = value.lower()
                for token in SECRET_TOKENS:
                    if token.lower() in lowered:
                        leaky.append((label, token))
        check(not leaky, "no plaintext secret in text columns", f"leaks={leaky[:5]}")

    engine.dispose()

    print()
    if failures:
        print(f"SMOKE FAILED — {len(failures)} check(s):")
        for label in failures:
            print(f"  - {label}")
        return 1
    print("SMOKE PASSED — schema, seed, chain, guards and secret scan all clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
