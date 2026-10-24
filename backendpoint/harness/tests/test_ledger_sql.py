"""Evidence Ledger tests: hash-chain continuity, tamper detection, checkpoints.

Covers Spec 3.9 / 5.4 and the user-approved requirement: SHA256 chain over
canonical JSON, append-only (UPDATE/DELETE rejected by database triggers on
PostgreSQL), per-project chains, signed checkpoints. The database-level
trigger behaviour itself is covered by tests/test_schema.py.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from app.core.harness.errors import HarnessError
from harness.core.ledger_sql import SqlLedger

ZERO_HASH = "0" * 64


def ledger_event(**overrides) -> dict:
    event = {
        "project_id": "p1",
        "actor_id": "u1",
        "event_type": "pdp.decision.recorded",
        "resource_type": "pdp_decision",
        "resource_id": "dec_1",
        "payload_digest": "c" * 64,
    }
    event.update(overrides)
    return event


async def _append_three(ledger, session_factory):
    for index in range(1, 4):
        with session_factory() as session:
            await ledger.append(session, ledger_event(resource_id=f"dec_{index}"))
            session.commit()


async def test_chain_is_continuous_and_verifies(ledger, seeded_engine, session_factory):
    await _append_three(ledger, session_factory)

    with session_factory() as session:
        report = ledger.verify(session, "p1")
    assert report["status"] == "VERIFIED"
    assert report["entries"] == 3
    assert report["external_entries"] == 0

    with session_factory() as session:
        rows = session.execute(
            text(
                "SELECT chain_seq, prev_event_hash, event_hash FROM audit_events "
                "WHERE project_id='p1' ORDER BY chain_seq"
            )
        ).all()
    assert [row[0] for row in rows] == [1, 2, 3]
    assert rows[0][1] == ZERO_HASH
    assert rows[1][1] == rows[0][2]
    assert rows[2][1] == rows[1][2]


async def test_tampering_is_detected(ledger, seeded_engine, session_factory):
    await _append_three(ledger, session_factory)

    # Append-only is enforced by triggers on PostgreSQL; on the SQLite test
    # stand-in we simulate an attacker writing directly behind the ledger.
    with session_factory() as session:
        session.execute(
            text("UPDATE audit_events SET event_type='tampered' WHERE chain_seq=2")
        )
        session.commit()

    with session_factory() as session:
        report = ledger.verify(session, "p1")
    assert report["status"] == "BROKEN"
    assert report["broken_at"] == 2


async def test_projects_have_independent_chains(ledger, seeded_engine, session_factory):
    with session_factory() as session:
        await ledger.append(session, ledger_event(resource_id="p1_event"))
        session.commit()
    with session_factory() as session:
        await ledger.append(
            session, ledger_event(project_id="p2", resource_id="p2_event")
        )
        session.commit()

    with session_factory() as session:
        for project_id in ("p1", "p2"):
            report = ledger.verify(session, project_id)
            assert report["status"] == "VERIFIED"
            assert report["entries"] == 1
        row = session.execute(
            text(
                "SELECT prev_event_hash FROM audit_events "
                "WHERE project_id='p2'"
            )
        ).scalar_one()
    assert row == ZERO_HASH


async def test_external_writers_are_counted_not_fatal(
    ledger, seeded_engine, session_factory
):
    await _append_three(ledger, session_factory)
    with session_factory() as session:
        session.execute(
            text(
                "INSERT INTO audit_events (id, project_id, actor_id, event_type, "
                "resource_type, resource_id, payload_digest, prev_event_hash, "
                "event_hash, created_at) VALUES "
                "('evt_legacy','p1','u1','connection.created','connection','c1',"
                ":payload,:prev,:event,:now)"
            ),
            {"payload": "d" * 64, "prev": ZERO_HASH, "event": "e" * 64, "now": "2026-10-24T00:00:00+00:00"},
        )
        session.commit()

    with session_factory() as session:
        report = ledger.verify(session, "p1")
    assert report["status"] == "VERIFIED"
    assert report["entries"] == 3
    assert report["external_entries"] == 1


async def test_duplicate_event_id_is_rejected(ledger, seeded_engine, session_factory):
    with session_factory() as session:
        await ledger.append(session, ledger_event(event_id="evt_dup"))
        session.commit()
    with session_factory() as session:
        with pytest.raises(HarnessError) as duplicate:
            await ledger.append(session, ledger_event(event_id="evt_dup"))
        session.rollback()
    assert duplicate.value.error_code == "EL-409"


async def test_supplied_hash_mismatch_is_rejected(ledger, seeded_engine, session_factory):
    with session_factory() as session:
        with pytest.raises(HarnessError) as mismatch:
            await ledger.append(session, ledger_event(event_hash="f" * 64))
        session.rollback()
    assert mismatch.value.error_code == "EL-422"


async def test_supplied_prev_conflict_is_rejected(ledger, seeded_engine, session_factory):
    await _append_three(ledger, session_factory)
    with session_factory() as session:
        with pytest.raises(HarnessError) as conflict:
            await ledger.append(
                session, ledger_event(prev_event_hash=ZERO_HASH)
            )
        session.rollback()
    assert conflict.value.error_code == "EL-409"


async def test_checkpoint_roundtrip_and_tamper(ledger, seeded_engine, session_factory):
    await _append_three(ledger, session_factory)
    with session_factory() as session:
        checkpoint = ledger.checkpoint(session, "p1")
        session.commit()

    assert checkpoint["last_sequence"] == 3
    ledger.verify_checkpoint(checkpoint)

    tampered = {**checkpoint, "last_event_hash": "f" * 64}
    with pytest.raises(HarnessError):
        ledger.verify_checkpoint(tampered)


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="needs a real PostgreSQL via TEST_DATABASE_URL",
)
def test_concurrent_appends_keep_absolute_chain_order():
    """The advisory-lock path (pg_advisory_xact_lock) under real concurrency."""
    import asyncio

    from sqlalchemy import create_engine as pg_create_engine
    from sqlalchemy.orm import sessionmaker

    from harness.tests.conftest import fixed_private_key

    async def append_async(session, ledger, index):
        await ledger.append(
            session, ledger_event(actor_id=f"u{index}", resource_id=f"dec_{index}")
        )

    engine = pg_create_engine(os.environ["TEST_DATABASE_URL"])
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    ledger = SqlLedger(private_key=fixed_private_key())

    def append_one(index: int) -> None:
        with factory() as session:
            session.execute(
                text(
                    "INSERT INTO users (id, username, display_name, email, "
                    "status, created_at, updated_at) VALUES "
                    "(:id, :id, 'U', :email, 'active', now(), now()) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"id": f"u{index}", "email": f"u{index}@example.com"},
            )
            session.commit()
        with factory() as session:
            session.execute(
                text(
                    "INSERT INTO projects (id, name, code, description, "
                    "created_at, updated_at) VALUES ('p1','P','P',NULL,"
                    "now(),now()) ON CONFLICT (id) DO NOTHING"
                )
            )
            session.commit()
        with factory() as session:
            asyncio.run(_append_async(session, ledger, index))
            session.commit()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(append_one, range(8)))

    with factory() as session:
        report = ledger.verify(session, "p1")
    engine.dispose()
    assert report["status"] == "VERIFIED"
    assert report["entries"] == 8
