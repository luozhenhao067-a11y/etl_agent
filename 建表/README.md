# 建表交付包：Spec 10.1 十三张表 + 幂等演示数据（PostgreSQL）

本目录是 PostgreSQL 持久化迁移的建表与落库交付物，供评审；确认后按下文
「合入计划」并入 `backendpoint/`。表结构、外键、触发器与
`backendpoint/migrations/versions/0001_initial_13_tables.py` 完全一致
（模型单一事实来源：`backendpoint/app/models/tables.py`，本目录不复制模型，
脚本直接从 backendpoint 导入，保证零漂移）。

## 前置条件

- Python 3.11+，已安装 `sqlalchemy>=2`、`psycopg[binary]`（3.x）、`alembic`（requirements.txt 已含）
- PostgreSQL 13+（本项目：192.168.100.128:5432，库名 postgres）
- 数据库密码等凭据只通过环境变量传递，任何代码/脚本不硬编码

## 执行步骤

PowerShell：

```powershell
# 1. 连接串（驱动前缀必须是 postgresql+psycopg://，psycopg 3）
$env:DATABASE_URL = "postgresql+psycopg://postgres:123456@192.168.100.128:5432/postgres"

# 2. 建表（13 张表 + 防篡改触发器，Alembic 迁移）
cd ..\backendpoint
alembic upgrade head
cd ..\建表

# 3. 幂等灌入演示数据
python seed_data.py

# 4. 冒烟验证（列一致性 / 行数 / 哈希链 / 双层防篡改 / 明文扫描 / 时间戳）
python verify_smoke.py
```

bash：将 `$env:` 换成 `export`，其余相同。也可用
`python seed_data.py --database-url postgresql+psycopg://...` 临时覆盖。

## 幂等与防篡改的配合（为什么不是"先清空再插入"）

迁移 0001 为关键表创建了数据库触发器（Spec 10.2 的库内防线）：

| 表 | 触发器行为 | 对灌数脚本的影响 |
|---|---|---|
| `audit_events` | 禁止 UPDATE / DELETE / TRUNCATE | 只能追加；脚本按主键/事件哈希"存在即跳过"，新事件续接既有链尾 |
| `pipeline_versions` | 禁止 DELETE；冻结后内容字段禁改、禁解冻 | 冻结版本存在即跳过 |
| `approval_requests` | 已决策记录禁改 `decision/approver_id/decided_at` | 只插入，不更新 |

因此 `seed_data.py` 采用**按主键存在即跳过**的幂等策略，全程单事务，重复执行为零操作。
全量重置：`alembic downgrade base && alembic upgrade head` 后重跑脚本。

## 数据覆盖（正常 / 异常 / 边界）

总量 342 行，每张表 ≥ 20 行（`projects` 6 行因 Spec 场景天然有限，
成员/授权/管道等关联表均 ≥ 20）。结构快照见 `../项目信息/数据结构.json`
（由 `export_schema_json.py` 从模型内省 + 库内实况生成）。

| 表 | 行数 | 覆盖点 |
|---|---|---|
| users | 24 | 5 类演示角色（与前端 DEV_USERS 一致，逐字保留）+ 17 名业务/技术人员 + 边界：`disabled` 用户（svc_etl，不删除、不入项目） |
| projects | 6 | 财务数据集成、用户行为分析、物流数据平台、集团报表中心等多租户场景 + 隔离校验项目 |
| project_memberships / role_grants | 33 / 10 | 成员角色五类（maker/checker1/checker2/ops/auditor）；职责槽 data_checker、security_checker，含一人多项目、一项目多成员 |
| pipelines | 20 | active / draft，覆盖 5 个项目的真实业务管道（订单同步、账务对账、埋点清洗、运单入库、报表汇总等） |
| pipeline_versions | 27 | 冻结含制品、计划中（仅 plan）、空草稿三类；含同管道多版本演进（v1→v2） |
| pipeline_artifacts | 31 | 每个冻结版本 hocon + etl_plan 双制品，digest 均为对应版本内容真实 SHA256 |
| agent_runs | 25 | completed / running / interrupted（异常，对应前端 Studio 中断问答），prompt 贴合各管道业务 |
| approval_requests | 50 | PENDING / APPROVED / REJECTED；数据 + 安全双槽位；已决策含 decided_at（决策时间 = 创建 + 审批时滞），待决策为 NULL（边界） |
| execution_runs | 26 | running / succeeded / failed / cancelled / rolled_back + queued 全零计数（边界），计数含大字节数（BigInteger 验证） |
| file_assets | 24 | csv / excel / json + 0 字节文件（边界），文件名贴合项目业务 |
| runtime_supervision_snapshots | 25 | within_budget / budget_exceeded+paused / cancelled，指标随执行规模变化 |
| audit_events | 41 | Spec 12.2 事件目录 21 种事件类型：pipeline.created、version.frozen、preparation.created、approval.*、run.*、supervision.*、agent.run.*；时间严格递增；创世 prev=64 个 0，逐条真实 SHA256 链式签名 |

所有摘要字段（artifact_digest、capability_token_digest、payload_digest、
prev_event_hash、event_hash）都是 `hashlib.sha256(...).hexdigest()` 生成的
真实小写 64 位十六进制串；HOCON/示例值沿用 mock 的脱敏形态（`10.20.*.*`、
`etl_***`），不落任何明文 Secret。

## 与任务要求的偏差说明（需要评审确认）

1. **users 表没有新增 password 列。** Spec 10.1 的 users 字段不含密码，
   认证机制/密码策略整体标记为待确认（Spec P-26），前端为模拟登录
   （`stores/auth.js`），Pydantic Schema 亦无 password 字段。按"模型与前端
   /Schema 100% 一致"与"不新增未定义实体"两条硬约束，未加列；接入真实认证
   时再以一个 Alembic 迁移加 `password_hash`（passlib[bcrypt]）。
2. **状态枚举大小写遵循接口实况**：审批大写（PENDING/APPROVED/REJECTED）、
   执行小写（queued/.../rolled_back），与 mock、前端 `status.js` 完全一致。
   Spec 4.7 状态机的大写写法是文档记法；若后续统一，只需改数据不改结构。
3. 任务提示词中的 `app/db/models.py`：模型已在 `backendpoint/app/models/tables.py`
   且被 Alembic env.py 引用，重复放置会造成双份事实来源，故保持原位。

## 合入计划（已执行，2026-10-24）

| 本目录文件 | 目标位置 | 状态 |
|---|---|---|
| `db/session.py` | `backendpoint/app/db/session.py` | ✅ 已合入（新增 `validate_url()` 供测试复用；`create_db_engine()` 支持显式 url 参数） |
| `db/guards.py` | `backendpoint/app/db/guards.py` | ✅ 已合入（原样，双导入兼容层已去除） |
| `seed_data.py` / `verify_smoke.py` | 保留在 `建表/`（运维脚本） | ✅ 维持原位 |

后续步骤（对应迁移任务清单）均已完成：容器 `STORAGE=memory\|postgres` 开关 +
`app/adapters/sql/repository.py`（RepositoryPort SQL 实现，E 项）、
`tests/conftest.py` 真实库事务回滚 fixture（F 项，`TEST_STORAGE=postgres` +
`TEST_DATABASE_URL` 启用，134 个测试双后端全绿、真库零污染）。

本目录的 `db/` 副本保留自包含运行能力（`seed_data.py` / `verify_smoke.py`
独立运行时使用），正式实现以 `backendpoint/app/db/` 为准。

## 哈希链规范化说明

`event_hash = sha256(project_id|actor_id|event_type|resource_type|resource_id|payload_digest|prev_event_hash)`，
`payload_digest = sha256(canonical_json(payload))`（sort_keys、紧凑分隔符）。
链内顺序以插入序（id）为准；正式链序规则待确认（Spec P-09），届时仅需替换
`seed_data.py` 中的 `event_hash_for` 一处。
