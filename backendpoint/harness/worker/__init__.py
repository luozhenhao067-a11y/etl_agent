"""Spec 5.5 step 4+: Outbox dispatch and the managed execution Worker.

Three pieces, wired together in ``app.container``:

- ``PendingCommandStore`` — in-process handoff of the plaintext capability
  token from the Commit orchestrator to the dispatcher (Spec 5.1: the token
  plaintext never touches the database or the Outbox payload).
- ``OutboxDispatcher`` — claims PENDING/RETRYING events, delivers them to the
  Worker, and drives the Outbox state machine (PUBLISHED → CONSUMED, or
  RETRYING / DEAD_LETTER on transport failure).
- ``ExecutionWorker`` — consumes one ``execution.command``: run-row binding,
  capability verification, PDP re-check, broker-mediated single consumption,
  ExecPort submission and the legal run.* audit events (Spec 12.2).
"""

from __future__ import annotations

from harness.worker.commands import PendingCommandStore
from harness.worker.dispatcher import OutboxDispatcher
from harness.worker.worker import ExecutionWorker

__all__ = ["ExecutionWorker", "OutboxDispatcher", "PendingCommandStore"]
