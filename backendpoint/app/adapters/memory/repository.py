"""In-memory implementation of RepositoryPort.

Rows are plain dictionaries so the API layer can run without PostgreSQL. The
SQLAlchemy models in ``app.models`` remain the only table declarations.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

Row = dict[str, Any]


class InMemoryRepository:
    def __init__(self) -> None:
        self.users: dict[str, Row] = {}
        self.projects: dict[str, Row] = {}
        self.memberships: dict[str, Row] = {}
        self.role_grants: dict[str, Row] = {}
        self.pipelines: dict[str, Row] = {}
        self.versions: dict[str, Row] = {}
        self.artifacts: dict[str, Row] = {}
        self.agent_runs: dict[str, Row] = {}
        self.approvals: dict[str, Row] = {}
        self.execution_runs: dict[str, Row] = {}
        self.file_assets: dict[str, Row] = {}
        self.supervision_snapshots: dict[str, Row] = {}
        self.audit_events: dict[str, Row] = {}

    @staticmethod
    def _copy(row: Row | None) -> Row | None:
        return deepcopy(row) if row is not None else None

    # users
    def get_user(self, user_id: str) -> Row | None:
        return self._copy(self.users.get(user_id))

    def get_user_by_username(self, username: str) -> Row | None:
        for row in self.users.values():
            if row["username"] == username:
                return self._copy(row)
        return None

    def list_users(self) -> list[Row]:
        return deepcopy(list(self.users.values()))

    def create_user(self, row: Row) -> Row:
        self.users[row["id"]] = deepcopy(row)
        return self._copy(row)  # type: ignore[return-value]

    # projects
    def get_project(self, project_id: str) -> Row | None:
        return self._copy(self.projects.get(project_id))

    def list_projects(self) -> list[Row]:
        return deepcopy(list(self.projects.values()))

    def create_project(self, row: Row) -> Row:
        self.projects[row["id"]] = deepcopy(row)
        return self._copy(row)  # type: ignore[return-value]

    # project_memberships
    def get_membership(self, project_id: str, user_id: str) -> Row | None:
        for row in self.memberships.values():
            if row["project_id"] == project_id and row["user_id"] == user_id:
                return self._copy(row)
        return None

    def list_memberships(self, project_id: str) -> list[Row]:
        return deepcopy([row for row in self.memberships.values() if row["project_id"] == project_id])

    def create_membership(self, row: Row) -> Row:
        self.memberships[row["id"]] = deepcopy(row)
        return self._copy(row)  # type: ignore[return-value]

    # project_role_grants
    def get_role_grant(self, project_id: str, user_id: str, role_slot: str) -> Row | None:
        for row in self.role_grants.values():
            if (
                row["project_id"] == project_id
                and row["user_id"] == user_id
                and row["role_slot"] == role_slot
            ):
                return self._copy(row)
        return None

    def list_role_grants(self, project_id: str, user_id: str) -> list[Row]:
        return deepcopy(
            [
                row
                for row in self.role_grants.values()
                if row["project_id"] == project_id and row["user_id"] == user_id
            ]
        )

    def create_role_grant(self, row: Row) -> Row:
        self.role_grants[row["id"]] = deepcopy(row)
        return self._copy(row)  # type: ignore[return-value]

    # pipelines
    def get_pipeline(self, pipeline_id: str) -> Row | None:
        return self._copy(self.pipelines.get(pipeline_id))

    def get_pipeline_by_code(self, project_id: str, code: str) -> Row | None:
        for row in self.pipelines.values():
            if row["project_id"] == project_id and row["code"] == code:
                return self._copy(row)
        return None

    def list_pipelines(self, project_id: str) -> list[Row]:
        return deepcopy([row for row in self.pipelines.values() if row["project_id"] == project_id])

    def create_pipeline(self, row: Row) -> Row:
        self.pipelines[row["id"]] = deepcopy(row)
        return self._copy(row)  # type: ignore[return-value]

    # pipeline_versions
    def get_version(self, version_id: str) -> Row | None:
        return self._copy(self.versions.get(version_id))

    def list_versions(self, pipeline_id: str) -> list[Row]:
        return deepcopy([row for row in self.versions.values() if row["pipeline_id"] == pipeline_id])

    def create_version(self, row: Row) -> Row:
        self.versions[row["id"]] = deepcopy(row)
        return self._copy(row)  # type: ignore[return-value]

    def update_version(self, version_id: str, fields: Row) -> Row | None:
        row = self.versions.get(version_id)
        if row is None:
            return None
        row.update(deepcopy(fields))
        return self._copy(row)

    # pipeline_artifacts
    def get_artifact(self, artifact_id: str) -> Row | None:
        return self._copy(self.artifacts.get(artifact_id))

    def list_artifacts(self, version_id: str) -> list[Row]:
        return deepcopy([row for row in self.artifacts.values() if row["version_id"] == version_id])

    def create_artifact(self, row: Row) -> Row:
        self.artifacts[row["id"]] = deepcopy(row)
        return self._copy(row)  # type: ignore[return-value]

    # agent_runs
    def get_agent_run(self, run_id: str) -> Row | None:
        return self._copy(self.agent_runs.get(run_id))

    def get_agent_run_by_thread(self, version_id: str, thread_id: str) -> Row | None:
        for row in self.agent_runs.values():
            if row["version_id"] == version_id and row["thread_id"] == thread_id:
                return self._copy(row)
        return None

    def list_agent_runs(self, version_id: str) -> list[Row]:
        return deepcopy([row for row in self.agent_runs.values() if row["version_id"] == version_id])

    def create_agent_run(self, row: Row) -> Row:
        self.agent_runs[row["id"]] = deepcopy(row)
        return self._copy(row)  # type: ignore[return-value]

    def update_agent_run(self, run_id: str, fields: Row) -> Row | None:
        row = self.agent_runs.get(run_id)
        if row is None:
            return None
        row.update(deepcopy(fields))
        return self._copy(row)

    # approval_requests
    def get_approval(self, approval_id: str) -> Row | None:
        return self._copy(self.approvals.get(approval_id))

    def list_approvals(self, preparation_id: str) -> list[Row]:
        return deepcopy(
            [row for row in self.approvals.values() if row["preparation_id"] == preparation_id]
        )

    def list_approvals_for_version(self, version_id: str) -> list[Row]:
        return deepcopy([row for row in self.approvals.values() if row["version_id"] == version_id])

    def create_approval(self, row: Row) -> Row:
        self.approvals[row["id"]] = deepcopy(row)
        return self._copy(row)  # type: ignore[return-value]

    def update_approval(self, approval_id: str, fields: Row) -> Row | None:
        row = self.approvals.get(approval_id)
        if row is None:
            return None
        row.update(deepcopy(fields))
        return self._copy(row)

    # execution_runs
    def get_execution_run(self, run_id: str) -> Row | None:
        return self._copy(self.execution_runs.get(run_id))

    def list_execution_runs(self, version_id: str | None = None) -> list[Row]:
        rows = list(self.execution_runs.values())
        if version_id is not None:
            rows = [row for row in rows if row["version_id"] == version_id]
        return deepcopy(rows)

    def create_execution_run(self, row: Row) -> Row:
        self.execution_runs[row["id"]] = deepcopy(row)
        return self._copy(row)  # type: ignore[return-value]

    def update_execution_run(self, run_id: str, fields: Row) -> Row | None:
        row = self.execution_runs.get(run_id)
        if row is None:
            return None
        row.update(deepcopy(fields))
        return self._copy(row)

    # file_assets
    def get_file_asset(self, asset_id: str) -> Row | None:
        return self._copy(self.file_assets.get(asset_id))

    def list_file_assets(self, project_id: str) -> list[Row]:
        return deepcopy([row for row in self.file_assets.values() if row["project_id"] == project_id])

    def create_file_asset(self, row: Row) -> Row:
        self.file_assets[row["id"]] = deepcopy(row)
        return self._copy(row)  # type: ignore[return-value]

    # runtime_supervision_snapshots
    def get_supervision_snapshot(self, snapshot_id: str) -> Row | None:
        return self._copy(self.supervision_snapshots.get(snapshot_id))

    def list_supervision_snapshots(self, execution_run_id: str) -> list[Row]:
        return deepcopy(
            [
                row
                for row in self.supervision_snapshots.values()
                if row["execution_run_id"] == execution_run_id
            ]
        )

    def create_supervision_snapshot(self, row: Row) -> Row:
        self.supervision_snapshots[row["id"]] = deepcopy(row)
        return self._copy(row)  # type: ignore[return-value]

    # audit_events
    def append_audit_event(self, row: Row) -> Row:
        self.audit_events[row["id"]] = deepcopy(row)
        return self._copy(row)  # type: ignore[return-value]

    def list_audit_events(self, project_id: str) -> list[Row]:
        return deepcopy(
            [row for row in self.audit_events.values() if row["project_id"] == project_id]
        )
