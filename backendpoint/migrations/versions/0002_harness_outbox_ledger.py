"""Harness batch 1: outbox table, ledger checkpoints, audit chain order.

Decisions recorded 2026-10-24 (Harness delivery task):
- P-06 confirmed: ``outbox_events`` is the physical Outbox carrier, written in
  the same PostgreSQL transaction as the Commit business facts (Spec 3.8/4.4).
- P-09 decided: ``audit_events.chain_seq`` is the absolute per-project chain
  order, assigned by ``harness.core.ledger_sql.SqlLedger`` under a
  transaction-scoped advisory lock (``MAX+1``); ``created_at`` is never the
  chain order (Spec 3.9). ``occurred_at`` stores the event time that is part
  of the Spec 3.9 hash formula, so verification can recompute hashes.
- ``ledger_checkpoints`` stores Ed25519-signed chain checkpoints (Spec 5.4).

SQLite variants exist so the schema smoke test (tests/test_schema.py) runs
without a database server; SQLite has a single writer, so ``chain_seq`` is a
plain nullable integer there.

Revision ID: 0002_harness_outbox_ledger
Revises: 0001_initial_13_tables
Create Date: 2026-10-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_harness_outbox_ledger"
down_revision = "0001_initial_13_tables"
branch_labels = None
depends_on = None


def _add_chain_columns() -> None:
    # Absolute order only; no autoincrement — SqlLedger assigns MAX+1 under
    # the advisory lock so staging/create_all schemas behave the same as
    # migrated ones (SQLite: single writer, same arithmetic).
    op.add_column(
        "audit_events", sa.Column("chain_seq", sa.BigInteger(), nullable=True)
    )
    op.create_index(
        "ix_audit_events_project_seq", "audit_events", ["project_id", "chain_seq"]
    )
    op.add_column(
        "audit_events",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
    )


def _create_outbox_events() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.String(length=64), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_id", sa.String(length=64), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("event_id", name="pk_outbox_events"),
        sa.UniqueConstraint("idempotency_key", name="uq_outbox_events_idempotency_key"),
        sa.CheckConstraint(
            "event_type = 'execution.command'", name="ck_outbox_events_event_type"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','PUBLISHED','RETRYING','CONSUMED','DEAD_LETTER')",
            name="ck_outbox_events_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_events_attempts"),
        sa.CheckConstraint(
            "length(payload_digest) = 64 AND payload_digest = lower(payload_digest)",
            name="ck_outbox_events_payload_digest",
        ),
    )
    op.create_index(
        "ix_outbox_events_status_available", "outbox_events", ["status", "available_at"]
    )
    op.create_index("ix_outbox_events_aggregate", "outbox_events", ["aggregate_id"])


def _create_ledger_checkpoints() -> None:
    op.create_table(
        "ledger_checkpoints",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column("last_event_hash", sa.String(length=64), nullable=False),
        sa.Column("checkpoint_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm", sa.String(length=16), nullable=False),
        sa.Column("public_key", sa.String(length=64), nullable=False),
        sa.Column("signature", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ledger_checkpoints"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_ledger_checkpoints_project_id"
        ),
        sa.CheckConstraint(
            "length(last_event_hash) = 64 AND last_event_hash = lower(last_event_hash)",
            name="ck_ledger_checkpoints_last_event_hash",
        ),
        sa.CheckConstraint(
            "last_sequence >= 0", name="ck_ledger_checkpoints_last_sequence"
        ),
    )
    op.create_index(
        "ix_ledger_checkpoints_project_created",
        "ledger_checkpoints",
        ["project_id", "checkpoint_at"],
    )


def upgrade() -> None:
    _add_chain_columns()
    _create_outbox_events()
    _create_ledger_checkpoints()


def downgrade() -> None:
    op.drop_index(
        "ix_ledger_checkpoints_project_created", table_name="ledger_checkpoints"
    )
    op.drop_table("ledger_checkpoints")
    op.drop_index("ix_outbox_events_aggregate", table_name="outbox_events")
    op.drop_index("ix_outbox_events_status_available", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_audit_events_project_seq", table_name="audit_events")
    op.drop_column("audit_events", "occurred_at")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_column("audit_events", "chain_seq")
    else:
        with op.batch_alter_table("audit_events") as batch:
            batch.drop_column("chain_seq")
