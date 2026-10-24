"""Capability token tests: issuance, verification, TTL, single consumption.

Covers Spec 3.5 / 5.1 and the user-approved requirement: Ed25519 signing,
5-minute single-use tokens bound to tool/subject/environment/artifact
fingerprint, with only jti + digest retained — never the plaintext.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from app.core.harness.capability import CapabilityService
from app.core.harness.errors import HarnessError
from harness.tests.conftest import TEST_SEED


class _FixedClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 24, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


def make_service(**kwargs) -> CapabilityService:
    kwargs.setdefault("clock", _FixedClock())
    return CapabilityService(private_key_bytes=TEST_SEED, **kwargs)


def claims(**overrides) -> dict:
    base = {
        "tool": "etl.execute",
        "sub": "ops1",
        "project_id": "p1",
        "environment": "prod",
        "resource_scope": {"version_id": "ver_1"},
        "artifact_digest": "a" * 64,
        "preparation_id": "prep_1",
        "execution_run_id": "run_1",
    }
    base.update(overrides)
    return base


def approval_facts(**overrides) -> list[dict]:
    facts = [
        {
            "decision": "APPROVED",
            "approver_id": "u2",
            "required_role": "data_checker",
        },
        {
            "decision": "APPROVED",
            "approver_id": "u3",
            "required_role": "security_checker",
        },
    ]
    if overrides:
        for fact in facts:
            fact.update(overrides)
    return facts


REQUIRED_SLOTS = ("data_checker", "security_checker")


def test_issue_and_verify_roundtrip_binds_claims():
    service = make_service()
    issued = service.issue(claims(), approval_facts=approval_facts(), required_slots=REQUIRED_SLOTS)

    assert issued["jti"].startswith("cap_")
    assert issued["token_digest"] == hashlib.sha256(
        issued["token"].encode("utf-8")
    ).hexdigest()
    assert issued["claims"]["tool"] == "etl.execute"
    assert issued["claims"]["preparation_id"] == "prep_1"

    verified = service.verify(
        issued["token"],
        {"tool": "etl.execute", "execution_run_id": "run_1"},
    )
    assert verified["status"] == "PRESENTED"
    assert verified["jti"] == issued["jti"]


def test_ttl_is_300_seconds():
    service = make_service()
    issued = service.issue(claims(), approval_facts=approval_facts(), required_slots=REQUIRED_SLOTS)

    assert issued["claims"]["exp"] - issued["claims"]["iat"] == 300
    record = service.get_record(issued["jti"])
    assert record is not None
    assert datetime.fromisoformat(record["expires_at"]) - datetime.fromisoformat(
        record["issued_at"]
    ) == timedelta(seconds=300)


def test_token_is_single_use():
    service = make_service()
    issued = service.issue(claims(), approval_facts=approval_facts(), required_slots=REQUIRED_SLOTS)

    service.verify(issued["token"], {})
    with pytest.raises(HarnessError) as presented:
        service.verify(issued["token"], {})
    assert presented.value.error_code == "CAP-409"

    service.consume(issued["jti"], issued["token_digest"])
    with pytest.raises(HarnessError) as consumed:
        service.verify(issued["token"], {})
    assert consumed.value.error_code == "CAP-409"


def test_expired_token_is_rejected_with_410():
    clock = _FixedClock()
    service = CapabilityService(private_key_bytes=TEST_SEED, clock=clock)
    issued = service.issue(claims(), approval_facts=approval_facts(), required_slots=REQUIRED_SLOTS)

    clock.now += timedelta(seconds=301)
    with pytest.raises(HarnessError) as expired:
        service.verify(issued["token"], {})
    assert expired.value.error_code == "CAP-410"
    assert expired.value.status_code == 410


def test_tampered_token_is_rejected():
    service = make_service()
    issued = service.issue(claims(), approval_facts=approval_facts(), required_slots=REQUIRED_SLOTS)

    tampered = issued["token"][:-2] + ("AA" if not issued["token"].endswith("AA") else "BB")
    with pytest.raises(HarnessError) as rejected:
        service.verify(tampered, {})
    assert rejected.value.status_code == 401


def test_execution_requires_two_independent_approvals():
    service = make_service()

    with pytest.raises(HarnessError) as missing:
        service.issue(claims(), approval_facts=[], required_slots=REQUIRED_SLOTS)
    assert missing.value.error_code == "CAP-422"

    with pytest.raises(HarnessError) as same_approver:
        service.issue(
            claims(),
            approval_facts=approval_facts(approver_id="u2"),
            required_slots=REQUIRED_SLOTS,
        )
    assert same_approver.value.error_code == "CAP-422"


def test_only_jti_and_digest_are_retained():
    service = make_service()
    issued = service.issue(claims(), approval_facts=approval_facts(), required_slots=REQUIRED_SLOTS)

    record = service.get_record(issued["jti"])
    assert record is not None
    assert record["token_digest"] == issued["token_digest"]
    flattened = repr(record)
    assert issued["token"] not in flattened  # plaintext token is never stored
