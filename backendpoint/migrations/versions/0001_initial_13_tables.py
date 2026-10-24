"""Create the thirteen PRD 7.1 / Spec 10.1 tables.

Only the tables explicitly listed by the specification are created. Connection
configuration, metadata profiles, Preparation, Outbox, Capability consumption
and Benchmark results remain undefined and therefore stay out of the schema.

The migration also installs database guards for rows that the specification
marks append-only or immutable. PostgreSQL is the production target; SQLite
guards exist so the schema can be smoke-tested without a database server.

Revision ID: 0001_initial_13_tables
Revises:
Create Date: 2026-10-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial_13_tables"
down_revision = None
branch_labels = None
depends_on = None

# PostgreSQL stores these fields as JSONB so the immutability trigger can
# compare them with equality. SQLite uses JSON for the migration smoke test.
JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _create_postgresql_guards() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION etl_reject_audit_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION etl_reject_audit_truncate()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only';
        END;
        $$;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_audit_events_no_update ON audit_events"
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_events_no_update
        BEFORE UPDATE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION etl_reject_audit_mutation()
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_audit_events_no_delete ON audit_events"
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_events_no_delete
        BEFORE DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION etl_reject_audit_mutation()
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_audit_events_no_truncate ON audit_events"
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_events_no_truncate
        BEFORE TRUNCATE ON audit_events
        FOR EACH STATEMENT EXECUTE FUNCTION etl_reject_audit_truncate()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION etl_guard_pipeline_version()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.is_immutable THEN
                IF NEW.is_immutable IS DISTINCT FROM TRUE THEN
                    RAISE EXCEPTION 'pipeline_versions cannot be unfrozen';
                END IF;
                IF NEW.etl_plan_json IS DISTINCT FROM OLD.etl_plan_json
                   OR NEW.hocon_text IS DISTINCT FROM OLD.hocon_text
                   OR NEW.artifact_digest IS DISTINCT FROM OLD.artifact_digest THEN
                    RAISE EXCEPTION 'pipeline_versions content is immutable';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_pipeline_versions_immutable ON pipeline_versions"
    )
    op.execute(
        """
        CREATE TRIGGER trg_pipeline_versions_immutable
        BEFORE UPDATE ON pipeline_versions
        FOR EACH ROW EXECUTE FUNCTION etl_guard_pipeline_version()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION etl_reject_pipeline_version_delete()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'pipeline_versions cannot be deleted';
        END;
        $$;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_pipeline_versions_no_delete ON pipeline_versions"
    )
    op.execute(
        """
        CREATE TRIGGER trg_pipeline_versions_no_delete
        BEFORE DELETE ON pipeline_versions
        FOR EACH ROW EXECUTE FUNCTION etl_reject_pipeline_version_delete()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION etl_guard_approval_decision()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.decision IS NOT NULL THEN
                IF NEW.decision IS DISTINCT FROM OLD.decision
                   OR NEW.approver_id IS DISTINCT FROM OLD.approver_id
                   OR NEW.decided_at IS DISTINCT FROM OLD.decided_at THEN
                    RAISE EXCEPTION 'approval decision is immutable';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_approval_requests_decision ON approval_requests"
    )
    op.execute(
        """
        CREATE TRIGGER trg_approval_requests_decision
        BEFORE UPDATE ON approval_requests
        FOR EACH ROW EXECUTE FUNCTION etl_guard_approval_decision()
        """
    )


def _create_sqlite_guards() -> None:
    op.execute(
        """
        CREATE TRIGGER trg_audit_events_no_update
        BEFORE UPDATE ON audit_events
        BEGIN
            SELECT RAISE(ABORT, 'audit_events is append-only');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_events_no_delete
        BEFORE DELETE ON audit_events
        BEGIN
            SELECT RAISE(ABORT, 'audit_events is append-only');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_pipeline_versions_immutable
        BEFORE UPDATE ON pipeline_versions
        WHEN OLD.is_immutable = 1 AND (
            NEW.is_immutable <> 1
            OR NEW.etl_plan_json IS NOT OLD.etl_plan_json
            OR NEW.hocon_text IS NOT OLD.hocon_text
            OR NEW.artifact_digest IS NOT OLD.artifact_digest
        )
        BEGIN
            SELECT RAISE(ABORT, 'pipeline_versions content is immutable');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_pipeline_versions_no_delete
        BEFORE DELETE ON pipeline_versions
        BEGIN
            SELECT RAISE(ABORT, 'pipeline_versions cannot be deleted');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_approval_requests_decision
        BEFORE UPDATE ON approval_requests
        WHEN OLD.decision IS NOT NULL AND (
            NEW.decision IS NOT OLD.decision
            OR NEW.approver_id IS NOT OLD.approver_id
            OR NEW.decided_at IS NOT OLD.decided_at
        )
        BEGIN
            SELECT RAISE(ABORT, 'approval decision is immutable');
        END
        """
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_status", "users", ["status"])

    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
        sa.UniqueConstraint("code", name="uq_projects_code"),
    )

    op.create_table(
        "project_memberships",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_project_memberships_project_id",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_project_memberships_user_id"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_project_memberships"),
        sa.UniqueConstraint(
            "project_id", "user_id", name="uq_project_memberships_project_user"
        ),
    )
    op.create_index(
        "ix_project_memberships_user_id", "project_memberships", ["user_id"]
    )
    op.create_index(
        "ix_project_memberships_project_role",
        "project_memberships",
        ["project_id", "role"],
    )

    op.create_table(
        "project_role_grants",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("role_slot", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_project_role_grants_project_id",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_project_role_grants_user_id"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_project_role_grants"),
        sa.UniqueConstraint(
            "project_id",
            "user_id",
            "role_slot",
            name="uq_project_role_grants_project_user_slot",
        ),
    )
    op.create_index(
        "ix_project_role_grants_project_slot",
        "project_role_grants",
        ["project_id", "role_slot"],
    )

    op.create_table(
        "pipelines",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_pipelines_project_id"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pipelines"),
        sa.UniqueConstraint("project_id", "code", name="uq_pipelines_project_code"),
    )
    op.create_index(
        "ix_pipelines_project_status", "pipelines", ["project_id", "status"]
    )

    op.create_table(
        "pipeline_versions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("pipeline_id", sa.String(length=64), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("etl_plan_json", JSONType, nullable=True),
        sa.Column("hocon_text", sa.Text(), nullable=True),
        sa.Column("artifact_digest", sa.String(length=64), nullable=True),
        sa.Column("is_immutable", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["pipeline_id"],
            ["pipelines.id"],
            name="fk_pipeline_versions_pipeline_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pipeline_versions"),
        sa.UniqueConstraint(
            "pipeline_id", "version_number", name="uq_pipeline_versions_pipeline_number"
        ),
        sa.CheckConstraint(
            "artifact_digest IS NULL OR "
            "(length(artifact_digest) = 64 AND artifact_digest = lower(artifact_digest))",
            name="ck_pipeline_versions_artifact_digest",
        ),
    )
    op.create_index(
        "ix_pipeline_versions_pipeline_created",
        "pipeline_versions",
        ["pipeline_id", "created_at"],
    )
    op.create_index(
        "ix_pipeline_versions_artifact_digest",
        "pipeline_versions",
        ["artifact_digest"],
    )

    op.create_table(
        "pipeline_artifacts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("artifact_digest", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["pipeline_versions.id"],
            name="fk_pipeline_artifacts_version_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pipeline_artifacts"),
        sa.UniqueConstraint(
            "version_id",
            "artifact_type",
            "artifact_digest",
            name="uq_pipeline_artifacts_version_type_digest",
        ),
        sa.CheckConstraint(
            "length(artifact_digest) = 64 AND artifact_digest = lower(artifact_digest)",
            name="ck_pipeline_artifacts_artifact_digest",
        ),
    )
    op.create_index(
        "ix_pipeline_artifacts_version_type",
        "pipeline_artifacts",
        ["version_id", "artifact_type"],
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("step_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"], ["pipeline_versions.id"], name="fk_agent_runs_version_id"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_runs"),
        sa.CheckConstraint("step_count >= 0", name="ck_agent_runs_step_count"),
    )
    op.create_index(
        "ix_agent_runs_version_created", "agent_runs", ["version_id", "created_at"]
    )
    op.create_index("ix_agent_runs_thread_id", "agent_runs", ["thread_id"])

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("preparation_id", sa.String(length=64), nullable=False),
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("required_role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=True),
        sa.Column("approver_id", sa.String(length=64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["pipeline_versions.id"],
            name="fk_approval_requests_version_id",
        ),
        sa.ForeignKeyConstraint(
            ["approver_id"],
            ["users.id"],
            name="fk_approval_requests_approver_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_approval_requests"),
        sa.UniqueConstraint(
            "preparation_id",
            "required_role",
            name="uq_approval_requests_preparation_role",
        ),
    )
    op.create_index(
        "ix_approval_requests_preparation_id",
        "approval_requests",
        ["preparation_id"],
    )
    op.create_index(
        "ix_approval_requests_approver_status",
        "approval_requests",
        ["approver_id", "status"],
    )
    op.create_index(
        "ix_approval_requests_version_id", "approval_requests", ["version_id"]
    )

    op.create_table(
        "execution_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("preparation_id", sa.String(length=64), nullable=False),
        sa.Column("capability_token_digest", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("engine_job_id", sa.String(length=128), nullable=True),
        sa.Column("input_records", sa.Integer(), nullable=False),
        sa.Column("output_records", sa.Integer(), nullable=False),
        sa.Column("error_records", sa.Integer(), nullable=False),
        sa.Column("bytes_processed", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["pipeline_versions.id"],
            name="fk_execution_runs_version_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_execution_runs"),
        sa.UniqueConstraint(
            "capability_token_digest",
            name="uq_execution_runs_capability_token_digest",
        ),
        sa.CheckConstraint(
            "capability_token_digest IS NULL OR "
            "(length(capability_token_digest) = 64 "
            "AND capability_token_digest = lower(capability_token_digest))",
            name="ck_execution_runs_capability_token_digest",
        ),
        sa.CheckConstraint("input_records >= 0", name="ck_execution_runs_input_records"),
        sa.CheckConstraint("output_records >= 0", name="ck_execution_runs_output_records"),
        sa.CheckConstraint("error_records >= 0", name="ck_execution_runs_error_records"),
        sa.CheckConstraint("bytes_processed >= 0", name="ck_execution_runs_bytes_processed"),
    )
    op.create_index(
        "ix_execution_runs_version_created",
        "execution_runs",
        ["version_id", "created_at"],
    )
    op.create_index(
        "ix_execution_runs_preparation_id", "execution_runs", ["preparation_id"]
    )
    op.create_index("ix_execution_runs_status", "execution_runs", ["status"])
    op.create_index(
        "ix_execution_runs_engine_job_id", "execution_runs", ["engine_job_id"]
    )

    op.create_table(
        "file_assets",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("file_format", sa.String(length=32), nullable=False),
        sa.Column("schema_json", JSONType, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_file_assets_project_id"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_file_assets"),
        sa.CheckConstraint("file_size >= 0", name="ck_file_assets_file_size"),
    )
    op.create_index(
        "ix_file_assets_project_created", "file_assets", ["project_id", "created_at"]
    )
    op.create_index("ix_file_assets_file_format", "file_assets", ["file_format"])

    op.create_table(
        "runtime_supervision_snapshots",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("execution_run_id", sa.String(length=64), nullable=False),
        sa.Column("metrics_json", JSONType, nullable=True),
        sa.Column("decision", sa.String(length=64), nullable=True),
        sa.Column("action_taken", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_run_id"],
            ["execution_runs.id"],
            name="fk_runtime_supervision_snapshots_run_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_runtime_supervision_snapshots"),
    )
    op.create_index(
        "ix_runtime_supervision_snapshots_run_created",
        "runtime_supervision_snapshots",
        ["execution_run_id", "created_at"],
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("prev_event_hash", sa.String(length=64), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_audit_events_project_id"
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_audit_events_actor_id"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        sa.UniqueConstraint("event_hash", name="uq_audit_events_event_hash"),
        sa.CheckConstraint(
            "length(payload_digest) = 64 AND payload_digest = lower(payload_digest)",
            name="ck_audit_events_payload_digest",
        ),
        sa.CheckConstraint(
            "length(prev_event_hash) = 64 "
            "AND prev_event_hash = lower(prev_event_hash)",
            name="ck_audit_events_prev_event_hash",
        ),
        sa.CheckConstraint(
            "length(event_hash) = 64 AND event_hash = lower(event_hash)",
            name="ck_audit_events_event_hash",
        ),
    )
    op.create_index(
        "ix_audit_events_project_created", "audit_events", ["project_id", "created_at"]
    )
    op.create_index(
        "ix_audit_events_resource", "audit_events", ["resource_type", "resource_id"]
    )
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _create_postgresql_guards()
    elif bind.dialect.name == "sqlite":
        _create_sqlite_guards()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_approval_requests_decision ON approval_requests"
        )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_pipeline_versions_no_delete ON pipeline_versions"
        )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_pipeline_versions_immutable ON pipeline_versions"
        )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_audit_events_no_truncate ON audit_events"
        )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_audit_events_no_delete ON audit_events"
        )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_audit_events_no_update ON audit_events"
        )
        op.execute("DROP FUNCTION IF EXISTS etl_guard_approval_decision()")
        op.execute("DROP FUNCTION IF EXISTS etl_reject_pipeline_version_delete()")
        op.execute("DROP FUNCTION IF EXISTS etl_guard_pipeline_version()")
        op.execute("DROP FUNCTION IF EXISTS etl_reject_audit_truncate()")
        op.execute("DROP FUNCTION IF EXISTS etl_reject_audit_mutation()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_approval_requests_decision")
        op.execute("DROP TRIGGER IF EXISTS trg_pipeline_versions_no_delete")
        op.execute("DROP TRIGGER IF EXISTS trg_pipeline_versions_immutable")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_events_no_delete")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_events_no_update")

    op.drop_table("audit_events")
    op.drop_table("runtime_supervision_snapshots")
    op.drop_table("file_assets")
    op.drop_table("execution_runs")
    op.drop_table("approval_requests")
    op.drop_table("agent_runs")
    op.drop_table("pipeline_artifacts")
    op.drop_table("pipeline_versions")
    op.drop_table("pipelines")
    op.drop_table("project_role_grants")
    op.drop_table("project_memberships")
    op.drop_table("projects")
    op.drop_table("users")
