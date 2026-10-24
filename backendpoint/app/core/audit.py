"""Audit event writer for the API-layer delivery.

The real Evidence Ledger is a Harness dependency and is exposed only through
``HarnessPort.append_ledger``; that Stub is not implemented. This service keeps
a local, in-memory staging copy of Spec 12.2 events so the API layer can prove
its audit calls in tests. Every record is therefore marked
``ledger_status="pending_ledger"`` in the structured log: it is not a Ledger
entry and must not be treated as one.

Each record stores a payload digest, not the payload itself. Event types that
the contract marks pending are emitted to the structured log only and never
enter the staging chain.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.utils import ZERO_HASH, canonical_json, digest_of, new_id, now_iso, sha256_hex
from app.ports.repository import RepositoryPort

logger = logging.getLogger("etl_agent.audit")

PENDING_EVENT_TYPES = {
    "run.queued",
    "file.asset.parse_failed",
    "agent.run.failed",
    "version.diff.generated",
    "diagnosis.generated",
    "tool.call.unknown",
    "outbox.event.failed",
    "secret.rotated",
    "ledger.tamper_detected",
    "project.member.revoked",
}


class AuditService:
    def __init__(self, repository: RepositoryPort) -> None:
        self._repository = repository

    def append(
        self,
        *,
        project_id: str,
        actor_id: str,
        event_type: str,
        resource_type: str,
        resource_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        if event_type in PENDING_EVENT_TYPES:
            logger.warning(
                "audit_pending event_type=%s resource_type=%s resource_id=%s "
                "actor_id=%s ledger_status=pending_ledger",
                event_type,
                resource_type,
                resource_id,
                actor_id,
            )
            return None

        events = self._repository.list_audit_events(project_id)
        prev_hash = events[-1]["event_hash"] if events else ZERO_HASH
        created_at = now_iso()
        payload_digest = digest_of(payload)
        event = {
            "id": new_id("evt"),
            "project_id": project_id,
            "actor_id": actor_id,
            "event_type": event_type,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "payload_digest": payload_digest,
            "prev_event_hash": prev_hash,
            "created_at": created_at,
        }
        event["event_hash"] = sha256_hex(
            canonical_json({**event, "prev_event_hash": prev_hash})
        )
        self._repository.append_audit_event(event)
        logger.info(
            "audit_event event_id=%s event_type=%s resource_type=%s "
            "resource_id=%s actor_id=%s payload_digest=%s "
            "ledger_status=pending_ledger",
            event["id"],
            event_type,
            resource_type,
            resource_id,
            actor_id,
            payload_digest,
        )
        return event
