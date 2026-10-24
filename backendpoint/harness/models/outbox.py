"""``outbox_events`` — Transactional Outbox rows (Spec 3.8 / 5.3, P-06).

Physical carrier for the execution command written in the Commit transaction.
The state machine lives in ``harness.core.outbox_sql.SqlOutbox``; this model
only declares the persisted shape and the database-level invariants:

- ``idempotency_key`` is globally unique (at-least-once delivery + consumer
  dedup by ``execution_run_id + idempotency_key``).
- ``status`` can only hold the five forward-only states of Spec 5.3.1;
  regressions such as CONSUMED → PUBLISHED cannot be stored.
- ``payload_digest`` follows the project-wide lowercase SHA256 convention.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.tables import Base


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(
            "event_type = 'execution.command'", name="ck_outbox_events_event_type"
        ),
        CheckConstraint(
            "status IN ('PENDING','PUBLISHED','RETRYING','CONSUMED','DEAD_LETTER')",
            name="ck_outbox_events_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_outbox_events_attempts"),
        CheckConstraint(
            "length(payload_digest) = 64 AND payload_digest = lower(payload_digest)",
            name="ck_outbox_events_payload_digest",
        ),
        UniqueConstraint("idempotency_key", name="uq_outbox_events_idempotency_key"),
        Index("ix_outbox_events_status_available", "status", "available_at"),
        Index("ix_outbox_events_aggregate", "aggregate_id"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Dispatch lease: NULL when no dispatcher holds the event.
    lease_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)


__all__ = ["OutboxEvent"]
