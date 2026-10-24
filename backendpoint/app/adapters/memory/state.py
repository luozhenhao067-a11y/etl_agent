"""In-memory state for entities with no Spec-defined table.

Spec 10.3 lists connection configuration, metadata profiles, Preparation,
Outbox, and Benchmark persistence as undefined. They are deliberately stored
in memory here, not created as database tables.
"""

from __future__ import annotations

from typing import Any


class MemoryState:
    def __init__(self) -> None:
        self.connections: dict[str, dict[str, Any]] = {}
        self.profiles: dict[str, dict[str, Any] | None] = {}
        self.preparations: dict[str, dict[str, Any]] = {}
        self.designs: dict[str, dict[str, Any]] = {}
        self.benchmark_runs: dict[str, dict[str, Any]] = {}
        self.agent_states: dict[str, dict[str, Any]] = {}
        self.pending_audit_events: list[dict[str, Any]] = []
        self.run_extras: dict[str, dict[str, Any]] = {}
