"""Ed25519 single-use Capability issuer and verifier (Spec 3.5 / 5.1).

The compact token is a JWS-like ``header.payload.signature`` value with an
EdDSA header. The token itself is returned once to the caller and never stored
or logged. The service retains only ``jti`` and ``token_digest``.

Token encoding and key lifecycle are still pending P-31. The encoding here is a
concrete kernel implementation, not a frozen contract for an external issuer.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from copy import deepcopy
from datetime import timedelta
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.core.harness.errors import HarnessError
from app.core.harness.models import (
    CAPABILITY_CONSUMED,
    CAPABILITY_EXPIRED,
    CAPABILITY_ISSUED,
    CAPABILITY_PRESENTED,
    CAPABILITY_REJECTED,
    ENVIRONMENTS,
    Clock,
    assert_no_secret_material,
    epoch_seconds,
    isoformat,
    require_nonempty,
    utcnow,
)
from app.core.utils import canonical_json

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_HEADER = {"alg": "EdDSA", "typ": "JWT"}
_SCOPE_CLAIMS = {"sub", "project_id", "environment", "tool", "resource_scope"}
_BINDING_CLAIMS = {
    "artifact_digest",
    "preparation_id",
    "execution_run_id",
}


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


class CapabilityService:
    def __init__(
        self,
        *,
        private_key: Ed25519PrivateKey | None = None,
        private_key_bytes: bytes | None = None,
        ttl_seconds: int = 300,
        clock: Clock = utcnow,
        require_approval_facts: bool = True,
    ) -> None:
        if private_key is not None and private_key_bytes is not None:
            raise ValueError("provide one of private_key or private_key_bytes")
        if private_key_bytes is not None:
            private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
        if ttl_seconds <= 0:
            raise ValueError("capability TTL must be positive")
        self._private_key = private_key or Ed25519PrivateKey.generate()
        self._public_key: Ed25519PublicKey = self._private_key.public_key()
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._require_approval_facts = require_approval_facts
        self._records: dict[str, dict[str, Any]] = {}

    @property
    def public_key_b64(self) -> str:
        raw = self._public_key.public_bytes_raw()
        return _b64url_encode(raw)

    def issue(
        self,
        claims: dict[str, Any],
        *,
        approval_facts: list[dict[str, Any]] | None = None,
        required_slots: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        prepared, facts = self._prepare_claims(claims, approval_facts)
        if self._require_approval_facts:
            applicant_id = claims.get("applicant_id") or claims.get("requested_by")
            self._validate_approval_facts(
                prepared,
                facts,
                applicant_id=applicant_id,
                required_slots=required_slots,
            )

        now = self._clock()
        iat = epoch_seconds(now)
        jti = f"cap_{uuid.uuid4().hex}"
        token_claims = {
            "jti": jti,
            "sub": prepared["sub"],
            "project_id": prepared["project_id"],
            "environment": prepared["environment"],
            "tool": prepared["tool"],
            "resource_scope": deepcopy(prepared["resource_scope"]),
            "artifact_digest": prepared["artifact_digest"],
            "preparation_id": prepared["preparation_id"],
            "execution_run_id": prepared["execution_run_id"],
            "iat": iat,
            "exp": iat + self._ttl_seconds,
        }
        try:
            token = self._sign(token_claims)
        except Exception:
            raise HarnessError(500, "CAP-500", "capability signer is unavailable") from None
        token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        record = {
            "jti": jti,
            "token_digest": token_digest,
            "claims": deepcopy(token_claims),
            "status": CAPABILITY_ISSUED,
            "issued_at": isoformat(now),
            "expires_at": isoformat(now + timedelta(seconds=self._ttl_seconds)),
        }
        self._records[jti] = record
        return {
            "token": token,
            "jti": jti,
            "token_digest": token_digest,
            "claims": deepcopy(token_claims),
            "expires_at": record["expires_at"],
        }

    def verify(
        self, token: str, expected_claims: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        parsed = self._verify_signature(token)
        claims = parsed["claims"]
        jti = claims.get("jti")
        token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()

        if not isinstance(jti, str) or not jti:
            raise HarnessError(422, "CAP-422", "capability jti is missing")
        if (
            not isinstance(claims.get("iat"), int)
            or isinstance(claims.get("iat"), bool)
            or not isinstance(claims.get("exp"), int)
            or isinstance(claims.get("exp"), bool)
            or claims["exp"] <= claims["iat"]
        ):
            raise HarnessError(422, "CAP-422", "capability time claims are invalid")
        record = self._records.get(jti)
        if record is None:
            raise HarnessError(422, "CAP-422", "capability was not issued by this verifier")
        if record["token_digest"] != token_digest:
            raise HarnessError(401, "CAP-401", "capability digest does not match the issued token")

        self._expire_if_needed(record)

        if record["status"] == CAPABILITY_CONSUMED:
            raise HarnessError(409, "CAP-409", "capability has already been consumed")
        if record["status"] == CAPABILITY_EXPIRED:
            raise HarnessError(410, "CAP-410", "capability has expired")
        if record["status"] == CAPABILITY_REJECTED:
            raise HarnessError(409, "CAP-409", "capability was rejected")
        if record["status"] == CAPABILITY_PRESENTED:
            raise HarnessError(409, "CAP-409", "capability has already been presented")

        self._compare_claims(claims, expected_claims or {})
        record["status"] = CAPABILITY_PRESENTED
        record["presented_at"] = isoformat(self._clock())
        return {
            "status": record["status"],
            "jti": jti,
            "token_digest": token_digest,
            "claims": deepcopy(claims),
        }

    def consume(self, jti: str, token_digest: str) -> dict[str, Any]:
        record = self._records.get(jti)
        if record is None:
            raise HarnessError(422, "CAP-422", "capability was not issued by this verifier")
        if record["token_digest"] != token_digest:
            raise HarnessError(401, "CAP-401", "capability digest does not match the issued token")
        self._expire_if_needed(record)
        if record["status"] == CAPABILITY_CONSUMED:
            raise HarnessError(409, "CAP-409", "capability has already been consumed")
        if record["status"] == CAPABILITY_EXPIRED:
            raise HarnessError(410, "CAP-410", "capability has expired")
        if record["status"] != CAPABILITY_PRESENTED:
            raise HarnessError(409, "CAP-409", "capability must be presented before consumption")
        record["status"] = CAPABILITY_CONSUMED
        record["consumed_at"] = isoformat(self._clock())
        return self._safe_record(record)

    def reject(self, jti: str, reason: str) -> dict[str, Any]:
        record = self._records.get(jti)
        if record is None:
            raise HarnessError(422, "CAP-422", "capability was not issued by this verifier")
        if record["status"] == CAPABILITY_CONSUMED:
            raise HarnessError(409, "CAP-409", "capability has already been consumed")
        record["status"] = CAPABILITY_REJECTED
        record["rejected_at"] = isoformat(self._clock())
        record["reject_reason"] = reason
        return self._safe_record(record)

    def get_record(self, jti: str) -> dict[str, Any] | None:
        record = self._records.get(jti)
        if record is None:
            return None
        self._expire_if_needed(record)
        return self._safe_record(record)

    def decode_claims(self, token: str) -> dict[str, Any]:
        """Read-only inspection of the token payload — no state change.

        The dispatch Worker decodes the claims to rebuild the intent before
        handing the token to the broker, whose ``verify`` remains the single
        authoritative presentation (a second ``verify`` would fail with
        CAP-409). Authenticity here comes from the digest binding instead:
        the SHA256 of these exact token bytes is the unique digest recorded
        at Commit, so a forged token cannot match the run row.
        """
        try:
            _header_b64, payload_b64, _signature_b64 = token.split(".")
            claims = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        except Exception:
            raise HarnessError(422, "CAP-422", "capability token is malformed") from None
        if not isinstance(claims, dict):
            raise HarnessError(422, "CAP-422", "capability claims are malformed")
        return claims

    def _prepare_claims(
        self,
        claims: dict[str, Any],
        approval_facts: list[dict[str, Any]] | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if not isinstance(claims, dict):
            raise HarnessError(422, "CAP-422", "capability claims must be an object")
        try:
            assert_no_secret_material(claims)
            sub = require_nonempty(claims.get("sub") or claims.get("actor_id"), "sub")
            project_id = require_nonempty(claims.get("project_id"), "project_id")
            environment = require_nonempty(claims.get("environment"), "environment")
            if environment not in ENVIRONMENTS:
                raise ValueError("environment must be prod, preprod or test")
            tool = require_nonempty(claims.get("tool"), "tool")
            resource_scope = claims.get("resource_scope")
            if not isinstance(resource_scope, dict) or not resource_scope:
                raise ValueError("resource_scope is required")
            artifact_digest = require_nonempty(
                claims.get("artifact_digest"), "artifact_digest"
            )
            if not _DIGEST.fullmatch(artifact_digest):
                raise ValueError("artifact_digest must be a 64-character lowercase SHA256")
            preparation_id = require_nonempty(
                claims.get("preparation_id"), "preparation_id"
            )
            execution_run_id = require_nonempty(
                claims.get("execution_run_id"), "execution_run_id"
            )
        except ValueError as exc:
            raise HarnessError(422, "CAP-422", str(exc)) from None
        prepared = {
            "sub": sub,
            "project_id": project_id,
            "environment": environment,
            "tool": tool,
            "resource_scope": resource_scope,
            "artifact_digest": artifact_digest,
            "preparation_id": preparation_id,
            "execution_run_id": execution_run_id,
        }
        facts = approval_facts if approval_facts is not None else claims.get("approval_facts")
        if facts is None:
            facts = []
        if not isinstance(facts, list):
            raise HarnessError(422, "CAP-422", "approval_facts must be a list")
        return prepared, facts

    def _validate_approval_facts(
        self,
        claims: dict[str, Any],
        facts: list[dict[str, Any]],
        *,
        applicant_id: str | None = None,
        required_slots: tuple[str, ...] | None = None,
    ) -> None:
        approved = [
            fact
            for fact in facts
            if isinstance(fact, dict)
            # Spec 4.6: approval status is uppercase; normalize defensively.
            and (
                str(fact.get("decision") or fact.get("status") or "").upper() == "APPROVED"
            )
        ]
        approvers = {fact.get("approver_id") for fact in approved if fact.get("approver_id")}
        if len(approved) < 2 or len(approvers) < 2:
            raise HarnessError(
                422,
                "CAP-422",
                "commit requires two independent approved slots",
                {"reason": "APPROVAL_INCOMPLETE"},
            )
        role_slots = {
            fact.get("role_slot") or fact.get("required_role")
            for fact in approved
            if fact.get("role_slot") or fact.get("required_role")
        }
        if role_slots and len(role_slots) < 2:
            raise HarnessError(
                422,
                "CAP-422",
                "commit requires two distinct approval slots",
                {"reason": "approval_slots_not_independent"},
            )
        if required_slots:
            missing = sorted(set(required_slots) - role_slots)
            if missing:
                raise HarnessError(
                    422,
                    "CAP-422",
                    "approval facts do not cover required slots",
                    {"reason": "approval_slots_missing", "missing": missing},
                )
        if applicant_id and applicant_id in approvers:
            raise HarnessError(
                422,
                "CAP-422",
                "applicant cannot approve the same preparation",
                {"reason": "self_approval"},
            )
        for fact in approved:
            if fact.get("artifact_digest") not in (None, claims["artifact_digest"]):
                raise HarnessError(
                    422,
                    "CAP-422",
                    "approval fact artifact digest does not match",
                    {"reason": "fingerprint_mismatch"},
                )
            if fact.get("preparation_id") not in (None, claims["preparation_id"]):
                raise HarnessError(
                    422,
                    "CAP-422",
                    "approval fact preparation does not match",
                    {"reason": "preparation_mismatch"},
                )

    def _sign(self, claims: dict[str, Any]) -> str:
        header = _b64url_encode(canonical_json(_HEADER).encode("utf-8"))
        payload = _b64url_encode(canonical_json(claims).encode("utf-8"))
        signing_input = f"{header}.{payload}".encode("ascii")
        signature = self._private_key.sign(signing_input)
        return f"{header}.{payload}.{_b64url_encode(signature)}"

    def _verify_signature(self, token: str) -> dict[str, Any]:
        if not isinstance(token, str):
            raise HarnessError(401, "CAP-401", "capability token is invalid")
        parts = token.split(".")
        if len(parts) != 3:
            raise HarnessError(401, "CAP-401", "capability token is invalid")
        header_b64, payload_b64, signature_b64 = parts
        try:
            header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
            claims = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
            signature = _b64url_decode(signature_b64)
        except Exception:
            raise HarnessError(401, "CAP-401", "capability token is invalid") from None
        if header != _HEADER or not isinstance(claims, dict):
            raise HarnessError(401, "CAP-401", "capability token header is invalid")
        try:
            self._public_key.verify(
                signature, f"{header_b64}.{payload_b64}".encode("ascii")
            )
        except InvalidSignature:
            raise HarnessError(401, "CAP-401", "capability signature is invalid") from None
        return {"header": header, "claims": claims}

    def _compare_claims(
        self, claims: dict[str, Any], expected_claims: dict[str, Any]
    ) -> None:
        for key, expected in expected_claims.items():
            if key in {"actor_id", "applicant_id", "approval_facts", "requested_budget"}:
                continue
            actual = claims.get(key)
            if actual != expected:
                if key in _SCOPE_CLAIMS:
                    raise HarnessError(
                        403,
                        "CAP-403",
                        "capability scope does not match",
                        {"field": key},
                    )
                if key in _BINDING_CLAIMS:
                    raise HarnessError(
                        422,
                        "CAP-422",
                        "capability binding claim does not match",
                        {"field": key},
                    )
                raise HarnessError(
                    422,
                    "CAP-422",
                    "capability claim does not match",
                    {"field": key},
                )

    def _expire_if_needed(self, record: dict[str, Any]) -> None:
        if record["status"] in {CAPABILITY_CONSUMED, CAPABILITY_REJECTED, CAPABILITY_EXPIRED}:
            return
        if epoch_seconds(self._clock()) >= record["claims"]["exp"]:
            record["status"] = CAPABILITY_EXPIRED
            record["expired_at"] = isoformat(self._clock())

    def _safe_record(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "jti": record["jti"],
            "token_digest": record["token_digest"],
            "claims": deepcopy(record["claims"]),
            "status": record["status"],
            "issued_at": record["issued_at"],
            "expires_at": record["expires_at"],
        }
