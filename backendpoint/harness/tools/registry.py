"""Registration entry for the Tool Broker tool adapters.

Called once from the composition root (kernel mode). The ops handlers
(``run.cancel`` / ``shadow.rollback``) own the SQL transaction that records
the control-plane fact together with its ledger events, mirroring the
Commit orchestrator boundary; the read-only tools depend on the SecretPort
and a real database driver at call time.
"""

from __future__ import annotations

from typing import Any

from app.core.harness.kernel import HarnessKernel
from harness.tools.db_tools import make_conn_test_handler, make_metadata_profile_handler
from harness.tools.file_tools import make_file_parse_handler
from harness.tools.ops_tools import (
    make_benchmark_run_handler,
    make_run_cancel_handler,
    make_shadow_rollback_handler,
)
from harness.tools.secret_tools import make_secret_materialize_handler


def register_tool_handlers(
    kernel: HarnessKernel,
    *,
    session_factory: Any,
    ledger: Any,
    secret: Any,
    exec_port: Any | None = None,
    clock: Any | None = None,
) -> tuple[str, ...]:
    """Register all implemented tool handlers on the kernel's broker."""

    kwargs = {"clock": clock} if clock is not None else {}
    handlers = {
        "conn.test": make_conn_test_handler(secret=secret, **kwargs),
        "metadata.profile": make_metadata_profile_handler(secret=secret, **kwargs),
        "file.parse": make_file_parse_handler(**kwargs),
        "benchmark.run": make_benchmark_run_handler(**kwargs),
        "run.cancel": make_run_cancel_handler(
            session_factory=session_factory, ledger=ledger, exec_port=exec_port, **kwargs
        ),
        "shadow.rollback": make_shadow_rollback_handler(
            session_factory=session_factory, ledger=ledger, **kwargs
        ),
        "secret.materialize": make_secret_materialize_handler(secret=secret),
    }
    for tool, handler in handlers.items():
        kernel.broker.register_handler(tool, handler)
    return tuple(handlers)


__all__ = ["register_tool_handlers"]
