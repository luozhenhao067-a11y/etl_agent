"""Export the live database structure to 项目信息/数据结构.json.

Introspects the SQLAlchemy 2.0 declarative models (backendpoint/app/models/tables.py)
for columns / PK / FK / unique / check / index definitions, then queries the live
database for row counts and the actual distinct values of every enum-ish column.
Table purposes, sensitive fields and lifecycles come verbatim from spec.md 10.1.

Connection string is read from DATABASE_URL (or --database-url). The password is
never written to the JSON — the URL is rendered with the password masked.

Usage:
    export DATABASE_URL='postgresql+psycopg://...'
    python 建表/export_schema_json.py
"""

from __future__ import annotations

import argparse
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
from sqlalchemy.engine import make_url  # noqa: E402
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
from db.session import create_db_engine  # noqa: E402

MODELS = {
    "users": User,
    "projects": Project,
    "project_memberships": ProjectMembership,
    "project_role_grants": ProjectRoleGrant,
    "pipelines": Pipeline,
    "pipeline_versions": PipelineVersion,
    "pipeline_artifacts": PipelineArtifact,
    "agent_runs": AgentRun,
    "approval_requests": ApprovalRequest,
    "execution_runs": ExecutionRun,
    "file_assets": FileAsset,
    "runtime_supervision_snapshots": RuntimeSupervisionSnapshot,
    "audit_events": AuditEvent,
}

# Columns whose actual distinct values are sampled from the live database.
ENUM_COLUMNS = {
    "users": ["status"],
    "project_memberships": ["role"],
    "project_role_grants": ["role_slot"],
    "pipelines": ["status"],
    "pipeline_artifacts": ["artifact_type"],
    "agent_runs": ["status"],
    "approval_requests": ["required_role", "status", "decision"],
    "execution_runs": ["status"],
    "file_assets": ["file_format"],
    "runtime_supervision_snapshots": ["decision", "action_taken"],
    "audit_events": ["event_type", "resource_type"],
}

# Verbatim from spec.md 10.1 数据表清单.
SPEC_META = {
    "users": {
        "用途": "用户身份",
        "对应FR": "PRD 2.8.1",
        "敏感字段": [{"字段": "email", "说明": "演示数据已脱敏（m***@example.com 样式）"}],
        "生命周期": "禁用不删除；保留策略待确认",
    },
    "projects": {
        "用途": "多租户项目",
        "对应FR": "PRD 2.8.1",
        "敏感字段": [],
        "生命周期": "归档字段未定义；生命周期待确认",
    },
    "project_memberships": {
        "用途": "项目成员",
        "对应FR": "PRD 2.8.2、2.8.11",
        "敏感字段": [],
        "生命周期": "成员移除需审计；是否软删待确认",
    },
    "project_role_grants": {
        "用途": "职责槽授权",
        "对应FR": "PRD 2.8.2；FR-RUN-01",
        "敏感字段": [],
        "生命周期": "变更需审计；历史保留待确认",
    },
    "pipelines": {
        "用途": "Pipeline 定义",
        "对应FR": "FR-STUDIO-01、FR-STUDIO-04",
        "敏感字段": [],
        "生命周期": "归档/删除待确认",
    },
    "pipeline_versions": {
        "用途": "不可变版本",
        "对应FR": "FR-STUDIO-04；FR-RUN-01",
        "敏感字段": [{"字段": "hocon_text", "说明": "可能含主机/账号信息，需脱敏（演示已用 10.20.*.* 掩码）"}],
        "生命周期": "不可变版本永久保留；删除禁止",
    },
    "pipeline_artifacts": {
        "用途": "版本制品",
        "对应FR": "FR-STUDIO-03、FR-STUDIO-04",
        "敏感字段": [{"字段": "content", "说明": "禁止含 Secret 明文（verify_smoke.py 已扫描）"}],
        "生命周期": "随版本不可变；长期保留",
    },
    "agent_runs": {
        "用途": "Agent 运行",
        "对应FR": "FR-STUDIO-02、FR-STUDIO-06、FR-STUDIO-07",
        "敏感字段": [
            {"字段": "prompt", "说明": "可能含业务敏感信息"},
            {"字段": "error_message", "说明": "需脱敏"},
        ],
        "生命周期": "保留用于恢复与审计；期限待确认",
    },
    "approval_requests": {
        "用途": "审批请求",
        "对应FR": "FR-RUN-01",
        "敏感字段": [{"字段": "decision/approver_id", "说明": "审批意见可能含敏感信息，需脱敏"}],
        "生命周期": "只追加；保留策略待确认",
    },
    "execution_runs": {
        "用途": "执行实例",
        "对应FR": "FR-RUN-02、FR-RUN-03、FR-RUN-04、FR-RUN-05",
        "敏感字段": [{"字段": "capability_token_digest", "说明": "仅存 SHA256 摘要，Capability 明文绝不落库"}],
        "生命周期": "长期保留；清理策略待确认",
    },
    "file_assets": {
        "用途": "文件资产元数据",
        "对应FR": "FR-FILE-01、FR-FILE-02",
        "敏感字段": [{"字段": "file_path/file_name", "说明": "可能含敏感信息（演示已用 object://files/*** 掩码）"}],
        "生命周期": "原文件在对象存储；元数据生命周期待确认",
    },
    "runtime_supervision_snapshots": {
        "用途": "运行监督快照",
        "对应FR": "FR-RUN-02、FR-RUN-05",
        "敏感字段": [{"字段": "metrics_json", "说明": "不含原始业务值，仅指标聚合"}],
        "生命周期": "只追加；保留期限待确认",
    },
    "audit_events": {
        "用途": "审计证据账本",
        "对应FR": "FR-RUN-03、FR-RUN-05、FR-GOV-04；PRD 2.8.6",
        "敏感字段": [{"字段": "payload_digest", "说明": "仅存载荷摘要，禁止原始敏感载荷"}],
        "生命周期": "只追加；永久保留或按合规期限",
    },
}

# Tamper-evidence implemented in 0001 migration triggers + db/guards.py.
PROTECTION = {
    "audit_events": "只追加账本：DB 触发器禁 UPDATE/DELETE/TRUNCATE；ORM event.listen 抛 ImmutableRecordError；SHA256 哈希链（prev_event_hash 串联，创世为 64 个 0）",
    "pipeline_versions": "is_immutable=true 后 etl_plan_json/hocon_text/artifact_digest 禁改、禁解冻，且整表禁 DELETE：DB 触发器 + ORM 守卫双重保护",
    "approval_requests": "已决策（decision 非 NULL）记录禁改 decision/approver_id/decided_at：DB 触发器",
    "runtime_supervision_snapshots": "只追加（应用层约定，无更新入口）",
}

KEY_RULES = [
    "不可变版本：is_immutable=true 后内容字段禁止修改，应用层与数据库触发器双重保护",
    "摘要格式：artifact_digest、capability_token_digest、event_hash、prev_event_hash 均为小写 64 位十六进制 SHA256",
    "单次执行：capability_token_digest UNIQUE，同一令牌摘要只能对应一个 Run",
    "审批唯一：同一 preparation_id + required_role 只能有一条审批请求",
    "审批不可撤销：已决策记录禁止更新 decision/approver_id/decided_at",
    "账本只追加：audit_events 禁止 UPDATE/DELETE，修正以新事件追加",
    "哈希链：每条事件引用同项目前序 event_hash，创世前缀为固定零串",
    "计数非负：执行行数、字节数、错误数均 >= 0",
    "敏感字段：禁止保存 Secret 明文、密码、Capability 明文、原始敏感样本",
    "外键：project_id、version_id、preparation_id、execution_run_id、approver_id 均建立外键",
]


def column_info(column) -> dict:
    fk = list(column.foreign_keys)[0] if column.foreign_keys else None
    return {
        "字段": column.name,
        "类型": str(column.type),
        "可空": column.nullable,
        "默认": str(column.default.arg) if column.default is not None else None,
        "主键": column.primary_key,
        "外键": {
            "引用": fk.target_fullname,
            "ondelete": fk.ondelete,
        } if fk else None,
        "唯一": column.unique,
    }


def table_constraints(table) -> dict:
    uniques, checks = [], []
    for constraint in sorted(table.constraints, key=lambda c: c.name or ""):
        if constraint.__class__.__name__ == "UniqueConstraint":
            uniques.append([col.name for col in constraint.columns])
        elif constraint.__class__.__name__ == "CheckConstraint":
            checks.append(constraint.sqltext.text if hasattr(constraint.sqltext, "text") else str(constraint.sqltext))
    indexes = [
        {"字段": [col.name for col in index.columns], "唯一": index.unique}
        for index in sorted(table.indexes, key=lambda i: i.name or "")
    ]
    return {"唯一约束": uniques, "检查约束": checks, "索引": indexes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()
    if not args.database_url:
        parser.error("DATABASE_URL 未设置")
    os.environ["DATABASE_URL"] = args.database_url  # create_db_engine reads it from the env
    engine = create_db_engine()
    db_url = make_url(args.database_url).render_as_string(hide_password=True)

    tables_json: list[dict] = []
    total_rows = 0
    with Session(engine) as session:
        for name, model in MODELS.items():
            table = model.__table__
            row_count = session.execute(select(model.id)).scalars().all()
            total_rows += len(row_count)

            enums = {}
            for column_name in ENUM_COLUMNS.get(name, []):
                values = session.execute(
                    select(getattr(model, column_name)).distinct().order_by(getattr(model, column_name))
                ).scalars().all()
                enums[column_name] = values

            meta = SPEC_META[name]
            constraints = table_constraints(table)
            tables_json.append({
                "表名": name,
                "用途": meta["用途"],
                "对应FR": meta["对应FR"],
                "行数": len(row_count),
                "字段": [column_info(col) for col in table.columns],
                "外键汇总": [
                    {"字段": col.name, "引用": list(col.foreign_keys)[0].target_fullname,
                     "ondelete": list(col.foreign_keys)[0].ondelete}
                    for col in table.columns if col.foreign_keys
                ],
                **constraints,
                "枚举实际取值": enums,
                "敏感字段": meta["敏感字段"],
                "生命周期": meta["生命周期"],
                "保护机制": PROTECTION.get(name, "无特殊保护"),
            })

    payload = {
        "meta": {
            "标题": "ETL-Agent 数据集成平台 — 数据结构",
            "生成时间": datetime.now().astimezone().isoformat(timespec="seconds"),
            "数据库": db_url,
            "规范来源": "项目信息/spec.md 10.1 数据表清单、10.2 关键数据规则",
            "模型文件": "backendpoint/app/models/tables.py（SQLAlchemy 2.0 声明式）",
            "迁移文件": "backendpoint/migrations/versions/0001_initial_13_tables.py",
            "演示数据脚本": "建表/seed_data.py（幂等，可重复执行）",
            "表数量": len(tables_json),
            "总行数": total_rows,
            "说明": "行数与枚举实际取值为导出时数据库快照；演示数据覆盖正常/异常/边界场景，敏感值均为脱敏样式",
        },
        "关键数据规则": KEY_RULES,
        "tables": tables_json,
    }

    out_path = ROOT.parent / "项目信息" / "数据结构.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    engine.dispose()
    print(f"written: {out_path} ({len(tables_json)} tables, {total_rows} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
