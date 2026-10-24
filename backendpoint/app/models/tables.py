"""SQLAlchemy models for the thirteen PRD 7.1 / Spec 10.1 tables.

The models are the schema source of truth for Alembic autogenerate and for
schema tests. They deliberately do not include connection configuration,
metadata profiles, Preparation, Outbox, Capability consumption or Benchmark
results: those entities are not defined in the specification and remain
in-memory until the contract is extended.

Database-level guards for append-only and immutable rows live in the Alembic
migration because they are trigger DDL, not table metadata.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# PostgreSQL JSONB supports equality, which the immutability trigger needs.
# SQLite keeps the portable JSON type for the migration smoke test.
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """Declarative base shared by the thirteen specified tables."""


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        UniqueConstraint("email", name="uq_users_email"),
        Index("ix_users_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("code", name="uq_projects_code"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectMembership(Base):
    __tablename__ = "project_memberships"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "user_id", name="uq_project_memberships_project_user"
        ),
        Index("ix_project_memberships_user_id", "user_id"),
        Index("ix_project_memberships_project_role", "project_id", "role"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", name="fk_project_memberships_project_id"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", name="fk_project_memberships_user_id"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectRoleGrant(Base):
    __tablename__ = "project_role_grants"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "user_id",
            "role_slot",
            name="uq_project_role_grants_project_user_slot",
        ),
        Index("ix_project_role_grants_project_slot", "project_id", "role_slot"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", name="fk_project_role_grants_project_id"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", name="fk_project_role_grants_user_id"),
        nullable=False,
    )
    role_slot: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Pipeline(Base):
    __tablename__ = "pipelines"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_pipelines_project_code"),
        Index("ix_pipelines_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", name="fk_pipelines_project_id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PipelineVersion(Base):
    __tablename__ = "pipeline_versions"
    __table_args__ = (
        UniqueConstraint(
            "pipeline_id", "version_number", name="uq_pipeline_versions_pipeline_number"
        ),
        CheckConstraint(
            "artifact_digest IS NULL OR "
            "(length(artifact_digest) = 64 AND artifact_digest = lower(artifact_digest))",
            name="ck_pipeline_versions_artifact_digest",
        ),
        Index("ix_pipeline_versions_pipeline_created", "pipeline_id", "created_at"),
        Index("ix_pipeline_versions_artifact_digest", "artifact_digest"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pipeline_id: Mapped[str] = mapped_column(
        ForeignKey("pipelines.id", name="fk_pipeline_versions_pipeline_id"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    etl_plan_json: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    hocon_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PipelineArtifact(Base):
    __tablename__ = "pipeline_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "version_id",
            "artifact_type",
            "artifact_digest",
            name="uq_pipeline_artifacts_version_type_digest",
        ),
        CheckConstraint(
            "length(artifact_digest) = 64 AND artifact_digest = lower(artifact_digest)",
            name="ck_pipeline_artifacts_artifact_digest",
        ),
        Index("ix_pipeline_artifacts_version_type", "version_id", "artifact_type"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("pipeline_versions.id", name="fk_pipeline_artifacts_version_id"),
        nullable=False,
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint("step_count >= 0", name="ck_agent_runs_step_count"),
        Index("ix_agent_runs_version_created", "version_id", "created_at"),
        Index("ix_agent_runs_thread_id", "thread_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("pipeline_versions.id", name="fk_agent_runs_version_id"),
        nullable=False,
    )
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        UniqueConstraint(
            "preparation_id",
            "required_role",
            name="uq_approval_requests_preparation_role",
        ),
        Index("ix_approval_requests_preparation_id", "preparation_id"),
        Index("ix_approval_requests_approver_status", "approver_id", "status"),
        Index("ix_approval_requests_version_id", "version_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    preparation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("pipeline_versions.id", name="fk_approval_requests_version_id"),
        nullable=False,
    )
    required_role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approver_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", name="fk_approval_requests_approver_id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Preparation(Base):
    """P-04 entity (confirmed 2026-10-24): frozen Prepare facts (Spec 4.2).

    One preparation per immutable version: the (version_id, fingerprint)
    unique constraint realises "同一 version + 指纹返回同一 Preparation;
    不同指纹 PREP-409 FINGERPRINT_CONFLICT". The frozen facts (environment,
    resource scope, budget, schedule, quality contract, rollback plan) must
    not change after creation; commit appends commit_facts without rewriting
    the frozen columns.
    """

    __tablename__ = "preparations"
    __table_args__ = (
        UniqueConstraint(
            "version_id", "fingerprint", name="uq_preparations_version_fingerprint"
        ),
        CheckConstraint(
            "status IN ('PREPARED', 'PARTIAL_APPROVED', 'APPROVED', "
            "'REJECTED', 'COMMITTED')",
            name="ck_preparations_status",
        ),
        CheckConstraint(
            "risk_level IN ('P0', 'P1', 'P2', 'P3')",
            name="ck_preparations_risk_level",
        ),
        CheckConstraint(
            "environment IN ('prod', 'preprod', 'test')",
            name="ck_preparations_environment",
        ),
        CheckConstraint(
            "fingerprint LIKE 'sha256:%' AND length(fingerprint) = 71",
            name="ck_preparations_fingerprint",
        ),
        Index("ix_preparations_version", "version_id"),
        Index("ix_preparations_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("pipeline_versions.id", name="fk_preparations_version_id"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", name="fk_preparations_project_id"), nullable=False
    )
    applicant_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", name="fk_preparations_applicant_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(8), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(96), nullable=False)
    artifact_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    # Frozen facts (Spec 4.2) and the derived rollback plan.
    resource_scope: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    budget: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    schedule: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    quality_contract_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data_classification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rollback_plan: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    # The bound PDP decision (Spec 3.4 BOUND_TO_PREPARATION).
    decision_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Appended by the Commit orchestrator inside its atomic transaction.
    commit_facts: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExecutionRun(Base):
    __tablename__ = "execution_runs"
    __table_args__ = (
        CheckConstraint(
            "capability_token_digest IS NULL OR "
            "(length(capability_token_digest) = 64 "
            "AND capability_token_digest = lower(capability_token_digest))",
            name="ck_execution_runs_capability_token_digest",
        ),
        CheckConstraint("input_records >= 0", name="ck_execution_runs_input_records"),
        CheckConstraint("output_records >= 0", name="ck_execution_runs_output_records"),
        CheckConstraint("error_records >= 0", name="ck_execution_runs_error_records"),
        CheckConstraint("bytes_processed >= 0", name="ck_execution_runs_bytes_processed"),
        UniqueConstraint(
            "capability_token_digest", name="uq_execution_runs_capability_token_digest"
        ),
        Index("ix_execution_runs_version_created", "version_id", "created_at"),
        Index("ix_execution_runs_preparation_id", "preparation_id"),
        Index("ix_execution_runs_status", "status"),
        Index("ix_execution_runs_engine_job_id", "engine_job_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("pipeline_versions.id", name="fk_execution_runs_version_id"),
        nullable=False,
    )
    preparation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    capability_token_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    engine_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Byte totals routinely exceed the 32-bit range (frontend mock uses 6 GB
    # demo values), so this metric column is 64-bit.
    bytes_processed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FileAsset(Base):
    __tablename__ = "file_assets"
    __table_args__ = (
        CheckConstraint("file_size >= 0", name="ck_file_assets_file_size"),
        Index("ix_file_assets_project_created", "project_id", "created_at"),
        Index("ix_file_assets_file_format", "file_format"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", name="fk_file_assets_project_id"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_format: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_json: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RuntimeSupervisionSnapshot(Base):
    __tablename__ = "runtime_supervision_snapshots"
    __table_args__ = (
        Index(
            "ix_runtime_supervision_snapshots_run_created",
            "execution_run_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_run_id: Mapped[str] = mapped_column(
        ForeignKey("execution_runs.id", name="fk_runtime_supervision_snapshots_run_id"),
        nullable=False,
    )
    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action_taken: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("event_hash", name="uq_audit_events_event_hash"),
        CheckConstraint(
            "length(payload_digest) = 64 AND payload_digest = lower(payload_digest)",
            name="ck_audit_events_payload_digest",
        ),
        CheckConstraint(
            "length(prev_event_hash) = 64 AND prev_event_hash = lower(prev_event_hash)",
            name="ck_audit_events_prev_event_hash",
        ),
        CheckConstraint(
            "length(event_hash) = 64 AND event_hash = lower(event_hash)",
            name="ck_audit_events_event_hash",
        ),
        Index("ix_audit_events_project_created", "project_id", "created_at"),
        Index("ix_audit_events_resource", "resource_type", "resource_id"),
        Index("ix_audit_events_event_type", "event_type"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", name="fk_audit_events_project_id"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", name="fk_audit_events_actor_id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Migration 0002: absolute per-project chain order assigned by the SQL
    # Evidence Ledger (harness/core/ledger_sql.py) under its advisory lock,
    # and the event time used in the Spec 3.9 hash formula. NULL chain_seq
    # marks rows written outside the ledger; verify() reports them as
    # external entries until all writers are unified.
    chain_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
