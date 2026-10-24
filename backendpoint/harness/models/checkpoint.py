"""``ledger_checkpoints`` — signed Evidence Ledger checkpoints (Spec 3.9 / 5.4).

One row per Ed25519-signed ``{last_sequence, last_event_hash, checkpoint_at}``
snapshot of a project chain. Checkpoint frequency remains pending (P-32);
storage layout is fixed so the signer (``harness.core.ledger_sql.SqlLedger``)
and any future verifier job share one format.

``public_key`` is base64url of the raw 32-byte key (43 chars); ``signature``
is base64url of the raw 64-byte Ed25519 signature (86 chars).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.tables import Base


class LedgerCheckpoint(Base):
    __tablename__ = "ledger_checkpoints"
    __table_args__ = (
        CheckConstraint(
            "length(last_event_hash) = 64 AND last_event_hash = lower(last_event_hash)",
            name="ck_ledger_checkpoints_last_event_hash",
        ),
        CheckConstraint(
            "last_sequence >= 0", name="ck_ledger_checkpoints_last_sequence"
        ),
        Index(
            "ix_ledger_checkpoints_project_created", "project_id", "checkpoint_at"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", name="fk_ledger_checkpoints_project_id"),
        nullable=False,
    )
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    checkpoint_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    algorithm: Mapped[str] = mapped_column(String(16), nullable=False)
    public_key: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["LedgerCheckpoint"]
