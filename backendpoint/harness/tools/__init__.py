"""Tool Broker tool adapters (Spec 3.6, P-33 read-only/ops tools).

Each factory builds the handler registered for one Tool Broker tool. A handler
receives the broker-validated intent and returns its sanitized output dict;
adapters fail closed (``ToolUnavailableError`` / ``ToolDependencyError``)
when a downstream dependency is missing — no success is ever fabricated.
"""

from __future__ import annotations

from harness.tools.db_tools import make_conn_test_handler, make_metadata_profile_handler
from harness.tools.file_tools import make_file_parse_handler
from harness.tools.ops_tools import (
    make_benchmark_run_handler,
    make_run_cancel_handler,
    make_shadow_rollback_handler,
)
from harness.tools.secret_tools import make_secret_materialize_handler
from harness.tools.registry import register_tool_handlers

__all__ = [
    "make_benchmark_run_handler",
    "make_conn_test_handler",
    "make_file_parse_handler",
    "make_metadata_profile_handler",
    "make_run_cancel_handler",
    "make_secret_materialize_handler",
    "make_shadow_rollback_handler",
    "register_tool_handlers",
]
