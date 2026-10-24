# ETL-Agent Alembic 建表记录

- 日期：2026-10-23
- 依据：`项目信息/spec.md` 10.1 数据表清单（PRD 7.1 的 13 张表）、10.2 关键数据规则
- 迁移脚本：`backendpoint/migrations/versions/0001_initial_13_tables.py`
- 模型：`backendpoint/app/models/tables.py`
- 数据库目标：PostgreSQL（P-28 版本与拓扑仍待确认）

## 一、建表范围

只创建 Spec 10.1 列出的 13 张业务表：

`users`、`projects`、`project_memberships`、`project_role_grants`、`pipelines`、`pipeline_versions`、`pipeline_artifacts`、`agent_runs`、`approval_requests`、`execution_runs`、`file_assets`、`runtime_supervision_snapshots`、`audit_events`。

Alembic 自动创建的 `alembic_version` 属于工具元数据，不计入业务表。连接配置、元数据 Profile、Preparation、Outbox、Capability 消费记录、Benchmark 结果等未定义实体没有建表，仍保留在进程内存。

## 二、约束与索引

| 表 | 主要约束 / 索引 |
|---|---|
| `users` | PK；UNIQUE `username`、`email`；索引 `status` |
| `projects` | PK；UNIQUE `code` |
| `project_memberships` | PK；FK `project_id`、`user_id`；UNIQUE `(project_id,user_id)`；索引 `user_id`、`(project_id,role)` |
| `project_role_grants` | PK；FK `project_id`、`user_id`；UNIQUE `(project_id,user_id,role_slot)`；索引 `(project_id,role_slot)` |
| `pipelines` | PK；FK `project_id`；UNIQUE `(project_id,code)`；索引 `(project_id,status)` |
| `pipeline_versions` | PK；FK `pipeline_id`；UNIQUE `(pipeline_id,version_number)`；`artifact_digest` 64 位小写 SHA256 检查；索引 `(pipeline_id,created_at)`、`artifact_digest` |
| `pipeline_artifacts` | PK；FK `version_id`；UNIQUE `(version_id,artifact_type,artifact_digest)`；摘要格式检查；索引 `(version_id,artifact_type)` |
| `agent_runs` | PK；FK `version_id`；`step_count >= 0`；索引 `(version_id,created_at)`、`thread_id` |
| `approval_requests` | PK；FK `version_id`、`approver_id`；UNIQUE `(preparation_id,required_role)`；索引 `preparation_id`、`(approver_id,status)`、`version_id` |
| `execution_runs` | PK；FK `version_id`；`capability_token_digest` UNIQUE 且格式检查；四项计数 `>= 0`；索引 `(version_id,created_at)`、`preparation_id`、`status`、`engine_job_id` |
| `file_assets` | PK；FK `project_id`；`file_size >= 0`；索引 `(project_id,created_at)`、`file_format` |
| `runtime_supervision_snapshots` | PK；FK `execution_run_id`；索引 `(execution_run_id,created_at)` |
| `audit_events` | PK；FK `project_id`、`actor_id`；UNIQUE `event_hash`；摘要/哈希 64 位小写检查；索引 `(project_id,created_at)`、`(resource_type,resource_id)`、`event_type` |

摘要字段在 PostgreSQL 使用 `JSONB`（`etl_plan_json`、`schema_json`、`metrics_json`），以便触发器按值比较；SQLite 迁移测试使用 JSON。

## 三、不可变保护

| 对象 | 数据库保护 | 说明 |
|---|---|---|
| `audit_events` | `BEFORE UPDATE`、`BEFORE DELETE`、`BEFORE TRUNCATE` 触发器 | 任一操作抛出 `audit_events is append-only`，与 Spec 10.2“账本只追加”一致 |
| `pipeline_versions` | `BEFORE UPDATE` 触发器 | `is_immutable=true` 后禁止修改 `etl_plan_json`、`hocon_text`、`artifact_digest`，禁止解冻 |
| `pipeline_versions` | `BEFORE DELETE` 触发器 | 禁止删除，与 Spec 10.1“删除禁止”一致 |
| `approval_requests` | `BEFORE UPDATE` 触发器 | 已决策后禁止修改 `decision`、`approver_id`、`decided_at` |

未增加链序号字段。Spec P-09 尚未确认链序，迁移不以 `created_at` 代替唯一链序，也不自造序号列。

## 四、验证结果

### SQLite 迁移测试

命令：`python -m pytest tests/test_schema.py -ra`

结果：`3 passed`。

- 模型声明恰好 13 张业务表；
- 升级后 13 张业务表 + `alembic_version`；
- 5 个 SQLite 触发器存在；
- `audit_events` UPDATE/DELETE、`pipeline_versions` 冻结内容修改/解冻/删除、审批决策修改、负计数、非法摘要、重复审批均被拒绝；
- 降级后业务表与触发器清零。

### PostgreSQL 实测

环境：一次性 `postgres:16-alpine` 容器，仅用于本次验证；连接凭据未写入仓库。

命令：`DATABASE_URL=... python -m alembic upgrade head`

结果：

- 业务表 13 张；
- 触发器 6 个：`trg_audit_events_no_update`、`trg_audit_events_no_delete`、`trg_audit_events_no_truncate`、`trg_pipeline_versions_immutable`、`trg_pipeline_versions_no_delete`、`trg_approval_requests_decision`；
- `etl_plan_json` 类型为 `jsonb`；
- 审计 UPDATE/DELETE/TRUNCATE、版本内容修改、版本解冻、版本删除、审批决策修改、负计数、非法摘要、重复审批均被拒绝；
- `alembic downgrade base` 后业务表为 0、`etl_*` 函数为 0；再次 `upgrade head` 成功。

证据摘要：`证据/schema_checks.txt`。

## 五、边界

- 本次只完成 schema 与数据库保护，**API 运行时尚未接入数据库**；连接配置、Profile、Preparation 等未定义实体仍在内存。
- `audit_events` 的哈希链写入、Ledger 查询、链验证仍未实现，属于后续 Harness 内核（P-09、P-21）。
- PostgreSQL 版本、部署拓扑、备份与权限模型仍按 P-28 待确认；本次容器验证不代表生产部署完成。
