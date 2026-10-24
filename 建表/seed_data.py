"""Idempotent demo seed for the thirteen Spec 10.1 tables (v2, 20+ rows/table).

Base demo rows (user_demo_001..007 etc.) stay verbatim for frontend-mock
compatibility; the v2 volume section adds four more projects and realistic
ETL scenarios so every table carries 20+ rows. Status enums follow the live
interface: approval states are UPPER (PENDING/APPROVED/REJECTED), execution
states are lower (queued/running/succeeded/failed/cancelled/rolled_back).

Idempotency: every row is inserted only when its primary key is absent.
No DELETE/TRUNCATE is issued because ``audit_events`` is append-only and
``pipeline_versions`` can never be deleted (database triggers from migration
0001). Re-running is a no-op; a full reset is
``alembic downgrade base && alembic upgrade head``.

All digests are real SHA256 hex strings computed with hashlib; no plaintext
secret ever enters the database (Spec 10.2 / 12.4).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKENDPOINT = ROOT.parent / "backendpoint"
for path in (str(BACKENDPOINT), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.models.tables import (  # noqa: E402
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

GENESIS_PREV_HASH = "0" * 64
PROJECT_MAIN = "prj_demo_001"


def sha256_hex(text: str) -> str:
    """Real 64-char lowercase SHA256 hex digest (Spec 10.2 digest format)."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def event_hash_for(
    project_id: str,
    actor_id: str,
    event_type: str,
    resource_type: str,
    resource_id: str,
    payload_digest: str,
    prev_event_hash: str,
) -> str:
    """Deterministic demo canonicalization of the ledger hash chain.

    The on-chain ordering rule is still pending (Spec 10.3 / P-09); this
    canonical string is stable and self-describing for the demo dataset.
    """

    return sha256_hex(
        "|".join(
            (project_id, actor_id, event_type, resource_type, resource_id,
             payload_digest, prev_event_hash)
        )
    )


def insert_missing(session, model, rows, *, key: str = "id") -> tuple[int, int]:
    """Insert rows whose primary key does not exist yet. Returns (inserted, skipped)."""

    existing = set(session.execute(select(getattr(model, key))).scalars())
    inserted = skipped = 0
    for row in rows:
        if row[key] in existing:
            skipped += 1
            continue
        session.add(model(**row))
        existing.add(row[key])
        inserted += 1
    return inserted, skipped


def email_for(username: str) -> str:
    """Masked demo email, unique per username (no real address is stored)."""

    return f"{username.replace('_', '')}***@example.com"


def _latest(a: str, b: str) -> str:
    return a if ts(a) >= ts(b) else b


# ---------------------------------------------------------------------------
# Base demo rows (v1) — kept verbatim so the frontend mock story stays true.
# Timestamps are fixed demo values (+08:00).
# ---------------------------------------------------------------------------

T_BASE = "2026-10-01T09:00:00+08:00"

USERS = [
    ("user_demo_001", "maker01", "张三", "m***@example.com", "active"),
    ("user_demo_002", "checker1_01", "李四", "l***@example.com", "active"),
    ("user_demo_003", "checker2_01", "王五", "w***@example.com", "active"),
    ("user_demo_004", "ops01", "赵六", "z***@example.com", "active"),
    ("user_demo_005", "auditor01", "钱七", "q***@example.com", "active"),
    ("user_demo_006", "maker02", "孙八", "s***@example.com", "active"),
    # Boundary value: Spec allows disabling without deleting (10.1 lifecycle).
    ("user_demo_007", "outsider01", "周九", "o***@example.com", "disabled"),
]

MEMBERSHIPS = [
    ("mem_demo_001", "prj_demo_001", "user_demo_001", "maker"),
    ("mem_demo_002", "prj_demo_001", "user_demo_002", "checker1"),
    ("mem_demo_003", "prj_demo_001", "user_demo_003", "checker2"),
    ("mem_demo_004", "prj_demo_001", "user_demo_004", "ops"),
    ("mem_demo_005", "prj_demo_001", "user_demo_005", "auditor"),
    ("mem_demo_006", "prj_demo_001", "user_demo_006", "maker"),
]

ROLE_GRANTS = [
    ("grant_demo_001", "prj_demo_001", "user_demo_002", "data_checker"),
    ("grant_demo_002", "prj_demo_001", "user_demo_003", "security_checker"),
]

PIPELINES = [
    ("pipe_demo_001", "订单同步", "orders_sync", "MySQL 订单表到 Doris 的同步", "active"),
    ("pipe_demo_002", "CRM 汇总", "crm_agg", "CRM 数据聚合", "draft"),
    ("pipe_demo_003", "日志入仓", "logs_ingest", "ClickHouse 日志入仓", "draft"),
]

HOCON_ORDERS = (
    'source { host = "10.20.*.*" user = "etl_***" }\n'
    'sink { fenodes = "doris_fe:***" table = "orders_shadow" }'
)
ETL_PLAN_ORDERS = {
    "source": "mysql_orders",
    "target": "doris_orders",
    "mappings": [
        {"source": "order_id", "target": "order_id", "transform": "direct"},
        {"source": "phone", "target": "phone", "transform": "mask_phone"},
        {"source": "email", "target": "email", "transform": "mask_email"},
        {"source": "amount", "target": "amount", "transform": "direct"},
    ],
    "schedule": {"mode": "manual"},
}
HOCON_LOGS = (
    'source { host = "172.16.*.*" table = "logs_raw" }\n'
    'sink { url = "clickhouse://***" table = "logs_ods" }'
)
ETL_PLAN_LOGS = {
    "source": "clickhouse_logs",
    "target": "logs_ods",
    "mappings": [{"source": "event_id", "target": "event_id", "transform": "direct"}],
    "schedule": {"mode": "hourly"},
}

# (id, pipeline_id, version_number, plan, hocon, digest, is_immutable, created)
VERSIONS = [
    (
        "ver_demo_001", "pipe_demo_001", 1, ETL_PLAN_ORDERS, HOCON_ORDERS,
        sha256_hex(HOCON_ORDERS), True, "2026-10-23T10:35:00+08:00",
    ),
    # Boundary: freshly created, nothing generated yet.
    (
        "ver_demo_002", "pipe_demo_001", 2, None, None, None, False,
        "2026-10-23T10:36:00+08:00",
    ),
    (
        "ver_demo_003", "pipe_demo_003", 1, ETL_PLAN_LOGS, HOCON_LOGS,
        sha256_hex(HOCON_LOGS), True, "2026-10-23T11:30:00+08:00",
    ),
]

# (id, version_id, artifact_type, content_or_none) — digest is always computed.
ARTIFACTS = [
    ("art_demo_001", "ver_demo_001", "hocon", HOCON_ORDERS),
    ("art_demo_002", "ver_demo_001", "etl_plan", canonical_json(ETL_PLAN_ORDERS)),
    ("art_demo_003", "ver_demo_003", "hocon", HOCON_LOGS),
]

AGENT_RUNS = [
    # Matches frontend mock db.js agentRuns.ver_demo_002.
    ("agent_demo_001", "ver_demo_002", "thread_demo_001",
     "生成 CRM 汇总链路（演示）", "interrupted", 3, None,
     "2026-10-23T10:40:00+08:00", "2026-10-23T10:42:00+08:00"),
    ("agent_demo_002", "ver_demo_001", "thread_demo_002",
     "调整订单同步的字段映射（演示）", "completed", 6, None,
     "2026-10-23T09:20:00+08:00", "2026-10-23T09:35:00+08:00"),
    ("agent_demo_003", "ver_demo_002", "thread_demo_003",
     "为日志入仓生成调度策略（演示）", "running", 4, None,
     "2026-10-23T11:40:00+08:00", "2026-10-23T11:45:00+08:00"),
]

# (id, preparation_id, required_role, status, decision, approver_id, decided_at)
APPROVALS = [
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

# (id, preparation_id, status, engine_job_id, in, out, err, bytes, started, finished, created, updated)
EXECUTION_RUNS = [
    ("run_demo_001", "prep_demo_002", "running", "job_demo_001",
     823410, 806520, 16890, 4382746624,
     "2026-10-23T10:46:00+08:00", None,
     "2026-10-23T10:45:00+08:00", "2026-10-23T10:48:00+08:00"),
    ("run_demo_002", "prep_demo_002", "succeeded", "job_demo_002",
     1200000, 1194000, 6000, 6442450944,
     "2026-10-22T11:01:00+08:00", "2026-10-22T11:26:00+08:00",
     "2026-10-22T11:00:00+08:00", "2026-10-22T11:26:00+08:00"),
    ("run_demo_003", "prep_demo_004", "failed", "job_demo_003",
     560000, 512000, 48000, 2147483648,
     "2026-10-20T15:00:00+08:00", "2026-10-20T15:18:00+08:00",
     "2026-10-20T14:55:00+08:00", "2026-10-20T15:18:00+08:00"),
    ("run_demo_004", "prep_demo_003", "cancelled", "job_demo_004",
     120000, 90000, 30000, 536870912,
     "2026-10-21T10:00:00+08:00", "2026-10-21T10:12:00+08:00",
     "2026-10-21T09:58:00+08:00", "2026-10-21T10:12:00+08:00"),
    # Boundary: queued run has no counters, no engine job, no token yet.
    ("run_demo_005", "prep_demo_003", "queued", None,
     0, 0, 0, 0, None, None,
     "2026-10-23T11:10:00+08:00", "2026-10-23T11:10:00+08:00"),
    ("run_demo_006", "prep_demo_002", "rolled_back", "job_demo_005",
     340000, 0, 340000, 1073741824,
     "2026-10-22T16:00:00+08:00", "2026-10-22T16:09:00+08:00",
     "2026-10-22T15:58:00+08:00", "2026-10-22T16:15:00+08:00"),
]

FILE_ASSETS = [
    ("file_demo_001", "orders_***.csv", "object://files/***", 2048, "csv",
     {"fields": [{"name": "order_id", "type": "string"}]},
     "2026-10-23T10:25:00+08:00"),
    ("file_demo_002", "crm_export_***.xlsx", "object://files/***", 61440, "excel",
     {"fields": [{"name": "email", "type": "string", "masked": True}]},
     "2026-10-22T16:40:00+08:00"),
    ("file_demo_003", "events_***.json", "object://files/***", 4096, "json",
     None, "2026-10-21T09:10:00+08:00"),
    # Boundary: zero-size file passes the file_size >= 0 check.
    ("file_demo_004", "empty_***.csv", "object://files/***", 0, "csv",
     None, "2026-10-20T11:00:00+08:00"),
]

SNAPSHOTS = [
    ("snap_demo_001", "run_demo_001",
     {"rows_pct": 82, "bytes_pct": 82, "duration_pct": 69},
     "within_budget", None, "2026-10-23T10:48:00+08:00"),
    ("snap_demo_002", "run_demo_003",
     {"rows_pct": 100, "bytes_pct": 97, "duration_pct": 118, "error_rate_pct": 8.6},
     "budget_exceeded", "paused", "2026-10-20T15:10:00+08:00"),
    ("snap_demo_003", "run_demo_004",
     {"rows_pct": 26, "bytes_pct": 12, "duration_pct": 40},
     "cancelled", "cancelled", "2026-10-21T10:11:00+08:00"),
]

# (event_type, resource_type, resource_id, payload, actor, created)
# Event types follow the Spec 12.2 audit catalogue.
AUDIT_EVENT_DEFS = [
    ("pipeline.created", "pipeline", "pipe_demo_001",
     {"pipeline_id": "pipe_demo_001", "project_id": "prj_demo_001", "code": "orders_sync"},
     "user_demo_001", "2026-10-20T09:00:00+08:00"),
    ("file.asset.uploaded", "file_asset", "file_demo_001",
     {"file_asset_id": "file_demo_001", "format": "csv", "size": 2048, "source": "upload"},
     "user_demo_001", "2026-10-20T10:00:00+08:00"),
    ("agent.run.started", "agent_run", "agent_demo_002",
     {"agent_run_id": "agent_demo_002", "version_id": "ver_demo_001", "thread_id": "thread_demo_002", "provider": "demo"},
     "user_demo_001", "2026-10-20T11:00:00+08:00"),
    ("version.frozen", "pipeline_version", "ver_demo_001",
     {"version_id": "ver_demo_001", "artifact_digest": sha256_hex(HOCON_ORDERS)},
     "user_demo_001", "2026-10-21T08:30:00+08:00"),
    ("gate.evaluated", "pipeline_version", "ver_demo_001",
     {"version_id": "ver_demo_001", "syntax": "passed", "schema": "passed", "masking": "passed", "budget": "passed"},
     "user_demo_001", "2026-10-21T08:31:00+08:00"),
    ("preparation.created", "preparation", "prep_demo_002",
     {"preparation_id": "prep_demo_002", "version_id": "ver_demo_001", "risk_level": "P2"},
     "user_demo_001", "2026-10-22T10:40:00+08:00"),
    ("approval.decision.recorded", "approval_request", "apr_demo_003",
     {"approval_id": "apr_demo_003", "decision": "approve", "approver_id": "user_demo_002"},
     "user_demo_002", "2026-10-22T10:50:00+08:00"),
    ("approval.decision.recorded", "approval_request", "apr_demo_004",
     {"approval_id": "apr_demo_004", "decision": "approve", "approver_id": "user_demo_003"},
     "user_demo_003", "2026-10-22T10:55:00+08:00"),
    ("approval.completed", "preparation", "prep_demo_002",
     {"preparation_id": "prep_demo_002", "approval_ids": ["apr_demo_003", "apr_demo_004"]},
     "user_demo_002", "2026-10-22T10:56:00+08:00"),
    ("run.committed", "execution_run", "run_demo_002",
     {"execution_run_id": "run_demo_002", "version_id": "ver_demo_001", "preparation_id": "prep_demo_002"},
     "user_demo_001", "2026-10-22T11:00:00+08:00"),
    ("run.succeeded", "execution_run", "run_demo_002",
     {"execution_run_id": "run_demo_002", "output_records": 1194000, "error_records": 6000},
     "user_demo_004", "2026-10-22T11:26:00+08:00"),
    ("supervision.interrupted", "execution_run", "run_demo_003",
     {"execution_run_id": "run_demo_003", "action": "paused", "snapshot_id": "snap_demo_002"},
     "user_demo_004", "2026-10-20T15:10:00+08:00"),
    ("run.cancelled", "execution_run", "run_demo_004",
     {"execution_run_id": "run_demo_004", "reason": "demo_operator_cancel"},
     "user_demo_004", "2026-10-21T10:12:00+08:00"),
    ("run.rolled_back", "execution_run", "run_demo_006",
     {"execution_run_id": "run_demo_006", "scope": "shadow_tables_only", "result": "cleaned"},
     "user_demo_004", "2026-10-22T16:15:00+08:00"),
    ("version.frozen", "pipeline_version", "ver_demo_003",
     {"version_id": "ver_demo_003", "artifact_digest": sha256_hex(HOCON_LOGS)},
     "user_demo_006", "2026-10-23T11:30:00+08:00"),
]

# ---------------------------------------------------------------------------
# Volume rows (v2, 2026-10-24) — four more projects, 17 more pipelines and a
# realistic preparation/approval/execution history. All static and
# deterministic; existing primary keys are never reused.
# ---------------------------------------------------------------------------

EXTRA_USERS = [
    ("user_demo_008", "maker03", "吴十", "active", "2026-10-03T10:00:00+08:00"),
    ("user_demo_009", "analyst01", "郑十一", "active", "2026-10-03T10:30:00+08:00"),
    ("user_demo_010", "etl_dev01", "冯十二", "active", "2026-10-05T09:00:00+08:00"),
    ("user_demo_011", "etl_dev02", "陈十三", "active", "2026-10-05T09:10:00+08:00"),
    ("user_demo_012", "etl_dev03", "楚十四", "active", "2026-10-06T09:00:00+08:00"),
    ("user_demo_013", "ops02", "卫十五", "active", "2026-10-06T14:00:00+08:00"),
    ("user_demo_014", "ops03", "蒋十六", "active", "2026-10-07T09:00:00+08:00"),
    ("user_demo_015", "auditor02", "沈十七", "active", "2026-10-07T15:00:00+08:00"),
    ("user_demo_016", "checker1_02", "韩十八", "active", "2026-10-08T09:00:00+08:00"),
    ("user_demo_017", "checker2_02", "杨十九", "active", "2026-10-08T09:10:00+08:00"),
    ("user_demo_018", "maker04", "朱二十", "active", "2026-10-09T09:00:00+08:00"),
    ("user_demo_019", "analyst02", "秦二一", "active", "2026-10-09T10:00:00+08:00"),
    ("user_demo_020", "etl_dev04", "尤二二", "active", "2026-10-10T09:00:00+08:00"),
    ("user_demo_021", "ops04", "许二三", "active", "2026-10-10T14:00:00+08:00"),
    ("user_demo_022", "auditor03", "何二四", "active", "2026-10-11T09:00:00+08:00"),
    ("user_demo_023", "maker05", "吕二五", "active", "2026-10-11T10:00:00+08:00"),
    # Boundary: disabled service account, never a project member.
    ("user_demo_024", "svc_etl", "施二六", "disabled", "2026-10-12T09:00:00+08:00"),
    # Harness system actors (2026-10-24): audit_events.actor_id references
    # users, so the Worker / Outbox dispatcher ledger events need real
    # service accounts — otherwise every run.started / outbox.event.* write
    # fails the FK on PostgreSQL (SQLite tests never enforced it).
    ("svc_harness_worker", "svc_harness_worker", "Harness 执行 Worker（系统）",
     "active", "2026-10-24T00:00:00+08:00"),
    ("svc_harness_outbox", "svc_harness_outbox", "Harness Outbox 派发器（系统）",
     "active", "2026-10-24T00:00:00+08:00"),
]

EXTRA_PROJECTS = [
    ("prj_demo_002", "财务数据集成", "finance_demo", "总账、预算与成本数据的集成与对账",
     "2026-10-02T09:00:00+08:00"),
    ("prj_demo_003", "用户行为分析", "behavior_demo", "App/小程序埋点行为的采集与分析",
     "2026-10-04T09:00:00+08:00"),
    ("prj_demo_004", "物流数据平台", "logistics_demo", "运单、车辆与时效数据的入仓分析",
     "2026-10-06T09:00:00+08:00"),
    ("prj_demo_005", "集团报表中心", "report_demo", "跨系统手工与接口报表的统一归集",
     "2026-10-08T09:00:00+08:00"),
]

# (id, project_id, user_id, role)
EXTRA_MEMBERSHIPS = [
    ("mem_demo_007", "prj_demo_001", "user_demo_008", "maker"),
    ("mem_demo_008", "prj_demo_001", "user_demo_013", "ops"),
    ("mem_demo_009", "prj_demo_001", "user_demo_015", "auditor"),
    ("mem_demo_010", "prj_demo_001", "user_demo_016", "checker1"),
    ("mem_demo_011", "prj_demo_002", "user_demo_011", "maker"),
    ("mem_demo_012", "prj_demo_002", "user_demo_012", "maker"),
    ("mem_demo_013", "prj_demo_002", "user_demo_014", "ops"),
    ("mem_demo_014", "prj_demo_002", "user_demo_016", "checker1"),
    ("mem_demo_015", "prj_demo_002", "user_demo_017", "checker2"),
    ("mem_demo_016", "prj_demo_002", "user_demo_022", "auditor"),
    ("mem_demo_017", "prj_demo_003", "user_demo_009", "maker"),
    ("mem_demo_018", "prj_demo_003", "user_demo_010", "maker"),
    ("mem_demo_019", "prj_demo_003", "user_demo_013", "ops"),
    ("mem_demo_020", "prj_demo_003", "user_demo_016", "checker1"),
    ("mem_demo_021", "prj_demo_003", "user_demo_017", "checker2"),
    ("mem_demo_022", "prj_demo_004", "user_demo_018", "maker"),
    ("mem_demo_023", "prj_demo_004", "user_demo_020", "maker"),
    ("mem_demo_024", "prj_demo_004", "user_demo_021", "ops"),
    ("mem_demo_025", "prj_demo_004", "user_demo_016", "checker1"),
    ("mem_demo_026", "prj_demo_004", "user_demo_017", "checker2"),
    ("mem_demo_027", "prj_demo_005", "user_demo_023", "maker"),
    ("mem_demo_028", "prj_demo_005", "user_demo_019", "maker"),
    ("mem_demo_029", "prj_demo_005", "user_demo_014", "ops"),
    ("mem_demo_030", "prj_demo_999", "user_demo_018", "maker"),
    ("mem_demo_031", "prj_demo_999", "user_demo_021", "ops"),
    ("mem_demo_032", "prj_demo_999", "user_demo_016", "checker1"),
    ("mem_demo_033", "prj_demo_999", "user_demo_017", "checker2"),
]

EXTRA_ROLE_GRANTS = [
    ("grant_demo_003", "prj_demo_002", "user_demo_016", "data_checker"),
    ("grant_demo_004", "prj_demo_002", "user_demo_017", "security_checker"),
    ("grant_demo_005", "prj_demo_003", "user_demo_016", "data_checker"),
    ("grant_demo_006", "prj_demo_003", "user_demo_017", "security_checker"),
    ("grant_demo_007", "prj_demo_004", "user_demo_016", "data_checker"),
    ("grant_demo_008", "prj_demo_004", "user_demo_017", "security_checker"),
    ("grant_demo_009", "prj_demo_999", "user_demo_016", "data_checker"),
    ("grant_demo_010", "prj_demo_999", "user_demo_017", "security_checker"),
]

# Per-pipeline technical profile for HOCON / plan generation.
PIPELINE_SPECS = {
    "pipe_demo_002": ("crm_contacts", "doris_crm_agg", "10.30.*.*", "manual"),
    "pipe_demo_003": ("clickhouse_logs", "logs_ods", "172.16.*.*", "hourly"),
    "pipe_demo_004": ("erp_inventory", "doris_inventory", "10.20.*.*", "manual"),
    "pipe_demo_005": ("pay_gateway", "doris_payment", "10.20.*.*", "hourly"),
    "pipe_demo_006": ("user_tags", "mkt_profile", "10.25.*.*", "daily"),
    "pipe_demo_007": ("oracle_gl", "doris_voucher", "10.40.*.*", "daily"),
    "pipe_demo_008": ("cost_center", "doris_cost", "10.40.*.*", "manual"),
    "pipe_demo_009": ("oracle_budget", "doris_budget", "10.40.*.*", "daily"),
    "pipe_demo_010": ("app_event_log", "doris_events", "192.168.*.*", "hourly"),
    "pipe_demo_011": ("doris_events", "doris_funnel", "192.168.*.*", "daily"),
    "pipe_demo_012": ("doris_events", "doris_retention", "192.168.*.*", "daily"),
    "pipe_demo_013": ("tms_waybill", "doris_waybill", "10.50.*.*", "hourly"),
    "pipe_demo_014": ("doris_waybill", "doris_eta", "10.50.*.*", "manual"),
    "pipe_demo_015": ("gps_stream", "doris_gps", "10.50.*.*", "hourly"),
    "pipe_demo_016": ("hr_attend", "doris_hr", "10.60.*.*", "manual"),
    "pipe_demo_017": ("srm_supplier", "doris_supplier", "10.60.*.*", "daily"),
    "pipe_demo_018": ("erp_api", "doris_erp", "api.***", "manual"),
    "pipe_demo_019": ("excel_upload", "doris_report", "minio.***", "manual"),
    "pipe_demo_020": ("kafka_events", "doris_events_rt", "192.168.*.*", "hourly"),
}

# (id, project_id, name, code, description, status, created)
EXTRA_PIPELINES = [
    ("pipe_demo_004", "prj_demo_001", "库存同步", "inventory_sync", "ERP 库存表到 Doris 的准实时同步", "active", "2026-10-03T10:00:00+08:00"),
    ("pipe_demo_005", "prj_demo_001", "支付流水入仓", "payment_flow", "支付网关流水批量入仓", "active", "2026-10-04T10:00:00+08:00"),
    ("pipe_demo_006", "prj_demo_001", "用户画像同步", "user_profile_sync", "用户标签到营销系统的同步", "draft", "2026-10-05T10:00:00+08:00"),
    ("pipe_demo_007", "prj_demo_002", "财务凭证抽取", "finance_voucher", "Oracle 总账凭证抽取入仓", "active", "2026-10-05T09:00:00+08:00"),
    ("pipe_demo_008", "prj_demo_002", "成本分摊计算", "cost_alloc", "成本中心分摊宽表加工", "draft", "2026-10-06T09:00:00+08:00"),
    ("pipe_demo_009", "prj_demo_002", "预算实况对账", "budget_actual", "预算与实际支出对账宽表", "active", "2026-10-07T09:00:00+08:00"),
    ("pipe_demo_010", "prj_demo_003", "行为事件采集", "app_events", "App 埋点事件批量入仓", "active", "2026-10-06T14:00:00+08:00"),
    ("pipe_demo_011", "prj_demo_003", "漏斗聚合", "funnel_agg", "转化漏斗日聚合", "draft", "2026-10-08T09:00:00+08:00"),
    ("pipe_demo_012", "prj_demo_003", "留存计算", "retention_calc", "次日/7日留存宽表", "active", "2026-10-08T14:00:00+08:00"),
    ("pipe_demo_013", "prj_demo_004", "运单同步", "waybill_sync", "TMS 运单表同步入仓", "active", "2026-10-07T09:00:00+08:00"),
    ("pipe_demo_014", "prj_demo_004", "路径时效分析", "route_eta", "运输路径时效分析宽表", "draft", "2026-10-09T09:00:00+08:00"),
    ("pipe_demo_015", "prj_demo_004", "车辆GPS入仓", "vehicle_gps", "车载 GPS 轨迹入仓", "active", "2026-10-09T14:00:00+08:00"),
    ("pipe_demo_016", "prj_demo_999", "人事考勤同步", "hr_attend", "HR 系统考勤月度归档", "draft", "2026-10-10T09:00:00+08:00"),
    ("pipe_demo_017", "prj_demo_999", "供应商主数据", "supplier_master", "供应商主数据统一入仓", "active", "2026-10-10T14:00:00+08:00"),
    ("pipe_demo_018", "prj_demo_999", "ERP 接口拉取", "erp_api_pull", "ERP REST 接口定时拉取", "draft", "2026-10-11T09:00:00+08:00"),
    ("pipe_demo_019", "prj_demo_002", "手工报表导入", "excel_import", "财务手工报表 Excel 归集", "draft", "2026-10-24T09:00:00+08:00"),
    ("pipe_demo_020", "prj_demo_003", "Kafka 实时接入", "kafka_realtime", "Kafka 行为流准实时入仓", "active", "2026-10-23T14:00:00+08:00"),
]

_MAPPING_PRESETS = (
    [
        {"source": "id", "target": "id", "transform": "direct"},
        {"source": "phone", "target": "phone", "transform": "mask_phone"},
        {"source": "amount", "target": "amount", "transform": "direct"},
    ],
    [
        {"source": "event_id", "target": "event_id", "transform": "direct"},
        {"source": "user_id", "target": "user_id", "transform": "hash"},
        {"source": "occur_at", "target": "occur_at", "transform": "direct"},
    ],
    [
        {"source": "code", "target": "code", "transform": "direct"},
        {"source": "name", "target": "name", "transform": "direct"},
        {"source": "contact", "target": "contact", "transform": "mask_email"},
    ],
)


def _hocon_for(pipe_id: str) -> str:
    source, target, host, _ = PIPELINE_SPECS[pipe_id]
    return (
        f'source {{ host = "{host}" user = "etl_***" }}\n'
        f'sink {{ table = "{target}_shadow" }}  # {source}'
    )


def _plan_for(pipe_id: str, index: int) -> dict:
    source, target, _, mode = PIPELINE_SPECS[pipe_id]
    return {
        "source": source,
        "target": target,
        "mappings": _MAPPING_PRESETS[index % len(_MAPPING_PRESETS)],
        "schedule": {"mode": mode},
    }


# (ver_id, pipeline_id, version_number, kind, created, updated)
# kind: frozen = immutable with content; plan = draft with plan only; empty = bare draft.
VERSION_PLAN = [
    ("ver_demo_004", "pipe_demo_002", 1, "plan", "2026-10-10T10:00:00+08:00", "2026-10-11T15:00:00+08:00"),
    ("ver_demo_005", "pipe_demo_003", 2, "empty", "2026-10-11T09:00:00+08:00", "2026-10-11T09:30:00+08:00"),
    ("ver_demo_006", "pipe_demo_004", 1, "frozen", "2026-10-12T09:00:00+08:00", "2026-10-12T11:00:00+08:00"),
    ("ver_demo_007", "pipe_demo_005", 1, "frozen", "2026-10-13T10:00:00+08:00", "2026-10-13T12:00:00+08:00"),
    ("ver_demo_008", "pipe_demo_006", 1, "plan", "2026-10-14T09:00:00+08:00", "2026-10-14T17:00:00+08:00"),
    ("ver_demo_009", "pipe_demo_007", 1, "frozen", "2026-10-14T10:00:00+08:00", "2026-10-14T12:30:00+08:00"),
    ("ver_demo_010", "pipe_demo_007", 2, "frozen", "2026-10-19T09:00:00+08:00", "2026-10-19T10:00:00+08:00"),
    ("ver_demo_011", "pipe_demo_008", 1, "plan", "2026-10-15T09:00:00+08:00", "2026-10-16T11:00:00+08:00"),
    ("ver_demo_012", "pipe_demo_009", 1, "frozen", "2026-10-15T14:00:00+08:00", "2026-10-15T16:00:00+08:00"),
    ("ver_demo_013", "pipe_demo_010", 1, "frozen", "2026-10-16T09:00:00+08:00", "2026-10-16T10:30:00+08:00"),
    ("ver_demo_014", "pipe_demo_010", 2, "frozen", "2026-10-21T09:00:00+08:00", "2026-10-21T10:00:00+08:00"),
    ("ver_demo_015", "pipe_demo_011", 1, "plan", "2026-10-17T10:00:00+08:00", "2026-10-17T16:00:00+08:00"),
    ("ver_demo_016", "pipe_demo_012", 1, "frozen", "2026-10-17T14:00:00+08:00", "2026-10-17T15:30:00+08:00"),
    ("ver_demo_017", "pipe_demo_012", 2, "frozen", "2026-10-22T09:00:00+08:00", "2026-10-22T09:40:00+08:00"),
    ("ver_demo_018", "pipe_demo_013", 1, "frozen", "2026-10-18T09:00:00+08:00", "2026-10-18T10:00:00+08:00"),
    ("ver_demo_019", "pipe_demo_014", 1, "empty", "2026-10-19T10:00:00+08:00", "2026-10-19T10:20:00+08:00"),
    ("ver_demo_020", "pipe_demo_015", 1, "frozen", "2026-10-19T14:00:00+08:00", "2026-10-19T15:00:00+08:00"),
    ("ver_demo_021", "pipe_demo_015", 2, "plan", "2026-10-23T09:00:00+08:00", "2026-10-23T11:00:00+08:00"),
    ("ver_demo_022", "pipe_demo_016", 1, "plan", "2026-10-20T09:00:00+08:00", "2026-10-20T15:00:00+08:00"),
    ("ver_demo_023", "pipe_demo_017", 1, "frozen", "2026-10-20T10:00:00+08:00", "2026-10-20T11:00:00+08:00"),
    ("ver_demo_024", "pipe_demo_018", 1, "plan", "2026-10-21T14:00:00+08:00", "2026-10-21T18:00:00+08:00"),
    ("ver_demo_025", "pipe_demo_019", 1, "empty", "2026-10-24T09:30:00+08:00", "2026-10-24T09:35:00+08:00"),
    ("ver_demo_026", "pipe_demo_020", 1, "frozen", "2026-10-23T14:30:00+08:00", "2026-10-23T16:00:00+08:00"),
    ("ver_demo_027", "pipe_demo_020", 2, "frozen", "2026-10-24T13:30:00+08:00", "2026-10-24T14:00:00+08:00"),
]

FROZEN_VERSIONS = [v for v in VERSION_PLAN if v[3] == "frozen"]
PLAN_VERSIONS = [v for v in VERSION_PLAN if v[3] == "plan"]


# Agent runs: every frozen version was produced by a completed agent run;
# drafts hold interrupted / running sessions (Spec FR-STUDIO states).
EXTRA_AGENT_RUNS: list[tuple] = []
for index, (ver_id, pipe_id, _num, _kind, created, updated) in enumerate(FROZEN_VERSIONS):
    EXTRA_AGENT_RUNS.append(
        (f"agent_demo_{index + 4:03d}", ver_id, f"thread_demo_{index + 4:03d}",
         f"生成 {_plan_for(pipe_id, index)['target']} 链路（演示）",
         "completed", 5 + index % 4, None,
         created, updated)
    )
EXTRA_AGENT_RUNS += [
    ("agent_demo_018", "ver_demo_004", "thread_demo_018",
     "生成 CRM 聚合字段映射（演示）", "interrupted", 3, None,
     "2026-10-11T14:00:00+08:00", "2026-10-11T14:05:00+08:00"),
    ("agent_demo_019", "ver_demo_008", "thread_demo_019",
     "生成用户标签同步链路（演示）", "interrupted", 4, None,
     "2026-10-14T16:00:00+08:00", "2026-10-14T16:06:00+08:00"),
    ("agent_demo_020", "ver_demo_011", "thread_demo_020",
     "生成分摊规则草案（演示）", "interrupted", 2, None,
     "2026-10-15T15:00:00+08:00", "2026-10-15T15:04:00+08:00"),
    ("agent_demo_021", "ver_demo_015", "thread_demo_021",
     "生成漏斗口径映射（演示）", "interrupted", 3, None,
     "2026-10-17T15:00:00+08:00", "2026-10-17T15:05:00+08:00"),
    ("agent_demo_022", "ver_demo_021", "thread_demo_022",
     "生成 GPS 轨迹清洗链路（演示）", "interrupted", 4, None,
     "2026-10-23T09:20:00+08:00", "2026-10-23T09:26:00+08:00"),
    ("agent_demo_023", "ver_demo_025", "thread_demo_023",
     "生成手工报表导入链路（演示）", "interrupted", 2, None,
     "2026-10-24T09:35:00+08:00", "2026-10-24T09:40:00+08:00"),
    ("agent_demo_024", "ver_demo_019", "thread_demo_024",
     "生成路径时效宽表链路（演示）", "running", 3, None,
     "2026-10-24T10:00:00+08:00", "2026-10-24T10:05:00+08:00"),
    ("agent_demo_025", "ver_demo_011", "thread_demo_025",
     "恢复分摊规则生成会话（演示）", "running", 5, None,
     "2026-10-24T14:50:00+08:00", "2026-10-24T15:00:00+08:00"),
]

# (prep_id, version_id, project_id, outcome, created)
# outcome: completed → both approved; rejected → data ok, security rejects;
# pending → both waiting. Rejected/pending preparations never commit runs.
PREPARATION_PLAN = [
    ("prep_demo_006", "ver_demo_001", "prj_demo_001", "completed", "2026-10-23T12:00:00+08:00"),
    ("prep_demo_007", "ver_demo_001", "prj_demo_001", "pending", "2026-10-24T08:30:00+08:00"),
    ("prep_demo_008", "ver_demo_003", "prj_demo_001", "completed", "2026-10-23T13:00:00+08:00"),
    ("prep_demo_009", "ver_demo_003", "prj_demo_001", "rejected", "2026-10-21T10:00:00+08:00"),
    ("prep_demo_010", "ver_demo_006", "prj_demo_001", "completed", "2026-10-13T09:00:00+08:00"),
    ("prep_demo_011", "ver_demo_006", "prj_demo_001", "pending", "2026-10-20T09:00:00+08:00"),
    ("prep_demo_012", "ver_demo_007", "prj_demo_001", "completed", "2026-10-14T09:00:00+08:00"),
    ("prep_demo_013", "ver_demo_009", "prj_demo_002", "completed", "2026-10-15T09:00:00+08:00"),
    ("prep_demo_014", "ver_demo_009", "prj_demo_002", "rejected", "2026-10-18T10:00:00+08:00"),
    ("prep_demo_015", "ver_demo_010", "prj_demo_002", "completed", "2026-10-19T11:00:00+08:00"),
    ("prep_demo_016", "ver_demo_012", "prj_demo_002", "completed", "2026-10-16T09:00:00+08:00"),
    ("prep_demo_017", "ver_demo_013", "prj_demo_003", "completed", "2026-10-17T08:00:00+08:00"),
    ("prep_demo_018", "ver_demo_014", "prj_demo_003", "pending", "2026-10-22T10:00:00+08:00"),
    ("prep_demo_019", "ver_demo_016", "prj_demo_003", "completed", "2026-10-18T09:00:00+08:00"),
    ("prep_demo_020", "ver_demo_017", "prj_demo_003", "completed", "2026-10-22T10:30:00+08:00"),
    ("prep_demo_021", "ver_demo_018", "prj_demo_004", "rejected", "2026-10-19T09:00:00+08:00"),
    ("prep_demo_022", "ver_demo_020", "prj_demo_004", "completed", "2026-10-20T09:30:00+08:00"),
    ("prep_demo_023", "ver_demo_023", "prj_demo_999", "pending", "2026-10-21T09:00:00+08:00"),
    ("prep_demo_024", "ver_demo_026", "prj_demo_003", "completed", "2026-10-23T16:30:00+08:00"),
    ("prep_demo_025", "ver_demo_027", "prj_demo_003", "pending", "2026-10-24T14:30:00+08:00"),
]

PROJECT_APPROVERS = {
    "prj_demo_001": ("user_demo_002", "user_demo_003"),
    "prj_demo_002": ("user_demo_016", "user_demo_017"),
    "prj_demo_003": ("user_demo_016", "user_demo_017"),
    "prj_demo_004": ("user_demo_016", "user_demo_017"),
    "prj_demo_999": ("user_demo_016", "user_demo_017"),
}


def build_approval_rows() -> list[dict]:
    from datetime import timedelta

    rows: list[dict] = []
    base = 11
    for index, (prep_id, _ver, project_id, outcome, created) in enumerate(PREPARATION_PLAN):
        data_approver, sec_approver = PROJECT_APPROVERS[project_id]
        if outcome == "completed":
            decisions = (
                ("data_checker", "APPROVED", "approve", data_approver, 5),
                ("security_checker", "APPROVED", "approve", sec_approver, 15),
            )
        elif outcome == "rejected":
            decisions = (
                ("data_checker", "APPROVED", "approve", data_approver, 5),
                ("security_checker", "REJECTED", "reject", sec_approver, 20),
            )
        else:
            decisions = (
                ("data_checker", "PENDING", None, data_approver, None),
                ("security_checker", "PENDING", None, sec_approver, None),
            )
        for slot, status, decision, approver, lag_minutes in decisions:
            apr_id = f"apr_demo_{base + index * 2 + (0 if slot == 'data_checker' else 1):03d}"
            decided_at = (
                ts(created) + timedelta(minutes=lag_minutes) if lag_minutes else None
            )
            rows.append(
                {
                    "id": apr_id,
                    "preparation_id": prep_id,
                    "version_id": _ver,
                    "required_role": slot,
                    "status": status,
                    "decision": decision,
                    "approver_id": approver,
                    "decided_at": decided_at,
                    "created_at": ts(created),
                    "updated_at": decided_at or ts(created),
                }
            )
    return rows


# (id, prep, status, engine_job_id, in, out, err, bytes, started, finished, created, updated)
EXTRA_EXECUTION_RUNS = [
    ("run_demo_007", "prep_demo_010", "succeeded", "job_demo_006",
     480000, 475200, 4800, 983040000,
     "2026-10-13T09:30:00+08:00", "2026-10-13T09:52:00+08:00",
     "2026-10-13T09:25:00+08:00", "2026-10-13T09:52:00+08:00"),
    ("run_demo_008", "prep_demo_010", "succeeded", "job_demo_007",
     512000, 508900, 3100, 1048576000,
     "2026-10-15T02:00:00+08:00", "2026-10-15T02:24:00+08:00",
     "2026-10-15T01:55:00+08:00", "2026-10-15T02:24:00+08:00"),
    ("run_demo_009", "prep_demo_012", "succeeded", "job_demo_008",
     2600000, 2574000, 26000, 5324810240,
     "2026-10-14T09:30:00+08:00", "2026-10-14T10:05:00+08:00",
     "2026-10-14T09:25:00+08:00", "2026-10-14T10:05:00+08:00"),
    ("run_demo_010", "prep_demo_013", "failed", "job_demo_009",
     890000, 808000, 82000, 1822425088,
     "2026-10-15T09:20:00+08:00", "2026-10-15T09:41:00+08:00",
     "2026-10-15T09:15:00+08:00", "2026-10-15T09:41:00+08:00"),
    ("run_demo_011", "prep_demo_013", "succeeded", "job_demo_010",
     905000, 897200, 7800, 1852416000,
     "2026-10-16T02:00:00+08:00", "2026-10-16T02:22:00+08:00",
     "2026-10-16T01:55:00+08:00", "2026-10-16T02:22:00+08:00"),
    ("run_demo_012", "prep_demo_015", "succeeded", "job_demo_011",
     1340000, 1331000, 9000, 2747269120,
     "2026-10-19T11:30:00+08:00", "2026-10-19T11:58:00+08:00",
     "2026-10-19T11:25:00+08:00", "2026-10-19T11:58:00+08:00"),
    ("run_demo_013", "prep_demo_016", "succeeded", "job_demo_012",
     660000, 654000, 6000, 1352663040,
     "2026-10-16T09:20:00+08:00", "2026-10-16T09:40:00+08:00",
     "2026-10-16T09:15:00+08:00", "2026-10-16T09:40:00+08:00"),
    ("run_demo_014", "prep_demo_016", "cancelled", "job_demo_013",
     210000, 156000, 54000, 430080000,
     "2026-10-17T09:00:00+08:00", "2026-10-17T09:11:00+08:00",
     "2026-10-17T08:55:00+08:00", "2026-10-17T09:11:00+08:00"),
    ("run_demo_015", "prep_demo_017", "succeeded", "job_demo_014",
     1750000, 1739000, 11000, 3584000000,
     "2026-10-17T08:15:00+08:00", "2026-10-17T08:47:00+08:00",
     "2026-10-17T08:10:00+08:00", "2026-10-17T08:47:00+08:00"),
    ("run_demo_016", "prep_demo_017", "failed", "job_demo_015",
     1610000, 1465000, 145000, 3297259520,
     "2026-10-18T02:00:00+08:00", "2026-10-18T02:26:00+08:00",
     "2026-10-18T01:55:00+08:00", "2026-10-18T02:26:00+08:00"),
    ("run_demo_017", "prep_demo_019", "succeeded", "job_demo_016",
     720000, 716300, 3700, 1474560000,
     "2026-10-18T09:10:00+08:00", "2026-10-18T09:31:00+08:00",
     "2026-10-18T09:05:00+08:00", "2026-10-18T09:31:00+08:00"),
    ("run_demo_018", "prep_demo_020", "succeeded", "job_demo_017",
     990000, 984100, 5900, 2026651648,
     "2026-10-22T10:45:00+08:00", "2026-10-22T11:08:00+08:00",
     "2026-10-22T10:40:00+08:00", "2026-10-22T11:08:00+08:00"),
    ("run_demo_019", "prep_demo_022", "succeeded", "job_demo_018",
     2850000, 2830000, 20000, 5830080000,
     "2026-10-20T10:00:00+08:00", "2026-10-20T10:38:00+08:00",
     "2026-10-20T09:55:00+08:00", "2026-10-20T10:38:00+08:00"),
    ("run_demo_020", "prep_demo_022", "running", "job_demo_019",
     1520000, 1489000, 31000, 3112896512,
     "2026-10-24T09:02:00+08:00", None,
     "2026-10-24T09:00:00+08:00", "2026-10-24T09:40:00+08:00"),
    ("run_demo_021", "prep_demo_006", "rolled_back", "job_demo_020",
     368000, 0, 368000, 753664000,
     "2026-10-23T12:30:00+08:00", "2026-10-23T12:42:00+08:00",
     "2026-10-23T12:25:00+08:00", "2026-10-23T12:45:00+08:00"),
    ("run_demo_022", "prep_demo_008", "rolled_back", "job_demo_021",
     610000, 0, 610000, 1249026048,
     "2026-10-24T10:42:00+08:00", "2026-10-24T11:05:00+08:00",
     "2026-10-24T10:38:00+08:00", "2026-10-24T13:10:00+08:00"),
    ("run_demo_023", "prep_demo_008", "cancelled", "job_demo_022",
     95000, 71000, 24000, 194560000,
     "2026-10-24T11:32:00+08:00", "2026-10-24T11:35:00+08:00",
     "2026-10-24T11:28:00+08:00", "2026-10-24T11:35:00+08:00"),
    ("run_demo_024", "prep_demo_024", "succeeded", "job_demo_023",
     2100000, 2085000, 15000, 4300000000,
     "2026-10-23T17:31:00+08:00", "2026-10-23T18:20:00+08:00",
     "2026-10-23T17:30:00+08:00", "2026-10-23T18:20:00+08:00"),
    ("run_demo_025", "prep_demo_024", "queued", None,
     0, 0, 0, 0, None, None,
     "2026-10-24T16:00:00+08:00", "2026-10-24T16:00:00+08:00"),
    ("run_demo_026", "prep_demo_006", "running", "job_demo_024",
     780000, 765000, 15000, 1597440000,
     "2026-10-24T15:32:00+08:00", None,
     "2026-10-24T15:30:00+08:00", "2026-10-24T15:45:00+08:00"),
]

EXTRA_FILE_ASSETS = [
    ("file_demo_005", "prj_demo_001", "orders_20261018_***.csv", 18432768, "csv",
     {"fields": [{"name": "order_id", "type": "string"}, {"name": "phone", "type": "string", "masked": True}]},
     "2026-10-19T09:00:00+08:00"),
    ("file_demo_006", "prj_demo_001", "orders_20261019_***.csv", 19922944, "csv", None,
     "2026-10-20T09:00:00+08:00"),
    ("file_demo_007", "prj_demo_001", "refund_***.csv", 2097152, "csv",
     {"fields": [{"name": "refund_id", "type": "string"}]},
     "2026-10-20T14:00:00+08:00"),
    ("file_demo_008", "prj_demo_002", "voucher_202609_***.csv", 8388608, "csv",
     {"fields": [{"name": "voucher_no", "type": "string"}]},
     "2026-10-14T10:00:00+08:00"),
    ("file_demo_009", "prj_demo_002", "budget_***.xlsx", 1572864, "excel", None,
     "2026-10-15T11:00:00+08:00"),
    ("file_demo_010", "prj_demo_002", "cost_alloc_***.csv", 4194304, "csv", None,
     "2026-10-16T09:00:00+08:00"),
    ("file_demo_011", "prj_demo_003", "events_20261020_***.json", 33554432, "json",
     {"fields": [{"name": "event_id", "type": "string"}, {"name": "user_id", "type": "string", "masked": True}]},
     "2026-10-21T08:00:00+08:00"),
    ("file_demo_012", "prj_demo_003", "events_20261021_***.json", 35651584, "json", None,
     "2026-10-22T08:00:00+08:00"),
    ("file_demo_013", "prj_demo_003", "funnel_cfg_***.json", 65536, "json",
     {"fields": [{"name": "step", "type": "string"}]},
     "2026-10-17T10:00:00+08:00"),
    ("file_demo_014", "prj_demo_004", "waybill_***.csv", 52428800, "csv", None,
     "2026-10-19T07:00:00+08:00"),
    ("file_demo_015", "prj_demo_004", "gps_track_***.csv", 88080384, "csv",
     {"fields": [{"name": "vehicle_no", "type": "string"}]},
     "2026-10-20T07:00:00+08:00"),
    ("file_demo_016", "prj_demo_004", "eta_base_***.csv", 12582912, "csv", None,
     "2026-10-19T16:00:00+08:00"),
    ("file_demo_017", "prj_demo_999", "supplier_***.csv", 3145728, "csv",
     {"fields": [{"name": "supplier_code", "type": "string"}]},
     "2026-10-20T11:00:00+08:00"),
    ("file_demo_018", "prj_demo_999", "hr_attend_***.xlsx", 2621440, "excel", None,
     "2026-10-20T15:00:00+08:00"),
    # Boundary: file size just below the 100 MB upload limit.
    ("file_demo_019", "prj_demo_002", "report_finance_***.xlsx", 103809024, "excel", None,
     "2026-10-24T09:50:00+08:00"),
    ("file_demo_020", "prj_demo_003", "sdk_events_***.json", 5242880, "json", None,
     "2026-10-23T15:00:00+08:00"),
    ("file_demo_021", "prj_demo_002", "manual_report_***.xlsx", 8912896, "excel", None,
     "2026-10-24T10:00:00+08:00"),
    ("file_demo_022", "prj_demo_002", "manual_report_***_parsed.json", 4096, "json",
     {"fields": [{"name": "period", "type": "string"}]},
     "2026-10-24T16:00:00+08:00"),
    ("file_demo_023", "prj_demo_001", "doris_ddl_***.json", 12288, "json",
     {"fields": [{"name": "ddl", "type": "string"}]},
     "2026-10-22T16:00:00+08:00"),
    ("file_demo_024", "prj_demo_004", "waybill_20261023_***.csv", 54525952, "csv", None,
     "2026-10-24T07:00:00+08:00"),
]

EXTRA_SNAPSHOTS = [
    ("snap_demo_004", "run_demo_007", {"rows_pct": 99, "bytes_pct": 99, "duration_pct": 88}, "within_budget", None, "2026-10-13T09:40:00+08:00"),
    ("snap_demo_005", "run_demo_008", {"rows_pct": 100, "bytes_pct": 99, "duration_pct": 92}, "within_budget", None, "2026-10-15T02:12:00+08:00"),
    ("snap_demo_006", "run_demo_009", {"rows_pct": 100, "bytes_pct": 98, "duration_pct": 96}, "within_budget", None, "2026-10-14T09:50:00+08:00"),
    ("snap_demo_007", "run_demo_010", {"rows_pct": 100, "bytes_pct": 95, "duration_pct": 104, "error_rate_pct": 9.2}, "budget_exceeded", "paused", "2026-10-15T09:35:00+08:00"),
    ("snap_demo_008", "run_demo_011", {"rows_pct": 100, "bytes_pct": 99, "duration_pct": 90}, "within_budget", None, "2026-10-16T02:12:00+08:00"),
    ("snap_demo_009", "run_demo_012", {"rows_pct": 100, "bytes_pct": 98, "duration_pct": 94}, "within_budget", None, "2026-10-19T11:45:00+08:00"),
    ("snap_demo_010", "run_demo_013", {"rows_pct": 100, "bytes_pct": 99, "duration_pct": 86}, "within_budget", None, "2026-10-16T09:30:00+08:00"),
    ("snap_demo_011", "run_demo_014", {"rows_pct": 31, "bytes_pct": 28, "duration_pct": 40}, "cancelled", "cancelled", "2026-10-17T09:08:00+08:00"),
    ("snap_demo_012", "run_demo_015", {"rows_pct": 100, "bytes_pct": 99, "duration_pct": 91}, "within_budget", None, "2026-10-17T08:35:00+08:00"),
    ("snap_demo_013", "run_demo_016", {"rows_pct": 100, "bytes_pct": 94, "duration_pct": 108, "error_rate_pct": 9.0}, "budget_exceeded", "paused", "2026-10-18T02:18:00+08:00"),
    ("snap_demo_014", "run_demo_017", {"rows_pct": 100, "bytes_pct": 99, "duration_pct": 89}, "within_budget", None, "2026-10-18T09:22:00+08:00"),
    ("snap_demo_015", "run_demo_018", {"rows_pct": 100, "bytes_pct": 98, "duration_pct": 93}, "within_budget", None, "2026-10-22T10:58:00+08:00"),
    ("snap_demo_016", "run_demo_019", {"rows_pct": 100, "bytes_pct": 97, "duration_pct": 95}, "within_budget", None, "2026-10-20T10:25:00+08:00"),
    ("snap_demo_017", "run_demo_020", {"rows_pct": 62, "bytes_pct": 60, "duration_pct": 70}, "within_budget", None, "2026-10-24T09:30:00+08:00"),
    ("snap_demo_018", "run_demo_021", {"rows_pct": 100, "bytes_pct": 96, "duration_pct": 112, "error_rate_pct": 10.4}, "budget_exceeded", "paused", "2026-10-23T12:36:00+08:00"),
    ("snap_demo_019", "run_demo_022", {"rows_pct": 100, "bytes_pct": 95, "duration_pct": 106, "error_rate_pct": 11.2}, "budget_exceeded", "paused", "2026-10-24T11:00:00+08:00"),
    ("snap_demo_020", "run_demo_022", {"rows_pct": 0, "bytes_pct": 0, "duration_pct": 100}, "budget_exceeded", "paused", "2026-10-24T11:05:00+08:00"),
    ("snap_demo_021", "run_demo_023", {"rows_pct": 24, "bytes_pct": 22, "duration_pct": 35}, "cancelled", "cancelled", "2026-10-24T11:34:00+08:00"),
    ("snap_demo_022", "run_demo_024", {"rows_pct": 45, "bytes_pct": 44, "duration_pct": 40}, "within_budget", None, "2026-10-23T18:00:00+08:00"),
    ("snap_demo_023", "run_demo_024", {"rows_pct": 100, "bytes_pct": 99, "duration_pct": 74}, "within_budget", None, "2026-10-23T18:19:00+08:00"),
    ("snap_demo_024", "run_demo_026", {"rows_pct": 38, "bytes_pct": 37, "duration_pct": 30}, "within_budget", None, "2026-10-24T15:45:00+08:00"),
    ("snap_demo_025", "run_demo_019", {"rows_pct": 88, "bytes_pct": 86, "duration_pct": 80}, "within_budget", None, "2026-10-20T10:15:00+08:00"),
]

# Recent-story audit events (chain continues after evt_demo_015; chronological).
AUDIT_EVENT_DEFS_EXTRA = [
    ("pipeline.created", "pipeline", "pipe_demo_020",
     {"pipeline_id": "pipe_demo_020", "project_id": "prj_demo_003", "code": "kafka_realtime"},
     "user_demo_009", "2026-10-23T14:00:00+08:00"),
    ("agent.run.started", "agent_run", "agent_demo_016",
     {"agent_run_id": "agent_demo_016", "version_id": "ver_demo_026", "thread_id": "thread_demo_016", "provider": "demo"},
     "user_demo_009", "2026-10-23T14:10:00+08:00"),
    ("file.asset.uploaded", "file_asset", "file_demo_020",
     {"file_asset_id": "file_demo_020", "format": "json", "size": 5242880, "source": "upload"},
     "user_demo_009", "2026-10-23T15:00:00+08:00"),
    ("version.frozen", "pipeline_version", "ver_demo_026",
     {"version_id": "ver_demo_026", "artifact_digest": sha256_hex(_hocon_for("pipe_demo_020"))},
     "user_demo_009", "2026-10-23T16:00:00+08:00"),
    ("gate.evaluated", "pipeline_version", "ver_demo_026",
     {"version_id": "ver_demo_026", "syntax": "passed", "schema": "passed", "masking": "passed", "budget": "passed"},
     "user_demo_009", "2026-10-23T16:05:00+08:00"),
    ("preparation.created", "preparation", "prep_demo_024",
     {"preparation_id": "prep_demo_024", "version_id": "ver_demo_026", "risk_level": "P1"},
     "user_demo_009", "2026-10-23T16:30:00+08:00"),
    ("approval.decision.recorded", "approval_request", "apr_demo_047",
     {"approval_id": "apr_demo_047", "decision": "approve", "approver_id": "user_demo_016"},
     "user_demo_016", "2026-10-23T16:35:00+08:00"),
    ("approval.decision.recorded", "approval_request", "apr_demo_048",
     {"approval_id": "apr_demo_048", "decision": "approve", "approver_id": "user_demo_017"},
     "user_demo_017", "2026-10-23T16:45:00+08:00"),
    ("approval.completed", "preparation", "prep_demo_024",
     {"preparation_id": "prep_demo_024", "approval_ids": ["apr_demo_047", "apr_demo_048"]},
     "user_demo_016", "2026-10-23T16:46:00+08:00"),
    ("run.committed", "execution_run", "run_demo_024",
     {"execution_run_id": "run_demo_024", "version_id": "ver_demo_026", "preparation_id": "prep_demo_024"},
     "user_demo_009", "2026-10-23T17:30:00+08:00"),
    ("run.started", "execution_run", "run_demo_024",
     {"execution_run_id": "run_demo_024", "engine_job_id": "job_demo_023"},
     "user_demo_013", "2026-10-23T17:31:00+08:00"),
    ("supervision.warning", "execution_run", "run_demo_024",
     {"execution_run_id": "run_demo_024", "metric": "duration_pct", "value": 40},
     "user_demo_013", "2026-10-23T18:00:00+08:00"),
    ("run.succeeded", "execution_run", "run_demo_024",
     {"execution_run_id": "run_demo_024", "output_records": 2085000, "error_records": 15000},
     "user_demo_013", "2026-10-23T18:20:00+08:00"),
    ("pipeline.created", "pipeline", "pipe_demo_019",
     {"pipeline_id": "pipe_demo_019", "project_id": "prj_demo_002", "code": "excel_import"},
     "user_demo_011", "2026-10-24T09:00:00+08:00"),
    ("agent.run.interrupted", "agent_run", "agent_demo_023",
     {"agent_run_id": "agent_demo_023", "version_id": "ver_demo_025", "question": "目标表 doris_report 不存在，是否创建？"},
     "user_demo_011", "2026-10-24T09:40:00+08:00"),
    ("file.asset.uploaded", "file_asset", "file_demo_021",
     {"file_asset_id": "file_demo_021", "format": "excel", "size": 8912896, "source": "upload"},
     "user_demo_011", "2026-10-24T10:00:00+08:00"),
    ("run.failed", "execution_run", "run_demo_022",
     {"execution_run_id": "run_demo_022", "error_code": "E-3001", "snapshot_id": "snap_demo_019"},
     "user_demo_013", "2026-10-24T11:00:00+08:00"),
    ("supervision.interrupted", "execution_run", "run_demo_022",
     {"execution_run_id": "run_demo_022", "action": "paused", "snapshot_id": "snap_demo_020"},
     "user_demo_013", "2026-10-24T11:05:00+08:00"),
    ("run.cancel_requested", "execution_run", "run_demo_023",
     {"execution_run_id": "run_demo_023", "actor_id": "user_demo_013", "reason": "demo_operator_cancel"},
     "user_demo_013", "2026-10-24T11:30:00+08:00"),
    ("run.cancelled", "execution_run", "run_demo_023",
     {"execution_run_id": "run_demo_023", "reason": "demo_operator_cancel"},
     "user_demo_013", "2026-10-24T11:35:00+08:00"),
    ("run.rollback_requested", "execution_run", "run_demo_022",
     {"execution_run_id": "run_demo_022", "actor_id": "user_demo_013", "scope": "shadow_tables_only"},
     "user_demo_013", "2026-10-24T13:00:00+08:00"),
    ("run.rolled_back", "execution_run", "run_demo_022",
     {"execution_run_id": "run_demo_022", "scope": "shadow_tables_only", "result": "cleaned"},
     "user_demo_013", "2026-10-24T13:10:00+08:00"),
    ("version.frozen", "pipeline_version", "ver_demo_027",
     {"version_id": "ver_demo_027", "artifact_digest": sha256_hex(_hocon_for("pipe_demo_020"))},
     "user_demo_009", "2026-10-24T14:00:00+08:00"),
    ("preparation.created", "preparation", "prep_demo_025",
     {"preparation_id": "prep_demo_025", "version_id": "ver_demo_027", "risk_level": "P1"},
     "user_demo_009", "2026-10-24T14:30:00+08:00"),
    ("agent.run.resumed", "agent_run", "agent_demo_025",
     {"agent_run_id": "agent_demo_025", "thread_id": "thread_demo_025", "answer": "分摊规则已按确认口径更新（演示）"},
     "user_demo_011", "2026-10-24T15:00:00+08:00"),
    ("file.asset.parsed", "file_asset", "file_demo_022",
     {"file_asset_id": "file_demo_022", "column_count": 6, "confidence_digest": sha256_hex("manual_report_parsed")},
     "user_demo_011", "2026-10-24T16:00:00+08:00"),
]


# ---------------------------------------------------------------------------
# Merged row lists (base v1 + volume v2). Existing primary keys are skipped
# on re-run, so appending here never mutates already-seeded rows.
# ---------------------------------------------------------------------------

ALL_USERS = [
    {
        "id": user_id, "username": username, "display_name": display_name,
        "email": email, "status": status,
        "created_at": ts(T_BASE), "updated_at": ts(T_BASE),
    }
    for user_id, username, display_name, email, status in USERS
] + [
    {
        "id": user_id,
        "username": username,
        "display_name": display_name,
        "email": email_for(username),
        "status": status,
        "created_at": ts(created),
        "updated_at": ts(created),
    }
    for user_id, username, display_name, status, created in EXTRA_USERS
]

ALL_PROJECTS = [
    {
        "id": "prj_demo_001", "name": "订单数据集成（演示项目）",
        "code": "orders_demo", "description": "合成演示项目",
        "created_at": ts(T_BASE), "updated_at": ts(T_BASE),
    },
    {
        "id": "prj_demo_999", "name": "其他项目（演示）",
        "code": "other_demo", "description": "合成演示项目",
        "created_at": ts(T_BASE), "updated_at": ts(T_BASE),
    },
] + [
    {
        "id": project_id, "name": name, "code": code,
        "description": description,
        "created_at": ts(created), "updated_at": ts(created),
    }
    for project_id, name, code, description, created in EXTRA_PROJECTS
]

ALL_MEMBERSHIPS = [
    {
        "id": mem_id, "project_id": project_id, "user_id": user_id,
        "role": role, "created_at": ts(T_BASE), "updated_at": ts(T_BASE),
    }
    for mem_id, project_id, user_id, role in MEMBERSHIPS
] + [
    {
        "id": mem_id, "project_id": project_id, "user_id": user_id,
        "role": role, "created_at": ts("2026-10-10T09:00:00+08:00"),
        "updated_at": ts("2026-10-10T09:00:00+08:00"),
    }
    for mem_id, project_id, user_id, role in EXTRA_MEMBERSHIPS
]

ALL_ROLE_GRANTS = [
    {
        "id": grant_id, "project_id": project_id, "user_id": user_id,
        "role_slot": role_slot,
        "created_at": ts(T_BASE), "updated_at": ts(T_BASE),
    }
    for grant_id, project_id, user_id, role_slot in ROLE_GRANTS
] + [
    {
        "id": grant_id, "project_id": project_id, "user_id": user_id,
        "role_slot": role_slot,
        "created_at": ts("2026-10-10T09:00:00+08:00"),
        "updated_at": ts("2026-10-10T09:00:00+08:00"),
    }
    for grant_id, project_id, user_id, role_slot in EXTRA_ROLE_GRANTS
]

ALL_PIPELINES = [
    {
        "id": pipe_id, "project_id": "prj_demo_001",
        "name": name, "code": code, "description": description,
        "status": status,
        "created_at": ts("2026-10-20T10:00:00+08:00"),
        "updated_at": ts("2026-10-20T10:00:00+08:00"),
    }
    for pipe_id, name, code, description, status in PIPELINES
] + [
    {
        "id": pipe_id, "project_id": project_id,
        "name": name, "code": code, "description": description,
        "status": status,
        "created_at": ts(created),
        "updated_at": ts(created) if status == "draft" else ts(_latest(created, "2026-10-22T09:00:00+08:00")),
    }
    for pipe_id, project_id, name, code, description, status, created in EXTRA_PIPELINES
]


def build_version_rows() -> list[dict]:
    rows: list[dict] = []
    for index, (ver_id, pipe_id, number, kind, created, updated) in enumerate(VERSION_PLAN):
        if kind == "frozen":
            hocon = _hocon_for(pipe_id)
            plan = _plan_for(pipe_id, index)
            rows.append(
                {
                    "id": ver_id, "pipeline_id": pipe_id,
                    "version_number": number,
                    "etl_plan_json": plan, "hocon_text": hocon,
                    "artifact_digest": sha256_hex(hocon),
                    "is_immutable": True,
                    "created_at": ts(created), "updated_at": ts(updated),
                }
            )
        elif kind == "plan":
            rows.append(
                {
                    "id": ver_id, "pipeline_id": pipe_id,
                    "version_number": number,
                    "etl_plan_json": _plan_for(pipe_id, index),
                    "hocon_text": None, "artifact_digest": None,
                    "is_immutable": False,
                    "created_at": ts(created), "updated_at": ts(updated),
                }
            )
        else:  # empty draft
            rows.append(
                {
                    "id": ver_id, "pipeline_id": pipe_id,
                    "version_number": number,
                    "etl_plan_json": None, "hocon_text": None,
                    "artifact_digest": None, "is_immutable": False,
                    "created_at": ts(created), "updated_at": ts(updated),
                }
            )
    return rows


_NEW_VERSION_ROWS = build_version_rows()

ALL_VERSIONS = [
    {
        "id": ver_id, "pipeline_id": pipeline_id,
        "version_number": version_number,
        "etl_plan_json": plan, "hocon_text": hocon,
        "artifact_digest": digest, "is_immutable": immutable,
        "created_at": ts(created), "updated_at": ts(created),
    }
    for ver_id, pipeline_id, version_number, plan, hocon, digest, immutable, created in VERSIONS
] + _NEW_VERSION_ROWS

# Artifacts derive from the actual frozen version rows so content and
# digests are guaranteed identical to what the version carries.
_NEW_FROZEN_ROWS = [row for row in _NEW_VERSION_ROWS if row["is_immutable"]]

ALL_ARTIFACTS = [
    {
        "id": art_id, "version_id": version_id,
        "artifact_type": artifact_type,
        "artifact_digest": sha256_hex(content),
        "content": content,
        "created_at": ts("2026-10-23T10:35:00+08:00"),
    }
    for art_id, version_id, artifact_type, content in ARTIFACTS
] + [
    {
        "id": f"art_demo_{pair + 4:03d}",
        "version_id": version_row["id"],
        "artifact_type": artifact_type,
        "artifact_digest": sha256_hex(
            version_row["hocon_text"] if artifact_type == "hocon"
            else canonical_json(version_row["etl_plan_json"])
        ),
        "content": (
            version_row["hocon_text"] if artifact_type == "hocon"
            else canonical_json(version_row["etl_plan_json"])
        ),
        "created_at": version_row["updated_at"],
    }
    for pair, (version_row, artifact_type) in enumerate(
        (row, kind) for row in _NEW_FROZEN_ROWS for kind in ("hocon", "etl_plan")
    )
]

ALL_AGENT_RUNS = [
    {
        "id": run_id, "version_id": version_id,
        "thread_id": thread_id, "prompt": prompt,
        "status": status, "step_count": step_count,
        "error_message": error_message,
        "created_at": ts(created), "updated_at": ts(updated),
    }
    for run_id, version_id, thread_id, prompt, status, step_count,
        error_message, created, updated in AGENT_RUNS
] + [
    {
        "id": run_id, "version_id": version_id,
        "thread_id": thread_id, "prompt": prompt,
        "status": status, "step_count": step_count,
        "error_message": error_message,
        "created_at": ts(created), "updated_at": ts(updated),
    }
    for run_id, version_id, thread_id, prompt, status, step_count,
        error_message, created, updated in EXTRA_AGENT_RUNS
]

ALL_APPROVALS = [
    {
        "id": apr_id, "preparation_id": preparation_id,
        "version_id": "ver_demo_001",
        "required_role": required_role, "status": status,
        "decision": decision, "approver_id": approver_id,
        "decided_at": ts(decided_at) if decided_at else None,
        "created_at": ts("2026-10-20T09:00:00+08:00"),
        "updated_at": ts(decided_at or "2026-10-20T09:00:00+08:00"),
    }
    for apr_id, preparation_id, required_role, status, decision,
        approver_id, decided_at in APPROVALS
] + build_approval_rows()

_PREP_VERSION = {prep_id: ver_id for prep_id, ver_id, _p, _o, _c in PREPARATION_PLAN}


def _version_of(prep_id: str) -> str:
    return _PREP_VERSION[prep_id]


ALL_EXECUTION_RUNS = [
    {
        "id": run_id, "version_id": "ver_demo_001",
        "preparation_id": preparation_id,
        "capability_token_digest": sha256_hex(f"capability-token:{run_id}"),
        "status": status, "engine_job_id": engine_job_id,
        "input_records": input_records,
        "output_records": output_records,
        "error_records": error_records,
        "bytes_processed": bytes_processed,
        "started_at": ts(started) if started else None,
        "finished_at": ts(finished) if finished else None,
        "created_at": ts(created), "updated_at": ts(updated),
    }
    for run_id, preparation_id, status, engine_job_id,
        input_records, output_records, error_records,
        bytes_processed, started, finished, created, updated
    in EXECUTION_RUNS
] + [
    {
        "id": run_id, "version_id": _version_of(prep_id),
        "preparation_id": prep_id,
        "capability_token_digest": sha256_hex(f"capability-token:{run_id}"),
        "status": status, "engine_job_id": engine_job_id,
        "input_records": input_records,
        "output_records": output_records,
        "error_records": error_records,
        "bytes_processed": bytes_processed,
        "started_at": ts(started) if started else None,
        "finished_at": ts(finished) if finished else None,
        "created_at": ts(created), "updated_at": ts(updated),
    }
    for run_id, prep_id, status, engine_job_id,
        input_records, output_records, error_records,
        bytes_processed, started, finished, created, updated
    in EXTRA_EXECUTION_RUNS
]

ALL_FILE_ASSETS = [
    {
        "id": file_id, "project_id": "prj_demo_001",
        "file_name": file_name, "file_path": file_path,
        "file_size": file_size, "file_format": file_format,
        "schema_json": schema_json,
        "created_at": ts(created), "updated_at": ts(created),
    }
    for file_id, file_name, file_path, file_size, file_format,
        schema_json, created in FILE_ASSETS
] + [
    {
        "id": file_id, "project_id": project_id,
        "file_name": file_name, "file_path": "object://files/***",
        "file_size": file_size, "file_format": file_format,
        "schema_json": schema_json,
        "created_at": ts(created), "updated_at": ts(created),
    }
    for file_id, project_id, file_name, file_size, file_format,
        schema_json, created in EXTRA_FILE_ASSETS
]

ALL_SNAPSHOTS = [
    {
        "id": snap_id, "execution_run_id": execution_run_id,
        "metrics_json": metrics_json, "decision": decision,
        "action_taken": action_taken, "created_at": ts(created),
    }
    for snap_id, execution_run_id, metrics_json, decision,
        action_taken, created in SNAPSHOTS
] + [
    {
        "id": snap_id, "execution_run_id": execution_run_id,
        "metrics_json": metrics_json, "decision": decision,
        "action_taken": action_taken, "created_at": ts(created),
    }
    for snap_id, execution_run_id, metrics_json, decision,
        action_taken, created in EXTRA_SNAPSHOTS
]

ALL_AUDIT_DEFS = AUDIT_EVENT_DEFS + AUDIT_EVENT_DEFS_EXTRA

# ---------------------------------------------------------------------------
# Audit chain builder (append-only aware)
# ---------------------------------------------------------------------------


def build_audit_rows(session, project_id: str) -> tuple[list[dict], int]:
    """Create audit rows that extend the existing per-project hash chain.

    Existing rows are never touched (append-only). Skip key is the event id:
    ``event_hash`` depends on the chain position (``prev_event_hash``), so it
    changes for a re-run and cannot identify an already-seeded event. The
    stored hash of a skipped event becomes the chain predecessor for any
    following new event. Returns (rows, skipped).
    """

    existing_by_id = dict(
        session.execute(
            select(AuditEvent.id, AuditEvent.event_hash).where(
                AuditEvent.project_id == project_id
            )
        ).all()
    )
    tail = (
        session.execute(
            select(AuditEvent.event_hash)
            .where(AuditEvent.project_id == project_id)
            .order_by(AuditEvent.created_at, AuditEvent.id)
        )
        .scalars()
        .all()
    )
    prev_hash = tail[-1] if tail else GENESIS_PREV_HASH

    rows: list[dict] = []
    skipped = 0
    for index, (event_type, resource_type, resource_id, payload, actor_id, created) in enumerate(
        ALL_AUDIT_DEFS, start=1
    ):
        event_id = f"evt_demo_{index:03d}"
        payload_digest = sha256_hex(canonical_json(payload))
        if event_id in existing_by_id:
            prev_hash = existing_by_id[event_id]
            skipped += 1
            continue
        row_hash = event_hash_for(
            project_id, actor_id, event_type, resource_type, resource_id,
            payload_digest, prev_hash,
        )
        rows.append(
            {
                "id": event_id,
                "project_id": project_id,
                "actor_id": actor_id,
                "event_type": event_type,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "payload_digest": payload_digest,
                "prev_event_hash": prev_hash,
                "event_hash": row_hash,
                "created_at": ts(created),
            }
        )
        prev_hash = row_hash
    return rows, skipped


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def seed() -> int:
    from db.session import create_db_engine

    engine = create_db_engine()
    totals: dict[str, tuple[int, int]] = {}

    with Session(engine) as session:
        with session.begin():
            totals["users"] = insert_missing(session, User, ALL_USERS)
            totals["projects"] = insert_missing(session, Project, ALL_PROJECTS)
            totals["project_memberships"] = insert_missing(
                session, ProjectMembership, ALL_MEMBERSHIPS
            )
            totals["project_role_grants"] = insert_missing(
                session, ProjectRoleGrant, ALL_ROLE_GRANTS
            )
            totals["pipelines"] = insert_missing(session, Pipeline, ALL_PIPELINES)
            totals["pipeline_versions"] = insert_missing(
                session, PipelineVersion, ALL_VERSIONS
            )
            totals["pipeline_artifacts"] = insert_missing(
                session, PipelineArtifact, ALL_ARTIFACTS
            )
            totals["agent_runs"] = insert_missing(session, AgentRun, ALL_AGENT_RUNS)
            totals["approval_requests"] = insert_missing(
                session, ApprovalRequest, ALL_APPROVALS
            )
            totals["execution_runs"] = insert_missing(
                session, ExecutionRun, ALL_EXECUTION_RUNS
            )
            totals["file_assets"] = insert_missing(session, FileAsset, ALL_FILE_ASSETS)
            totals["runtime_supervision_snapshots"] = insert_missing(
                session, RuntimeSupervisionSnapshot, ALL_SNAPSHOTS
            )

            audit_rows, reused = build_audit_rows(session, "prj_demo_001")
            session.add_all([AuditEvent(**row) for row in audit_rows])
            totals["audit_events"] = (len(audit_rows), reused)

    engine.dispose()

    print("Seed complete (inserted, skipped):")
    for table, (inserted, skipped) in totals.items():
        print(f"  {table:32s} inserted={inserted:3d} skipped={skipped:3d}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override the DATABASE_URL environment variable",
    )
    args = parser.parse_args()
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url
    return seed()


if __name__ == "__main__":
    raise SystemExit(main())



