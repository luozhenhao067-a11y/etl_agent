"""P-04 confirmed (2026-10-24): Preparation entity with frozen Prepare facts.

Revision ID: 0003_preparations
Revises: 0002_harness_outbox_ledger
Create Date: 2026-10-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# PostgreSQL stores these fields as JSONB, matching the 13-table migration.
JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

revision = "0003_preparations"
down_revision = "0002_harness_outbox_ledger"
branch_labels = None
depends_on = None

_STATUS_CHECK = (
    "status IN ('PREPARED', 'PARTIAL_APPROVED', 'APPROVED', 'REJECTED', 'COMMITTED')"
)
_RISK_CHECK = "risk_level IN ('P0', 'P1', 'P2', 'P3')"
_ENV_CHECK = "environment IN ('prod', 'preprod', 'test')"
_FINGERPRINT_CHECK = "fingerprint LIKE 'sha256:%' AND length(fingerprint) = 71"


def upgrade() -> None:
    op.create_table(
        "preparations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("version_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("applicant_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("risk_level", sa.String(length=8), nullable=False),
        sa.Column("fingerprint", sa.String(length=96), nullable=False),
        sa.Column("artifact_digest", sa.String(length=64), nullable=True),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("resource_scope", JSONType, nullable=True),
        sa.Column("budget", JSONType, nullable=True),
        sa.Column("schedule", JSONType, nullable=True),
        sa.Column("quality_contract_ref", sa.String(length=255), nullable=True),
        sa.Column("data_classification", sa.String(length=32), nullable=True),
        sa.Column("rollback_plan", JSONType, nullable=True),
        sa.Column("decision_digest", sa.String(length=128), nullable=True),
        sa.Column("commit_facts", JSONType, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_preparations"),
        sa.ForeignKeyConstraint(
            ["version_id"], ["pipeline_versions.id"], name="fk_preparations_version_id"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_preparations_project_id"
        ),
        sa.ForeignKeyConstraint(
            ["applicant_id"], ["users.id"], name="fk_preparations_applicant_id"
        ),
        sa.UniqueConstraint(
            "version_id", "fingerprint", name="uq_preparations_version_fingerprint"
        ),
        sa.CheckConstraint(_STATUS_CHECK, name="ck_preparations_status"),
        sa.CheckConstraint(_RISK_CHECK, name="ck_preparations_risk_level"),
        sa.CheckConstraint(_ENV_CHECK, name="ck_preparations_environment"),
        sa.CheckConstraint(_FINGERPRINT_CHECK, name="ck_preparations_fingerprint"),
    )
    op.create_index(
        "ix_preparations_version", "preparations", ["version_id"], unique=False
    )
    op.create_index(
        "ix_preparations_project_status",
        "preparations",
        ["project_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_preparations_project_status", table_name="preparations")
    op.drop_index("ix_preparations_version", table_name="preparations")
    op.drop_table("preparations")
