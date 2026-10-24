"""``etl.execute`` tool adapter — the only path that submits engine jobs.

Registered by the ``ExecutionWorker`` on the kernel's broker, so a job can
only be submitted from a verified single-use execution context (Spec 5.5
steps 8-9): the broker has already bound the capability to the intent's
``artifact_digest`` / ``preparation_id`` / ``execution_run_id`` claims.

The managed artifact (the immutable HOCON plan) is loaded from SQL inside
the handler — the intent itself never carries pipeline text, which keeps the
PDP credential-material guard meaningful. Credentials are materialised by
the execution environment downstream, never inside this command payload.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.harness.broker import ToolDependencyError, ToolUnavailableError
from app.core.harness.errors import HarnessError
from app.core.harness.models import is_digest, utcnow
from app.models.tables import PipelineVersion
from harness.services.gateway import SessionFactory

Clock = Callable[..., Any]


def make_etl_execute_handler(
    *, exec_port: Any, session_factory: SessionFactory, clock: Clock = utcnow
) -> Any:
    async def handler(intent: dict[str, Any]) -> dict[str, Any]:
        scope = intent.get("resource_scope") or {}
        version_id = scope.get("version_id")
        if not isinstance(version_id, str) or not version_id.strip():
            raise HarnessError(400, "TB-400", "version_id is required")
        artifact_digest = intent.get("artifact_digest")

        # The immutable plan is the managed artifact; anything else refuses
        # to execute (fail closed) rather than running unverified text.
        session: Session = session_factory()
        try:
            row = session.execute(
                select(PipelineVersion).where(PipelineVersion.id == version_id.strip())
            ).scalar_one_or_none()
        except SQLAlchemyError as exc:
            raise ToolUnavailableError("pipeline version store is unavailable") from exc
        finally:
            session.close()
        if row is None:
            raise ToolDependencyError(f"pipeline version {version_id} does not exist")
        if not row.is_immutable:
            raise ToolDependencyError("pipeline version is not immutable")
        if row.artifact_digest and artifact_digest and row.artifact_digest != artifact_digest:
            raise ToolDependencyError("pipeline version digest drift from the approval")
        if not is_digest(artifact_digest or ""):
            raise ToolDependencyError("command carries no bound artifact digest")

        command = {
            "execution_run_id": intent.get("execution_run_id"),
            "preparation_id": intent.get("preparation_id"),
            "version_id": version_id.strip(),
            "artifact_digest": artifact_digest,
            "hocon": row.hocon_text,
        }
        try:
            result = await exec_port.submit_job(command)
        except NotImplementedError as exc:
            # No engine is wired: a deterministic TB-503 — never a fabricated
            # job ID. The Worker records the run as failed with this code.
            raise ToolUnavailableError("execution engine is not available") from exc

        engine_job_id = result.get("engine_job_id")
        if not isinstance(engine_job_id, str) or not engine_job_id.strip():
            raise ToolDependencyError("execution engine returned no job reference")
        return {
            "external_ref": engine_job_id.strip(),
            "engine_status": str(result.get("status") or "SUBMITTED"),
        }

    return handler


__all__ = ["make_etl_execute_handler"]
