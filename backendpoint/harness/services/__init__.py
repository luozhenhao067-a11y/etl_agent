"""Harness services: the API-facing adapters over the kernel components.

- ``gateway`` wires the kernel (PDP, Capability), the Redis replay guard, the
  SQL Outbox and the SQL Evidence Ledger into the ``HarnessPort`` the routes
  are allowed to call. It is selected by ``HARNESS=kernel``.
- ``commit_tx`` owns the API-14 Commit transaction boundary: one PostgreSQL
  transaction writes ``execution_runs`` + Outbox + audit events, after the
  server-side recheck of the 2/2 approvals and the fingerprint facts.
"""

from harness.services.commit_tx import CommitOrchestrator
from harness.services.gateway import KernelHarnessAdapter

__all__ = ["CommitOrchestrator", "KernelHarnessAdapter"]
