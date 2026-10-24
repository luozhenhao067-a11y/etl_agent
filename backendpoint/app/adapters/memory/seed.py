"""Synthetic, already-masked demo data.

All identifiers and values are demo values from the frontend mock so both
sides can be compared directly. No value is a real credential.
"""

from __future__ import annotations

from app.adapters.memory.repository import InMemoryRepository
from app.adapters.memory.state import MemoryState

PROJECT_ID = "prj_demo_001"
OTHER_PROJECT_ID = "prj_demo_999"

_MASKED_DIGEST_A = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
_MASKED_DIGEST_B = "5c4ae8e2d1b6a9f03c7d5e2a1b8f6c4d9e0a3b2c1d4e5f6a7b8c9d0e1f2a3b4c"

_MOCK_ROLES = {
    "user_demo_001": "maker",
    "user_demo_002": "checker1",
    "user_demo_003": "checker2",
    "user_demo_004": "ops",
    "user_demo_005": "auditor",
    "user_demo_006": "maker",
    "user_demo_007": "maker",
}


def seed_all(
    repo: InMemoryRepository,
    state: MemoryState,
    project_id: str = PROJECT_ID,
) -> None:
    seed_repository(repo, project_id)
    seed_state(state, project_id)


def seed_repository(repo: InMemoryRepository, project_id: str = PROJECT_ID) -> None:
    """Seed the 13-table rows. Any object with the create_* port methods works."""

    _seed_users(repo)
    _seed_projects(repo, project_id)
    _seed_memberships(repo, project_id)
    _seed_role_grants(repo, project_id)
    _seed_pipelines(repo, project_id)
    _seed_versions(repo)
    _seed_approvals(repo)
    _seed_execution_runs(repo)
    _seed_file_assets(repo, project_id)
    _seed_snapshots(repo)


def seed_state(state: MemoryState, project_id: str = PROJECT_ID) -> None:
    """Seed the Spec 10.3 memory-only entities (never persisted to tables)."""

    _seed_run_extras(state)
    _seed_connections(state, project_id)
    _seed_profiles(state)
    _seed_preparations(state, project_id)
    _seed_designs(state)
    _seed_benchmarks(state)


def _seed_users(repo: InMemoryRepository) -> None:
    users = [
        ("user_demo_001", "maker01", "张三", "m***@example.com", "active"),
        ("user_demo_002", "checker1_01", "李四", "l***@example.com", "active"),
        ("user_demo_003", "checker2_01", "王五", "w***@example.com", "active"),
        ("user_demo_004", "ops01", "赵六", "z***@example.com", "active"),
        ("user_demo_005", "auditor01", "钱七", "q***@example.com", "active"),
        ("user_demo_006", "maker02", "孙八", "s***@example.com", "active"),
        ("user_demo_007", "outsider01", "周九", "o***@example.com", "active"),
    ]
    for index, (user_id, username, display_name, email, status) in enumerate(users):
        repo.create_user(
            {
                "id": user_id,
                "username": username,
                "display_name": display_name,
                "email": email,
                "status": status,
                "created_at": "2026-10-01T09:00:00+08:00",
                "updated_at": "2026-10-01T09:00:00+08:00",
            }
        )

    # The role is membership-derived in production. The mock keeps the mapping
    # here so no new table or column is invented for it.
    repo._mock_roles = dict(_MOCK_ROLES)  # type: ignore[attr-defined]


def _seed_projects(repo: InMemoryRepository, project_id: str) -> None:
    for current_id, name, code in (
        (project_id, "订单数据集成（演示项目）", "orders_demo"),
        (OTHER_PROJECT_ID, "其他项目（演示）", "other_demo"),
    ):
        repo.create_project(
            {
                "id": current_id,
                "name": name,
                "code": code,
                "description": "合成演示项目",
                "created_at": "2026-10-01T09:00:00+08:00",
                "updated_at": "2026-10-01T09:00:00+08:00",
            }
        )


def _seed_memberships(repo: InMemoryRepository, project_id: str) -> None:
    for index, (user_id, role) in enumerate(_MOCK_ROLES.items(), start=1):
        if user_id == "user_demo_007":
            continue  # intentionally not a project member
        repo.create_membership(
            {
                "id": f"mem_demo_{index:03d}",
                "project_id": project_id,
                "user_id": user_id,
                "role": role,
                "created_at": "2026-10-01T09:00:00+08:00",
                "updated_at": "2026-10-01T09:00:00+08:00",
            }
        )


def _seed_role_grants(repo: InMemoryRepository, project_id: str) -> None:
    repo.create_role_grant(
        {
            "id": "grant_demo_001",
            "project_id": project_id,
            "user_id": "user_demo_002",
            "role_slot": "data_checker",
            "created_at": "2026-10-01T09:00:00+08:00",
            "updated_at": "2026-10-01T09:00:00+08:00",
        }
    )
    repo.create_role_grant(
        {
            "id": "grant_demo_002",
            "project_id": project_id,
            "user_id": "user_demo_003",
            "role_slot": "security_checker",
            "created_at": "2026-10-01T09:00:00+08:00",
            "updated_at": "2026-10-01T09:00:00+08:00",
        }
    )


def _seed_pipelines(repo: InMemoryRepository, project_id: str) -> None:
    pipelines = [
        ("pipe_demo_001", "订单同步", "orders_sync", "MySQL 订单表到 Doris 的同步", "active"),
        ("pipe_demo_002", "CRM 汇总", "crm_agg", "CRM 数据聚合", "draft"),
        ("pipe_demo_003", "日志入仓", "logs_ingest", "ClickHouse 日志入仓", "draft"),
    ]
    for pipeline_id, name, code, description, status in pipelines:
        repo.create_pipeline(
            {
                "id": pipeline_id,
                "project_id": project_id,
                "name": name,
                "code": code,
                "description": description,
                "status": status,
                "created_at": "2026-10-20T10:00:00+08:00",
                "updated_at": "2026-10-20T10:00:00+08:00",
            }
        )


def _seed_versions(repo: InMemoryRepository) -> None:
    repo.create_version(
        {
            "id": "ver_demo_001",
            "pipeline_id": "pipe_demo_001",
            "version_number": 1,
            "etl_plan_json": {"source": "mysql_orders", "target": "doris_orders"},
            "hocon_text": 'source { host = "10.20.*.*" user = "etl_***" }',
            "artifact_digest": _MASKED_DIGEST_A,
            "is_immutable": True,
            "created_at": "2026-10-23T10:35:00+08:00",
            "updated_at": "2026-10-23T10:35:00+08:00",
        }
    )
    repo.create_version(
        {
            "id": "ver_demo_002",
            "pipeline_id": "pipe_demo_001",
            "version_number": 2,
            "etl_plan_json": None,
            "hocon_text": None,
            "artifact_digest": None,
            "is_immutable": False,
            "created_at": "2026-10-23T10:36:00+08:00",
            "updated_at": "2026-10-23T10:36:00+08:00",
        }
    )
    repo.create_artifact(
        {
            "id": "art_demo_001",
            "version_id": "ver_demo_001",
            "artifact_type": "hocon",
            "artifact_digest": _MASKED_DIGEST_A,
            "content": 'source { host = "10.20.*.*" user = "etl_***" }',
            "created_at": "2026-10-23T10:35:00+08:00",
        }
    )


def _seed_approvals(repo: InMemoryRepository) -> None:
    approvals = [
        ("apr_demo_001", "prep_demo_001", "data_checker", "PENDING", None, "user_demo_002", None),
        ("apr_demo_002", "prep_demo_001", "security_checker", "PENDING", None, "user_demo_003", None),
        ("apr_demo_003", "prep_demo_002", "data_checker", "APPROVED", "approve", "user_demo_002", "2026-10-22T10:50:00+08:00"),
        ("apr_demo_004", "prep_demo_002", "security_checker", "APPROVED", "approve", "user_demo_003", "2026-10-22T10:55:00+08:00"),
        ("apr_demo_005", "prep_demo_003", "data_checker", "APPROVED", "approve", "user_demo_002", "2026-10-21T09:30:00+08:00"),
        ("apr_demo_006", "prep_demo_003", "security_checker", "PENDING", None, "user_demo_003", None),
        ("apr_demo_007", "prep_demo_004", "data_checker", "APPROVED", "approve", "user_demo_002", "2026-10-20T14:30:00+08:00"),
        ("apr_demo_008", "prep_demo_004", "security_checker", "REJECTED", "reject", "user_demo_003", "2026-10-20T14:45:00+08:00"),
        ("apr_demo_009", "prep_demo_005", "data_checker", "APPROVED", "approve", "user_demo_002", "2026-10-23T09:10:00+08:00"),
        ("apr_demo_010", "prep_demo_005", "security_checker", "APPROVED", "approve", "user_demo_003", "2026-10-23T09:15:00+08:00"),
    ]
    for approval_id, preparation_id, required_role, status, decision, approver_id, decided_at in approvals:
        repo.create_approval(
            {
                "id": approval_id,
                "preparation_id": preparation_id,
                "version_id": "ver_demo_001",
                "required_role": required_role,
                "status": status,
                "decision": decision,
                "approver_id": approver_id,
                "decided_at": decided_at,
                "created_at": "2026-10-20T09:00:00+08:00",
                "updated_at": decided_at or "2026-10-20T09:00:00+08:00",
            }
        )


def _seed_execution_runs(repo: InMemoryRepository) -> None:
    runs = [
        {
            "id": "run_demo_001",
            "version_id": "ver_demo_001",
            "preparation_id": "prep_demo_002",
            "capability_token_digest": "a" * 64,
            "status": "running",
            "engine_job_id": "job_demo_001",
            "input_records": 823410,
            "output_records": 806520,
            "error_records": 16890,
            "bytes_processed": 4382746624,
            "started_at": "2026-10-23T10:46:00+08:00",
            "finished_at": None,
            "created_at": "2026-10-23T10:45:00+08:00",
            "updated_at": "2026-10-23T10:48:00+08:00",
        },
        {
            "id": "run_demo_002",
            "version_id": "ver_demo_001",
            "preparation_id": "prep_demo_002",
            "capability_token_digest": "b" * 64,
            "status": "succeeded",
            "engine_job_id": "job_demo_002",
            "input_records": 1200000,
            "output_records": 1194000,
            "error_records": 6000,
            "bytes_processed": 6442450944,
            "started_at": "2026-10-22T11:01:00+08:00",
            "finished_at": "2026-10-22T11:26:00+08:00",
            "created_at": "2026-10-22T11:00:00+08:00",
            "updated_at": "2026-10-22T11:26:00+08:00",
        },
        {
            "id": "run_demo_003",
            "version_id": "ver_demo_001",
            "preparation_id": "prep_demo_004",
            "capability_token_digest": "c" * 64,
            "status": "failed",
            "engine_job_id": "job_demo_003",
            "input_records": 560000,
            "output_records": 512000,
            "error_records": 48000,
            "bytes_processed": 2147483648,
            "started_at": "2026-10-20T15:00:00+08:00",
            "finished_at": "2026-10-20T15:18:00+08:00",
            "created_at": "2026-10-20T14:55:00+08:00",
            "updated_at": "2026-10-20T15:18:00+08:00",
        },
        {
            "id": "run_demo_004",
            "version_id": "ver_demo_001",
            "preparation_id": "prep_demo_003",
            "capability_token_digest": "d" * 64,
            "status": "cancelled",
            "engine_job_id": "job_demo_004",
            "input_records": 120000,
            "output_records": 90000,
            "error_records": 30000,
            "bytes_processed": 536870912,
            "started_at": "2026-10-21T10:00:00+08:00",
            "finished_at": "2026-10-21T10:12:00+08:00",
            "created_at": "2026-10-21T09:58:00+08:00",
            "updated_at": "2026-10-21T10:12:00+08:00",
        },
        {
            "id": "run_demo_005",
            "version_id": "ver_demo_001",
            "preparation_id": "prep_demo_003",
            "capability_token_digest": "e" * 64,
            "status": "queued",
            "engine_job_id": None,
            "input_records": 0,
            "output_records": 0,
            "error_records": 0,
            "bytes_processed": 0,
            "started_at": None,
            "finished_at": None,
            "created_at": "2026-10-23T11:10:00+08:00",
            "updated_at": "2026-10-23T11:10:00+08:00",
        },
    ]
    for row in runs:
        repo.create_execution_run(row)


def _seed_file_assets(repo: InMemoryRepository, project_id: str) -> None:
    repo.create_file_asset(
        {
            "id": "file_demo_001",
            "project_id": project_id,
            "file_name": "orders_***.csv",
            "file_path": "object://files/***",
            "file_size": 2048,
            "file_format": "csv",
            "schema_json": {"fields": [{"name": "order_id", "type": "string"}]},
            "created_at": "2026-10-23T10:25:00+08:00",
            "updated_at": "2026-10-23T10:25:00+08:00",
        }
    )
    repo.create_file_asset(
        {
            "id": "file_demo_002",
            "project_id": project_id,
            "file_name": "crm_export_***.xlsx",
            "file_path": "object://files/***",
            "file_size": 61440,
            "file_format": "excel",
            "schema_json": {"fields": [{"name": "email", "type": "string", "masked": True}]},
            "created_at": "2026-10-22T16:40:00+08:00",
            "updated_at": "2026-10-22T16:40:00+08:00",
        }
    )
    repo.create_file_asset(
        {
            "id": "file_demo_003",
            "project_id": project_id,
            "file_name": "events_***.json",
            "file_path": "object://files/***",
            "file_size": 4096,
            "file_format": "json",
            "schema_json": None,
            "created_at": "2026-10-21T09:10:00+08:00",
            "updated_at": "2026-10-21T09:10:00+08:00",
        }
    )


def _seed_snapshots(repo: InMemoryRepository) -> None:
    repo.create_supervision_snapshot(
        {
            "id": "snap_demo_001",
            "execution_run_id": "run_demo_001",
            "metrics_json": {"rows_pct": 82, "bytes_pct": 82, "duration_pct": 69},
            "decision": "within_budget",
            "action_taken": None,
            "created_at": "2026-10-23T10:48:00+08:00",
        }
    )


def _seed_run_extras(state: MemoryState) -> None:
    state.run_extras["run_demo_001"] = {
        "duration_seconds": 120,
        "quality_report": {
            "status": "warning",
            "error_codes": [{"code": "E-2003", "count": 16890}],
            "samples_masked": True,
        },
        "supervision": {"status": "within_budget", "actions": []},
        "recent_logs": [
            "stage=extract rows=500000 masked=true",
            "stage=transform rows=420000 masked=true",
            "stage=load rows=380000 masked=true",
        ],
    }
    state.run_extras["run_demo_002"] = {
        "duration_seconds": 1500,
        "quality_report": {
            "status": "passed",
            "error_codes": [{"code": "E-2003", "count": 6000}],
            "samples_masked": True,
        },
        "supervision": {"status": "within_budget", "actions": []},
        "recent_logs": ["stage=load rows=1194000 masked=true", "job=succeeded masked=true"],
    }
    state.run_extras["run_demo_003"] = {
        "duration_seconds": 1080,
        "quality_report": {
            "status": "failed",
            "error_codes": [{"code": "E-3001", "count": 48000}],
            "samples_masked": True,
        },
        "supervision": {"status": "budget_exceeded", "actions": ["paused"]},
        "recent_logs": ["stage=transform status=failed masked=true"],
    }
    state.run_extras["run_demo_004"] = {
        "duration_seconds": 720,
        "quality_report": {
            "status": "cancelled",
            "error_codes": [],
            "samples_masked": True,
        },
        "supervision": {"status": "cancelled", "actions": ["cancelled"]},
        "recent_logs": ["status=cancelled masked=true"],
    }
    state.run_extras["run_demo_005"] = {
        "duration_seconds": None,
        "quality_report": None,
        "supervision": {"status": "queued", "actions": []},
        "recent_logs": [],
    }


def _seed_connections(state: MemoryState, project_id: str) -> None:
    connections = [
        ("conn_demo_001", "mysql_orders", "mysql", "prod", "active", "10.20.*.*", "source", "2026-10-23T09:30:00+08:00", "configured"),
        ("conn_demo_002", "doris_orders", "doris", "prod", "active", "10.30.*.*", "target", "2026-10-23T09:31:00+08:00", "configured"),
        ("conn_demo_003", "pg_crm", "postgresql", "test", "active", "192.168.*.*", "source", None, "not_configured"),
        ("conn_demo_004", "clickhouse_logs", "clickhouse", "preprod", "inactive", "172.16.*.*", "source", "2026-10-20T08:00:00+08:00", "configured"),
        ("conn_demo_005", "oracle_finance", "oracle", "prod", "active", "10.40.*.*", "source", None, "configured"),
        ("conn_demo_006", "minio_raw", "minio", "prod", "active", "minio.***", "source", "2026-10-22T14:00:00+08:00", "configured"),
        ("conn_demo_007", "api_erp", "rest_api", "test", "active", "api.***", "source", None, "configured"),
    ]
    database_types = {"mysql", "postgresql", "oracle", "doris", "clickhouse"}
    for (
        connection_id,
        name,
        connection_type,
        env,
        status,
        host_masked,
        source_target,
        last_tested_at,
        secret_state,
    ) in connections:
        is_database = connection_type in database_types
        state.connections[connection_id] = {
            "id": connection_id,
            "project_id": project_id,
            "name": name,
            "type": connection_type,
            "env": env,
            "status": status,
            "host_masked": host_masked,
            "source_target": source_target,
            "last_tested_at": last_tested_at,
            "secret_state": secret_state,
            "secret_ref_digest": None,
            # The full (masked) editable attributes keep API-04 partial updates
            # valid without inventing a second storage table.
            "port": 3306 if is_database else None,
            "database": "orders" if is_database else None,
            "username": "etl_***" if is_database else None,
            "readonly": True,
            "tls": None,
            "file_source": None if is_database else {"prefix": "***"},
            "created_at": "2026-10-01T09:00:00+08:00",
            "updated_at": "2026-10-01T09:00:00+08:00",
        }


def _seed_profiles(state: MemoryState) -> None:
    state.profiles["conn_demo_001"] = {
        "profile_status": "completed",
        "sampled_at": "2026-10-23T10:20:00+08:00",
        "tables": [{"name": "orders", "classification": "P1"}],
        "columns": [
            {"name": "order_id", "type": "bigint", "masked": False},
            {"name": "phone", "type": "string", "masked": True},
        ],
        "masked_samples": [{"phone": "138****6621"}],
    }
    state.profiles["conn_demo_003"] = None


def _seed_preparations(state: MemoryState, project_id: str) -> None:
    state.preparations["prep_demo_001"] = {
        "preparation_id": "prep_demo_001",
        "version_id": "ver_demo_001",
        "project_id": project_id,
        "applicant_id": "user_demo_001",
        "status": "PREPARED",
        "risk_level": "P1",
        "fingerprint": f"sha256:{_MASKED_DIGEST_A}",
        "approval_ids": ["apr_demo_001", "apr_demo_002"],
        "created_at": "2026-10-23T10:40:00+08:00",
    }
    state.preparations["prep_demo_002"] = {
        "preparation_id": "prep_demo_002",
        "version_id": "ver_demo_001",
        "project_id": project_id,
        "applicant_id": "user_demo_001",
        "status": "APPROVED",
        "risk_level": "P2",
        "fingerprint": f"sha256:{_MASKED_DIGEST_A}",
        "approval_ids": ["apr_demo_003", "apr_demo_004"],
        "created_at": "2026-10-22T10:40:00+08:00",
        "commit": {
            "execution_run_id": "run_demo_002",
            "capability_digest": f"sha256:{_MASKED_DIGEST_B}",
            "committed_at": "2026-10-22T11:00:00+08:00",
        },
    }
    state.preparations["prep_demo_003"] = {
        "preparation_id": "prep_demo_003",
        "version_id": "ver_demo_001",
        "project_id": project_id,
        "applicant_id": "user_demo_001",
        "status": "PARTIAL_APPROVED",
        "risk_level": "P1",
        "fingerprint": f"sha256:{_MASKED_DIGEST_A}",
        "approval_ids": ["apr_demo_005", "apr_demo_006"],
        "created_at": "2026-10-21T09:00:00+08:00",
    }
    state.preparations["prep_demo_004"] = {
        "preparation_id": "prep_demo_004",
        "version_id": "ver_demo_001",
        "project_id": project_id,
        "applicant_id": "user_demo_001",
        "status": "REJECTED",
        "risk_level": "P2",
        "fingerprint": f"sha256:{_MASKED_DIGEST_A}",
        "approval_ids": ["apr_demo_007", "apr_demo_008"],
        "created_at": "2026-10-20T14:00:00+08:00",
    }
    state.preparations["prep_demo_005"] = {
        "preparation_id": "prep_demo_005",
        "version_id": "ver_demo_001",
        "project_id": project_id,
        "applicant_id": "user_demo_001",
        "status": "APPROVED",
        "risk_level": "P1",
        "fingerprint": f"sha256:{_MASKED_DIGEST_A}",
        "approval_ids": ["apr_demo_009", "apr_demo_010"],
        "created_at": "2026-10-23T09:00:00+08:00",
    }


def _seed_designs(state: MemoryState) -> None:
    # ver_demo_001 is the committed demo chain; ver_demo_003 stays free of a
    # SQL preparation so the live prepare → approve → commit → execute chain
    # stays demoable end to end (2026-10-24 真库联调).
    for version_id in ("ver_demo_001", "ver_demo_003"):
        state.designs[version_id] = {
        "etl_plan_json": {
            "source": "mysql_orders",
            "target": "doris_orders",
            "mappings": [{"source": "phone", "target": "phone", "transform": "mask_phone"}],
        },
        "hocon_text": (
            'source { host = "10.20.*.*" user = "etl_***" }\n'
            'sink { fenodes = "doris_fe:***" table = "orders_shadow" }'
        ),
        "dag": {"nodes": ["source", "transform", "sink"], "edges": []},
        "quality_contract": {"rules": [{"field": "phone", "rule": "not_null"}]},
        "gate_result": {
            "syntax": "passed",
            "schema": "passed",
            "masking": "passed",
            "budget": "passed",
        },
        "diff": None,
        "masking": {"phone": {"before": "string", "after": "masked_string"}},
        }


def _seed_benchmarks(state: MemoryState) -> None:
    state.benchmark_runs["bench_demo_001"] = {
        "benchmark_run_id": "bench_demo_001",
        "suite_id": "suite_demo_001",
        "layer": "L0",
        "dataset_version": "ds_demo_v1",
        "status": "completed",
    }
    state.benchmark_runs["bench_demo_002"] = {
        "benchmark_run_id": "bench_demo_002",
        "suite_id": "suite_demo_001",
        "layer": "L1",
        "dataset_version": "ds_demo_v1",
        "status": "completed",
    }
    state.benchmark_runs["bench_demo_003"] = {
        "benchmark_run_id": "bench_demo_003",
        "suite_id": "suite_demo_001",
        "layer": "L2",
        "dataset_version": "ds_demo_v2",
        "status": "running",
    }
    state.benchmark_runs["bench_demo_004"] = {
        "benchmark_run_id": "bench_demo_004",
        "suite_id": "suite_demo_002",
        "layer": "L0",
        "dataset_version": "ds_demo_v1",
        "status": "failed",
        "error_code": "BENCH-503",
    }
