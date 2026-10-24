"""Harness delivery package (Spec 3-5).

Durable execution-kernel layer: Redis replay protection, transactional
PostgreSQL outbox, tamper-evident evidence ledger and the Ed25519 key
material. The pure state machines stay in ``app.core.harness`` and are
reused here; nothing in this package duplicates them.

Structure (batch 1 = core/ + models/; batch 2 = services/ + routers/):

- ``core``      Redis client factory, Redis replay guard, SQL outbox,
                SQL evidence ledger, signing-key loading
- ``models``    ORM rows for migration 0002 (outbox_events, ledger_checkpoints)
- ``services``  API gateway adapter and Commit transaction orchestration
- ``tests``     pytest coverage for token, replay, outbox and ledger

Every SQL adapter takes the caller's ``Session`` and never commits, so
outbox/ledger writes join the business transaction (Spec 4.4 atomicity).
"""

from __future__ import annotations

__all__: list[str] = []
