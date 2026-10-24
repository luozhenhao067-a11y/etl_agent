"""Append-only Evidence Ledger with a per-project hash chain (Spec 3.9 / 5.4).

The in-memory order is used only for this adapter's verification. P-09 has not
defined a persisted chain sequence, so no sequence column is added to
``audit_events`` and ``created_at`` is never treated as the chain order. A
durable deployment needs the sequence decision before this adapter can be
replaced.

Checkpoints are Ed25519-signed. Checkpoint frequency remains pending P-32.
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.core.harness.errors import HarnessError
from app.core.harness.models import (
    Clock,
    assert_no_secret_material,
    is_digest,
    isoformat,
    require_nonempty,
    utcnow,
)
from app.core.utils import ZERO_HASH, canonical_json, sha256_hex


class EvidenceLedger:
    def __init__(
        self,
        *,
        clock: Clock = utcnow,
        private_key: Ed25519PrivateKey | None = None,
    ) -> None:
        self._clock = clock
        self._private_key = private_key or Ed25519PrivateKey.generate()
        self._public_key: Ed25519PublicKey = self._private_key.public_key()
        self._chains: dict[str, list[dict[str, Any]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._checkpoints: list[dict[str, Any]] = []

    async def append(self, event: dict[str, Any]) -> dict[str, Any]:
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
                raise ValueError("payload_digest must be a 64-character lowercase SHA256")
            occurred_at = event.get("occurred_at") or isoformat(self._clock())
            if not isinstance(occurred_at, str):
                raise ValueError("occurred_at must be an ISO-8601 string")
            correlation_id = event.get("correlation_id")
            if correlation_id is not None and not isinstance(correlation_id, str):
                raise ValueError("correlation_id must be a string")
            assert_no_secret_material(event)
        except ValueError as exc:
            raise HarnessError(422, "EL-422", str(exc)) from None

        lock = self._locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            chain = self._chains.setdefault(project_id, [])
            prev_hash = chain[-1]["event_hash"] if chain else ZERO_HASH
            supplied_prev = event.get("prev_event_hash")
            if supplied_prev is not None and supplied_prev != prev_hash:
                raise HarnessError(409, "EL-409", "ledger chain head conflict")
            supplied_hash = event.get("event_hash")
            hash_input = {
                "prev_event_hash": prev_hash,
                "project_id": project_id,
                "actor_id": actor_id,
                "event_type": event_type,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "payload_digest": payload_digest,
                "occurred_at": occurred_at,
            }
            event_hash = sha256_hex(canonical_json(hash_input))
            if supplied_hash is not None and supplied_hash != event_hash:
                raise HarnessError(422, "EL-422", "supplied event_hash does not match")
            event_id = event.get("event_id") or f"evt_{uuid.uuid4().hex[:16]}"
            if any(row["id"] == event_id for row in chain):
                raise HarnessError(409, "EL-409", "ledger event id already exists")
            entry = {
                "id": event_id,
                "project_id": project_id,
                "actor_id": actor_id,
                "event_type": event_type,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "payload_digest": payload_digest,
                "occurred_at": occurred_at,
                "correlation_id": correlation_id,
                "prev_event_hash": prev_hash,
                "event_hash": event_hash,
                "created_at": isoformat(self._clock()),
                "_sequence": len(chain) + 1,
            }
            chain.append(entry)
            return self._safe_entry(entry)

    def entries(self, project_id: str) -> list[dict[str, Any]]:
        return [self._safe_entry(row) for row in self._chains.get(project_id, [])]

    def verify(self, project_id: str) -> dict[str, Any]:
        chain = self._chains.get(project_id, [])
        prev_hash = ZERO_HASH
        for index, entry in enumerate(chain, start=1):
            if entry["prev_event_hash"] != prev_hash:
                return {
                    "status": "BROKEN",
                    "project_id": project_id,
                    "broken_at": index,
                    "reason": "prev_event_hash_mismatch",
                }
            expected = self._event_hash(entry)
            if entry["event_hash"] != expected:
                return {
                    "status": "BROKEN",
                    "project_id": project_id,
                    "broken_at": index,
                    "reason": "event_hash_mismatch",
                }
            prev_hash = entry["event_hash"]
        return {
            "status": "VERIFIED",
            "project_id": project_id,
            "entries": len(chain),
            "last_event_hash": prev_hash,
        }

    def checkpoint(self, project_id: str) -> dict[str, Any]:
        chain = self._chains.get(project_id, [])
        last_sequence = len(chain)
        last_event_hash = chain[-1]["event_hash"] if chain else ZERO_HASH
        payload = {
            "last_sequence": last_sequence,
            "last_event_hash": last_event_hash,
            "checkpoint_at": isoformat(self._clock()),
        }
        signature = self._private_key.sign(canonical_json(payload).encode("utf-8"))
        checkpoint = {
            "project_id": project_id,
            **payload,
            "algorithm": "Ed25519",
            "public_key": _b64url_encode(self._public_key.public_bytes_raw()),
            "signature": _b64url_encode(signature),
        }
        self._checkpoints.append(deepcopy(checkpoint))
        return deepcopy(checkpoint)

    def verify_checkpoint(self, checkpoint: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(checkpoint, dict):
            raise HarnessError(410, "EL-410", "checkpoint is invalid")
        payload = {
            "last_sequence": checkpoint.get("last_sequence"),
            "last_event_hash": checkpoint.get("last_event_hash"),
            "checkpoint_at": checkpoint.get("checkpoint_at"),
        }
        if (
            not isinstance(payload["last_sequence"], int)
            or payload["last_sequence"] < 0
            or not is_digest(payload["last_event_hash"])
            or not isinstance(payload["checkpoint_at"], str)
            or checkpoint.get("algorithm") != "Ed25519"
        ):
            raise HarnessError(410, "EL-410", "checkpoint is invalid")
        try:
            signature = _b64url_decode(checkpoint["signature"])
            self._public_key.verify(signature, canonical_json(payload).encode("utf-8"))
        except (KeyError, ValueError, InvalidSignature, TypeError):
            raise HarnessError(410, "EL-410", "checkpoint signature is invalid") from None
        return {
            "status": "VERIFIED",
            "project_id": checkpoint.get("project_id"),
            "last_sequence": payload["last_sequence"],
            "last_event_hash": payload["last_event_hash"],
        }

    def checkpoints(self) -> list[dict[str, Any]]:
        return deepcopy(self._checkpoints)

    @staticmethod
    def _event_hash(entry: dict[str, Any]) -> str:
        return sha256_hex(
            canonical_json(
                {
                    "prev_event_hash": entry["prev_event_hash"],
                    "project_id": entry["project_id"],
                    "actor_id": entry["actor_id"],
                    "event_type": entry["event_type"],
                    "resource_type": entry["resource_type"],
                    "resource_id": entry["resource_id"],
                    "payload_digest": entry["payload_digest"],
                    "occurred_at": entry["occurred_at"],
                }
            )
        )

    @staticmethod
    def _safe_entry(entry: dict[str, Any]) -> dict[str, Any]:
        return deepcopy({key: value for key, value in entry.items() if not key.startswith("_")})


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
