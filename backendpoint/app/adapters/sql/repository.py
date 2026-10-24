"""PostgreSQL implementation of RepositoryPort (SQLAlchemy 2.0 ORM).

Rows stay plain dictionaries with ISO-8601 timestamp strings at the boundary
— identical to the in-memory adapter — so the API layer, Pydantic schemas and
the frontend contract are unchanged. Datetime columns convert here; JSONB
columns pass dicts through natively.

Each port method opens its own short session and commits, matching the
repository-per-operation access pattern of the API layer. Immutability rules
are enforced twice: the ORM guards (app.db.guards) fire on flush, and the
database triggers from migration 0001 remain the outer line of defence.

List ordering is ``created_at, id`` — the stable equivalent of the insertion
order the in-memory dictionaries provide; the audit hash chain relies on it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, select
from sqlalchemy.orm import sessionmaker

from app.core.utils import to_iso
from app.models.tables import (
    AgentRun,
    ApprovalRequest,
    AuditEvent,
    ExecutionRun,
    FileAsset,
    Pipeline,
    PipelineArtifact,
    PipelineVersion,
    Project,
    ProjectMembership,
    ProjectRoleGrant,
    RuntimeSupervisionSnapshot,
    User,
)

Row = dict[str, Any]

_MODELS = (
    User,
    Project,
    ProjectMembership,
    ProjectRoleGrant,
    Pipeline,
    PipelineVersion,
    PipelineArtifact,
    AgentRun,
    ApprovalRequest,
    ExecutionRun,
    FileAsset,
    RuntimeSupervisionSnapshot,
    AuditEvent,
)


class SqlRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory
        self._datetime_columns = {
            model: frozenset(
                column.name
                for column in model.__table__.columns
                if isinstance(column.type, DateTime)
            )
            for model in _MODELS
        }

    # -- boundary conversion ------------------------------------------------

    def _to_db(self, model, row: Row) -> dict[str, Any]:
        """ISO timestamp strings in, ORM-ready values out."""

        dt_columns = self._datetime_columns[model]
        out: dict[str, Any] = {}
        for key, value in row.items():
            if key in dt_columns and isinstance(value, str):
                value = datetime.fromisoformat(value)
            out[key] = value
        return out

    def _from_db(self, model, instance) -> Row:
        """ORM instance out, row dict with ISO timestamps in CST back."""

        row: Row = {}
        for column in model.__table__.columns:
            value = getattr(instance, column.name)
            if isinstance(column.type, DateTime) and value is not None:
                value = to_iso(value)
            row[column.name] = value
        return row

    # -- generic runners -----------------------------------------------------

    def _get_one(self, model, *criteria) -> Row | None:
        with self._session_factory() as session:
            instance = session.execute(
                select(model).where(*criteria)
            ).scalars().first()
            return self._from_db(model, instance) if instance is not None else None

    def _list(self, model, *criteria) -> list[Row]:
        statement = select(model).order_by(model.created_at, model.id)
        if criteria:
            statement = statement.where(*criteria)
        with self._session_factory() as session:
            instances = session.execute(statement).scalars().all()
            return [self._from_db(model, instance) for instance in instances]

    def _create(self, model, row: Row) -> Row:
        with self._session_factory() as session, session.begin():
            instance = model(**self._to_db(model, row))
            session.add(instance)
            session.flush()
            return self._from_db(model, instance)

    def _update(self, model, row_id: str, fields: Row) -> Row | None:
        with self._session_factory() as session, session.begin():
            instance = session.get(model, row_id)
            if instance is None:
                return None
            for key, value in self._to_db(model, fields).items():
                setattr(instance, key, value)
            session.flush()
            return self._from_db(model, instance)

    # users
    def get_user(self, user_id: str) -> Row | None:
        return self._get_one(User, User.id == user_id)

    def get_user_by_username(self, username: str) -> Row | None:
        return self._get_one(User, User.username == username)

    def list_users(self) -> list[Row]:
        return self._list(User)

    def create_user(self, row: Row) -> Row:
        return self._create(User, row)

    # projects
    def get_project(self, project_id: str) -> Row | None:
        return self._get_one(Project, Project.id == project_id)

    def list_projects(self) -> list[Row]:
        return self._list(Project)

    def create_project(self, row: Row) -> Row:
        return self._create(Project, row)

    # project_memberships
    def get_membership(self, project_id: str, user_id: str) -> Row | None:
        return self._get_one(
            ProjectMembership,
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user_id,
        )

    def list_memberships(self, project_id: str) -> list[Row]:
        return self._list(ProjectMembership, ProjectMembership.project_id == project_id)

    def create_membership(self, row: Row) -> Row:
        return self._create(ProjectMembership, row)

    # project_role_grants
    def get_role_grant(self, project_id: str, user_id: str, role_slot: str) -> Row | None:
        return self._get_one(
            ProjectRoleGrant,
            ProjectRoleGrant.project_id == project_id,
            ProjectRoleGrant.user_id == user_id,
            ProjectRoleGrant.role_slot == role_slot,
        )

    def list_role_grants(self, project_id: str, user_id: str) -> list[Row]:
        return self._list(
            ProjectRoleGrant,
            ProjectRoleGrant.project_id == project_id,
            ProjectRoleGrant.user_id == user_id,
        )

    def create_role_grant(self, row: Row) -> Row:
        return self._create(ProjectRoleGrant, row)

    # pipelines
    def get_pipeline(self, pipeline_id: str) -> Row | None:
        return self._get_one(Pipeline, Pipeline.id == pipeline_id)

    def get_pipeline_by_code(self, project_id: str, code: str) -> Row | None:
        return self._get_one(
            Pipeline, Pipeline.project_id == project_id, Pipeline.code == code
        )

    def list_pipelines(self, project_id: str) -> list[Row]:
        return self._list(Pipeline, Pipeline.project_id == project_id)

    def create_pipeline(self, row: Row) -> Row:
        return self._create(Pipeline, row)

    # pipeline_versions
    def get_version(self, version_id: str) -> Row | None:
        return self._get_one(PipelineVersion, PipelineVersion.id == version_id)

    def list_versions(self, pipeline_id: str) -> list[Row]:
        return self._list(PipelineVersion, PipelineVersion.pipeline_id == pipeline_id)

    def create_version(self, row: Row) -> Row:
        return self._create(PipelineVersion, row)

    def update_version(self, version_id: str, fields: Row) -> Row | None:
        return self._update(PipelineVersion, version_id, fields)

    # pipeline_artifacts
    def get_artifact(self, artifact_id: str) -> Row | None:
        return self._get_one(PipelineArtifact, PipelineArtifact.id == artifact_id)

    def list_artifacts(self, version_id: str) -> list[Row]:
        return self._list(PipelineArtifact, PipelineArtifact.version_id == version_id)

    def create_artifact(self, row: Row) -> Row:
        return self._create(PipelineArtifact, row)

    # agent_runs
    def get_agent_run(self, run_id: str) -> Row | None:
        return self._get_one(AgentRun, AgentRun.id == run_id)

    def get_agent_run_by_thread(self, version_id: str, thread_id: str) -> Row | None:
        return self._get_one(
            AgentRun, AgentRun.version_id == version_id, AgentRun.thread_id == thread_id
        )

    def list_agent_runs(self, version_id: str) -> list[Row]:
        return self._list(AgentRun, AgentRun.version_id == version_id)

    def create_agent_run(self, row: Row) -> Row:
        return self._create(AgentRun, row)

    def update_agent_run(self, run_id: str, fields: Row) -> Row | None:
        return self._update(AgentRun, run_id, fields)

    # approval_requests
    def get_approval(self, approval_id: str) -> Row | None:
        return self._get_one(ApprovalRequest, ApprovalRequest.id == approval_id)

    def list_approvals(self, preparation_id: str) -> list[Row]:
        return self._list(ApprovalRequest, ApprovalRequest.preparation_id == preparation_id)

    def list_approvals_for_version(self, version_id: str) -> list[Row]:
        return self._list(ApprovalRequest, ApprovalRequest.version_id == version_id)

    def create_approval(self, row: Row) -> Row:
        return self._create(ApprovalRequest, row)

    def update_approval(self, approval_id: str, fields: Row) -> Row | None:
        return self._update(ApprovalRequest, approval_id, fields)

    # execution_runs
    def get_execution_run(self, run_id: str) -> Row | None:
        return self._get_one(ExecutionRun, ExecutionRun.id == run_id)

    def list_execution_runs(self, version_id: str | None = None) -> list[Row]:
        if version_id is None:
            return self._list(ExecutionRun)
        return self._list(ExecutionRun, ExecutionRun.version_id == version_id)

    def create_execution_run(self, row: Row) -> Row:
        return self._create(ExecutionRun, row)

    def update_execution_run(self, run_id: str, fields: Row) -> Row | None:
        return self._update(ExecutionRun, run_id, fields)

    # file_assets
    def get_file_asset(self, asset_id: str) -> Row | None:
        return self._get_one(FileAsset, FileAsset.id == asset_id)

    def list_file_assets(self, project_id: str) -> list[Row]:
        return self._list(FileAsset, FileAsset.project_id == project_id)

    def create_file_asset(self, row: Row) -> Row:
        return self._create(FileAsset, row)

    # runtime_supervision_snapshots
    def get_supervision_snapshot(self, snapshot_id: str) -> Row | None:
        return self._get_one(
            RuntimeSupervisionSnapshot, RuntimeSupervisionSnapshot.id == snapshot_id
        )

    def list_supervision_snapshots(self, execution_run_id: str) -> list[Row]:
        return self._list(
            RuntimeSupervisionSnapshot,
            RuntimeSupervisionSnapshot.execution_run_id == execution_run_id,
        )

    def create_supervision_snapshot(self, row: Row) -> Row:
        return self._create(RuntimeSupervisionSnapshot, row)

    # audit_events
    def append_audit_event(self, row: Row) -> Row:
        return self._create(AuditEvent, row)

    def list_audit_events(self, project_id: str) -> list[Row]:
        return self._list(AuditEvent, AuditEvent.project_id == project_id)
