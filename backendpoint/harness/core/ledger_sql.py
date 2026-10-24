"""PostgreSQL Evidence Ledger (Spec 3.9 / 5.4).

Durable counterpart of ``app.core.harness.ledger.EvidenceLedger``: the hash
chain lives in ``audit_events`` (existing table; migration 0002 adds
``chain_seq`` and ``occurred_at``) and checkpoints in ``ledger_checkpoints``.

Chain order (P-09 decision 2026-10-24) is the per-project ``chain_seq``
assigned by this adapter — never ``created_at`` alone, as Spec 3.9 forbids.
On PostgreSQL the head is serialised with a transaction-scoped advisory lock
(``pg_advisory_xact_lock``, keyed by a SHA256 digest of ``project_id``): read
head → assign ``MAX(chain_seq)+1`` → insert happens atomically with respect
to other ``SqlLedger`` writers, and the lock's release at commit fixes the
commit order to the sequence order. SQLite has a single writer, so the lock
is skipped and the arithmetic is unchanged.

Rows written outside this adapter leave ``chain_seq`` NULL and stay outside
the chain: ``verify`` reports them as ``external_entries`` without treating
them as tampering. Batch 2 routes every audit write through this adapter,
which drives ``external_entries`` to zero.

Hash formula (identical to the in-memory ledger, Spec 3.9):
``event_hash = SHA256(canonical_json(prev_event_hash, project_id, actor_id,
event_type, resource_type, resource_id, payload_digest, occurred_at))`` over
UTF-8, key-sorted JSON. ``occurred_at`` is persisted (migration 0002) so
verification can recompute the hash.

Like every SQL harness adapter, methods take the caller's ``Session`` and
never commit: the append lands in the same transaction as the business fact
(Spec 4.4), and an append failure aborts that transaction — never a silent
drop (Spec 5.4).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.harness.errors import HarnessError
from app.core.harness.models import (
    Clock,
    assert_no_secret_material,
    is_digest,
    isoformat,
    require_nonempty,
    utcnow,
)
from app.core.utils import ZERO_HASH, canonical_json, new_id, sha256_hex
from app.models.tables import AuditEvent
from harness.core.keys import b64url_decode, b64url_encode, public_key_b64url
from harness.core.outbox_sql import to_utc_datetime
from harness.models.checkpoint import LedgerCheckpoint

_CHECKPOINT_FIELDS = ("last_sequence", "last_event_hash", "checkpoint_at")


class SqlLedger:
    def __init__(
        self,
        *,
        clock: Clock = utcnow,
        private_key: Ed25519PrivateKey | None = None,
    ) -> None:
        self._clock = clock
        # Ephemeral fallback is for tests only: without a persisted key,
        # checkpoints cannot be verified across restarts. Production loads
        # the key through harness.core.keys.load_private_key.
        self._private_key = private_key or Ed25519PrivateKey.generate()
        self._public_key = self._private_key.public_key()

    # -- append ---------------------------------------------------------------

    async def append(self, session: Session, event: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(event, dict):
            raise HarnessError(422, "EL-422", "ledger event must be an object")
        if "payload" in event or "secret" in event or "token" in event:
            raise HarnessError(
                422, "EL-422", "ledger stores payload_digest only, not sensitive payload"
            )
        try:
            project_id = require_nonempty(event.get("project_id"), "project_id")
            actor_id = require_nonempty(event.get("actor_id"), "actor_id")
            event_type = require_nonempty(event.get("event_type"), "event_type")
            resource_type = require_nonempty(event.get("resource_type"), "resource_type")
            resource_id = require_nonempty(event.get("resource_id"), "resource_id")
            payload_digest = event.get("payload_digest")
            if not is_digest(payload_digest):
                raise ValueError(
                    "payload_digest must be a 64-character lowercase SHA256"
                )
            occurred_at = to_utc_datetime(
                event.get("occurred_at") or isoformat(self._clock()), "occurred_at"
            )
            correlation_id = event.get("correlation_id")
            if correlation_id is not None and not isinstance(correlation_id, str):
                raise ValueError("correlation_id must be a string")
            assert_no_secret_material(event)
        except ValueError as exc:
            raise HarnessError(422, "EL-422", str(exc)) from None

        # correlation_id is validated but not persisted: audit_events has no
        # column for it (Spec 10.1). The calling layer carries it in its
        # structured log keyed by the returned event id.
        occurred_iso = isoformat(occurred_at)

        # Serialise head-read + sequence assignment + insert per project.
        self._lock_chain_head(session, project_id)
        head = self._head(session, project_id)
        prev_hash = head["event_hash"] if head else ZERO_HASH
        supplied_prev = event.get("prev_event_hash")
        if supplied_prev is not None and supplied_prev != prev_hash:
            raise HarnessError(409, "EL-409", "ledger chain head conflict")
        event_hash = sha256_hex(
            canonical_json(
                {
                    "prev_event_hash": prev_hash,
                    "project_id": project_id,
                    "actor_id": actor_id,
                    "event_type": event_type,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "payload_digest": payload_digest,
                    "occurred_at": occurred_iso,
                }
            )
        )
        supplied_hash = event.get("event_hash")
        if supplied_hash is not None and supplied_hash != event_hash:
            raise HarnessError(422, "EL-422", "supplied event_hash does not match")

        event_id = event.get("event_id") or new_id("evt")
        if not isinstance(event_id, str) or not event_id.strip():
            raise HarnessError(422, "EL-422", "event_id must be a non-empty string")
        duplicate = session.execute(
            select(AuditEvent.id).where(AuditEvent.id == event_id)
        ).first()
        if duplicate is not None:
            raise HarnessError(409, "EL-409", "ledger event id already exists")

        row = AuditEvent(
            id=event_id,
            project_id=project_id,
            actor_id=actor_id,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            payload_digest=payload_digest,
            prev_event_hash=prev_hash,
            event_hash=event_hash,
            created_at=to_utc_datetime(self._clock(), "created_at"),
            occurred_at=occurred_at,
            chain_seq=(head["chain_seq"] + 1) if head else 1,
        )
        session.add(row)
        session.flush()
        return self._entry(row, correlation_id)

    # -- verification ---------------------------------------------------------

    def verify(self, session: Session, project_id: str) -> dict[str, Any]:
        """Re-walk the per-project chain and recompute every ledger row hash."""

        try:
            project_id = require_nonempty(project_id, "project_id")
        except ValueError as exc:
            raise HarnessError(422, "EL-422", str(exc)) from None
        rows = (
            session.execute(
                select(AuditEvent)
                .where(
                    AuditEvent.project_id == project_id,
                    AuditEvent.chain_seq.is_not(None),
                )
                .order_by(AuditEvent.chain_seq)
            )
            .scalars()
            .all()
        )
        external = self._external_count(session, project_id)
        prev_hash = ZERO_HASH
        for row in rows:
            if row.occurred_at is None:
                return self._broken(row, "missing_occurred_at", len(rows), external)
            if row.prev_event_hash != prev_hash:
                return self._broken(
                    row, "prev_event_hash_mismatch", len(rows), external
                )
            if row.event_hash != self._row_event_hash(row):
                return self._broken(row, "event_hash_mismatch", len(rows), external)
            prev_hash = row.event_hash
        return {
            "status": "VERIFIED",
            "project_id": project_id,
            "entries": len(rows),
            "external_entries": external,
            "last_event_hash": prev_hash,
        }

    @staticmethod
    def _broken(
        row: AuditEvent, reason: str, entries: int, external: int
    ) -> dict[str, Any]:
        return {
            "status": "BROKEN",
            "project_id": row.project_id,
            "broken_at": row.chain_seq,
            "reason": reason,
            "entries": entries,
            "external_entries": external,
        }

    @staticmethod
    def _external_count(session: Session, project_id: str) -> int:
        return int(
            session.execute(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.project_id == project_id,
                    AuditEvent.chain_seq.is_(None),
                )
            ).scalar_one()
        )

    # -- checkpoints ----------------------------------------------------------

    def checkpoint(self, session: Session, project_id: str) -> dict[str, Any]:
        """Sign the current chain head and persist the checkpoint row."""

        try:
            project_id = require_nonempty(project_id, "project_id")
        except ValueError as exc:
            raise HarnessError(422, "EL-422", str(exc)) from None
        self._lock_chain_head(session, project_id)
        head = self._head(session, project_id)
        payload = {
            "last_sequence": head["chain_seq"] if head else 0,
            "last_event_hash": head["event_hash"] if head else ZERO_HASH,
            "checkpoint_at": isoformat(self._clock()),
        }
        signature = self._private_key.sign(canonical_json(payload).encode("utf-8"))
        row = LedgerCheckpoint(
            id=new_id("ckpt"),
            project_id=project_id,
            last_sequence=payload["last_sequence"],
            last_event_hash=payload["last_event_hash"],
            checkpoint_at=to_utc_datetime(payload["checkpoint_at"], "checkpoint_at"),
            algorithm="Ed25519",
            public_key=public_key_b64url(self._private_key),
            signature=b64url_encode(signature),
            created_at=to_utc_datetime(self._clock(), "created_at"),
        )
        session.add(row)
        session.flush()
        return {
            "id": row.id,
            "project_id": project_id,
            **payload,
            "algorithm": "Ed25519",
            "public_key": row.public_key,
            "signature": row.signature,
        }

    def verify_checkpoint(self, checkpoint: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(checkpoint, dict):
            raise HarnessError(410, "EL-410", "checkpoint is invalid")
        payload = {field: checkpoint.get(field) for field in _CHECKPOINT_FIELDS}
        if (
            not isinstance(payload["last_sequence"], int)
            or payload["last_sequence"] < 0
            or not is_digest(payload["last_event_hash"])
            or not isinstance(payload["checkpoint_at"], str)
            or checkpoint.get("algorithm") != "Ed25519"
        ):
            raise HarnessError(410, "EL-410", "checkpoint is invalid")
        try:
            signature = b64url_decode(checkpoint["signature"])
            self._public_key.verify(
                signature, canonical_json(payload).encode("utf-8")
            )
        except (KeyError, ValueError, InvalidSignature, TypeError):
            raise HarnessError(410, "EL-410", "checkpoint signature is invalid") from None
        return {
            "status": "VERIFIED",
            "project_id": checkpoint.get("project_id"),
            "last_sequence": payload["last_sequence"],
            "last_event_hash": payload["last_event_hash"],
        }

    def list_checkpoints(
        self, session: Session, project_id: str
    ) -> list[dict[str, Any]]:
        rows = (
            session.execute(
                select(LedgerCheckpoint)
                .where(LedgerCheckpoint.project_id == project_id)
                .order_by(
                    LedgerCheckpoint.checkpoint_at.desc(), LedgerCheckpoint.id.desc()
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": row.id,
                "project_id": row.project_id,
                "last_sequence": row.last_sequence,
                "last_event_hash": row.last_event_hash,
                "checkpoint_at": isoformat(row.checkpoint_at),
                "algorithm": row.algorithm,
                "public_key": row.public_key,
                "signature": row.signature,
                "created_at": isoformat(row.created_at),
            }
            for row in rows
        ]

    # -- chain head -----------------------------------------------------------

    @staticmethod
    def _lock_chain_head(session: Session, project_id: str) -> None:
        if session.get_bind().dialect.name != "postgresql":
            return  # SQLite has a single writer; nothing to serialise against.
        key = int.from_bytes(
            hashlib.sha256(project_id.encode("utf-8")).digest()[:8], "big", signed=True
        )
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    @staticmethod
    def _head(session: Session, project_id: str) -> dict[str, Any] | None:
        row = session.execute(
            select(AuditEvent.event_hash, AuditEvent.chain_seq)
            .where(
                AuditEvent.project_id == project_id,
                AuditEvent.chain_seq.is_not(None),
            )
            .order_by(AuditEvent.chain_seq.desc())
            .limit(1)
        ).first()
        if row is None:
            return None
        return {"event_hash": row.event_hash, "chain_seq": int(row.chain_seq)}

    # -- entry shaping --------------------------------------------------------

    def _entry(
        self, row: AuditEvent, correlation_id: str | None
    ) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "actor_id": row.actor_id,
            "event_type": row.event_type,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "payload_digest": row.payload_digest,
            "occurred_at": isoformat(row.occurred_at),
            "correlation_id": correlation_id,
            "prev_event_hash": row.prev_event_hash,
            "event_hash": row.event_hash,
            "created_at": isoformat(row.created_at),
            "chain_seq": row.chain_seq,
        }

    @staticmethod
    def _row_event_hash(row: AuditEvent) -> str:
        return sha256_hex(
            canonical_json(
                {
                    "prev_event_hash": row.prev_event_hash,
                    "project_id": row.project_id,
                    "actor_id": row.actor_id,
                    "event_type": row.event_type,
                    "resource_type": row.resource_type,
                    "resource_id": row.resource_id,
                    "payload_digest": row.payload_digest,
                    "occurred_at": isoformat(row.occurred_at),
                }
            )
        )


__all__ = ["SqlLedger"]
