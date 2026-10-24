# ETL-Agent 控制面后端（API 层交付）

本目录是依据 `项目信息/接口契约.md` v1.0 生成的 FastAPI 接口层，包含 Spec 10.1 / PRD 7.1 明确列出的 13 张表的 Alembic schema，并实现了可独立测试的 Harness 内核（PDP、Capability、Replay Guard、Tool Broker、Outbox、Evidence Ledger）。API 运行时仍使用进程内演示数据，尚未接入 Repository/数据库读写；Harness 内核也**尚未注入 API 容器**，API 的 Harness 调用仍走失败关闭的 Stub。

本交付**未接入** Celery、SeaTunnel、Vault、真实认证，以及 Spec 未定义的持久化表。API 的外部依赖均以 Port + Stub 的方式失败关闭（fail closed），不会伪造成功结果。Harness 内核为本地实现，不表示 Commit 事务、Outbox 持久化或生产密钥管理已完成。

## 1. 运行方式

要求 Python 3.11 或以上版本。

```bash
cd backendpoint

# 可选：创建虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload
```

启动后：

- Swagger UI：<http://localhost:8000/docs>
- OpenAPI JSON：<http://localhost:8000/openapi.json>
- 健康检查：`GET http://localhost:8000/health`（需要认证头）

运行测试：

```bash
python -m pytest -q
```

测试使用 `pytest-asyncio` 与 `httpx.AsyncClient`，默认使用内存仓储、不连接真实 PostgreSQL、Redis、SeaTunnel 或 Vault；`tests/test_schema.py` 使用临时 SQLite 校验迁移。

### 存储后端切换（memory | postgres）

`STORAGE` 环境变量选择仓储实现，默认 `memory`：

```bash
# 内存仓储（默认）：自包含演示数据，程序重启即清空
python -m uvicorn app.main:app --reload

# PostgreSQL 仓储：读写 DATABASE_URL 指向的库（需先 alembic upgrade head
# 并用 建表/seed_data.py 灌入演示数据）；连接配置/Preparation 等
# Spec 10.3 未定义实体仍保存在内存
export STORAGE=postgres
python -m uvicorn app.main:app --reload
```

两种后端共用同一个 `RepositoryPort` 接口，API 层、Pydantic Schema 与前端契约零变化；行以 dict + ISO 时间字符串跨越边界。`audit_events` 只追加与 `pipeline_versions` 冻结由应用层守卫（`app/db/guards.py`）+ 数据库触发器（迁移 0001）双重保护。

### 用真实 PostgreSQL 跑测试（可选）

```bash
export TEST_STORAGE=postgres
export TEST_DATABASE_URL="postgresql+psycopg://<user>:<password>@<host>:5432/<database>"
python -m pytest -q
```

每个测试在一个外层事务内运行：先建私有 schema `pytest_staging`（事务性 DDL）重建全部表并灌入内存种子，测试写操作经 savepoint（`join_transaction_mode="create_savepoint"`）落在该 schema，测试结束整体回滚——真实数据库（含演示数据）零污染。迁移 0001 的触发器属于 public schema，staging schema 中由应用层守卫承担同样的 Spec 10.2 规则。

### 数据库 schema

数据库 URL 只从环境变量读取，不写入 `alembic.ini`，也不提交凭据：

```bash
# PostgreSQL（生产目标）
export DATABASE_URL="postgresql+psycopg://<user>:<password>@<host>:5432/<database>"
python -m alembic upgrade head
```

本地无 PostgreSQL 时，可用临时 SQLite 验证同一份迁移：

```bash
export DATABASE_URL="sqlite:///./etl_agent_schema.db"
python -m alembic upgrade head
```

迁移只创建 Spec 10.1 / PRD 7.1 的 13 张业务表；Alembic 自身的 `alembic_version` 是工具元数据，不是业务表。连接配置、Profile、Preparation、Outbox、Capability 消费记录、Benchmark 结果等未定义实体不建表。

## 2. 目录结构

```text
backendpoint/
├─ app/
│  ├─ main.py                 # FastAPI 应用工厂、中间件、路由注册
│  ├─ config.py               # 环境变量配置
│  ├─ container.py            # 内存仓库、状态、Port 与 Stub 组装
│  ├─ api/                    # API-01 ~ API-18 路由
│  ├─ core/                   # 认证、错误、幂等、脱敏、审计
│  │  └─ harness/             # PDP、Capability、Replay、Broker、Outbox、Ledger
│  ├─ ports/                  # HarnessPort、SecretPort、ExecPort、RepositoryPort
│  ├─ adapters/stub/          # 失败关闭的 Harness / Secret / Exec Stub
│  ├─ adapters/memory/        # 内存仓库、内存状态、Harness 内核适配器
│  ├─ schemas/                # Pydantic 请求、响应、枚举
│  └─ models/tables.py        # Spec 10.1 的 13 张表模型与约束
├─ migrations/                # Alembic 迁移；0001 建 13 张表与数据库保护
├─ tests/                     # API 契约测试与 schema 迁移测试
├─ alembic.ini
├─ requirements.txt
├─ pytest.ini
└─ README.md
```

## 3. 认证与角色切换

认证机制在契约中仍是待确认项 P-26。本交付不签发 JWT，不校验密码，不调用外部身份提供方。请求头格式固定为：

```http
Authorization: Bearer <user_demo_xxx>
```

切换演示用户即切换角色。演示用户如下：

| 用户 ID | 用户名 | 显示名 | 项目角色 | 角色槽 | 说明 |
|---|---|---|---|---|---|
| `user_demo_001` | `maker01` | 张三 | maker | — | 申请人与数据工程师 |
| `user_demo_002` | `checker1_01` | 李四 | checker1 | `data_checker` | 数据审批人 |
| `user_demo_003` | `checker2_01` | 王五 | checker2 | `security_checker` | 安全审批人 |
| `user_demo_004` | `ops01` | 赵六 | ops | — | 系统操作员 |
| `user_demo_005` | `auditor01` | 钱七 | auditor | — | 审计人员，只读 |
| `user_demo_006` | `maker02` | 孙八 | maker | — | 第二个数据工程师 |
| `user_demo_007` | `outsider01` | 周九 | 无 | — | 非项目成员，用于验证 AUTH-403 |

默认项目为 `prj_demo_001`。演示用户均隶属于该项目，`user_demo_007` 不属于任何项目。另有一个项目 `prj_demo_999`，用于验证跨项目访问返回 `403 AUTH-403`。

前端开发模式默认使用 mock 适配器。连接真实后端时，设置 `VITE_USE_MOCK=false`，前端通过 Vite 代理把 `/api` 与 `/health` 转发到 `http://localhost:8000`。前端 `stores/auth.js` 会把演示用户 ID 组装为 `Bearer <user_demo_xxx>`；真实令牌格式待 P-26 确认后再替换。

## 4. Port 与 Stub

| Port | 方法 | Stub 行为 |
|---|---|---|
| `HarnessPort` | `pdp_decide`、`issue_capability`、`verify_capability`、`replay_guard_check`、`write_outbox`、`append_ledger` | API 容器注入的 Stub 全部抛出 `NotImplementedError("HARNESS_NOT_READY")`；`InMemoryHarnessAdapter` 可运行内核，但尚未接入 API |
| `SecretPort` | `materialize`、`get_ref` | 全部抛出 `NotImplementedError("SECRET_PROVIDER_NOT_READY")` |
| `ExecPort` | `submit_job`、`cancel_job`、`query_status` | 全部抛出 `NotImplementedError("EXEC_ENGINE_NOT_READY")` |
| `RepositoryPort` | 按 Spec 10.1 的 13 张表分组 | 仅提供 `InMemoryRepository` 实现，不连接数据库 |

路由捕获 Stub 的 `NotImplementedError`，返回契约错误码，并在 `details` 中给出：

```json
{"dependency": "harness", "status": "not_implemented"}
```

任何 Stub 都不会返回成功、伪造的 `execution_run_id`、`capability_digest`、Benchmark 结果或质量指标。

### Harness 内核（本地可执行，未接入 API）

`app/core/harness/` 按 Spec 3.4–3.9 / 5.1–5.4 实现以下组件：

| 组件 | 文件 | 已实现的行为 |
|---|---|---|
| PDP | `pdp.py` | ToolIntent 校验、P0–P3 输出、审批槽、预算校验、决策摘要、绑定 Preparation；策略异常 fail closed |
| Capability | `capability.py` | Ed25519 紧凑令牌、TTL 300 秒、jti/token_digest、2/2 审批与职责分离校验、签名/Scope/绑定/过期/单次消费 |
| Replay Guard | `replay.py` | 原子内存占位、键作用域绑定、TTL、重复/过期/缺失/存储不可用错误 |
| Tool Broker | `broker.py` | 工具注册、PDP 决策摘要复核、Capability 校验、Replay 占位、处理器执行、输出摘要与 TB 错误码；敏感 `external_ref` 丢弃 |
| Outbox | `outbox.py` | PENDING/PUBLISHED/RETRYING/CONSUMED/DEAD_LETTER、租约、重复事件与幂等键拒绝 |
| Evidence Ledger | `ledger.py` | 按项目哈希链、`prev_event_hash`/`event_hash`、链验证、Ed25519 检查点 |

边界：

- P-06 未决：Outbox 无持久化表，`InMemoryOutbox` 不能提供 Commit 的数据库原子性；因此内核不接入 API 的 Commit 路由。
- P-07 未决：Capability 消费记录只有内存 `jti`/`token_digest`，不是 Redis/PostgreSQL 双重占位。
- P-09 未决：Ledger 顺序只存在于内存链表，没有写入 `audit_events` 的链序字段；检查点中的 `last_sequence` 不能作为生产持久化方案。
- P-31/P-32 未决：令牌编码、密钥生命周期、检查点频率仍待确认；当前私钥由进程临时生成，不落库、不写日志。
- P-13 未决：PDP 的 P0–P3 与审批槽映射是显式临时策略；执行类工具始终保留四眼最低要求，策略不得降低。
- `InMemoryHarnessAdapter` 仅用于内核测试和后续接入，不改变 API 当前的 503 口径。
- 内核专项记录见 [`../联调报告/08-Harness内核记录.md`](../联调报告/08-Harness内核记录.md)。

## 5. 接口实现分层

| 接口 | 方法与路径 | 实现层级 | 说明 |
|---|---|---|---|
| API-01 | `GET /health` | 只读，完整实现 | 返回 `status=degraded`；数据库、Harness、SecretProvider、执行引擎均如实标记未配置/未实现 |
| API-02 | `GET /api/v1/projects/{project_id}/connections` | 只读，完整实现 | 类型/环境/状态过滤、分页、主机脱敏、项目隔离 |
| API-03 | `POST /api/v1/connections` | 无副作用写，完整实现 | 字段校验、名称冲突、幂等、审计、Secret 只保存摘要 |
| API-04 | `PUT /api/v1/connections/{id}` | 无副作用写，完整实现 | 部分更新、合并后重新校验、幂等、审计 |
| API-05 | `POST /api/v1/connections/{id}/tests` | Harness 副作用，返回 503 | 校验超时与权限后调用 `pdp_decide`，依赖未就绪返回 `CONN-503` |
| API-06 | `POST /api/v1/connections/{id}/profiles` | Harness 副作用，返回 503 | 校验只读与采样范围后调用 `pdp_decide`，返回 `META-503` |
| API-07 | `POST /api/v1/file-assets` | Harness 副作用，返回 503 | multipart 校验、格式/扩展名/大小/路径检查、幂等后调用 `pdp_decide`，返回 `FILE-503`；不落盘、不解析 |
| API-08 | `POST /api/v1/pipelines` | 无副作用写，完整实现 | 项目边界、Maker 权限、编码冲突、幂等、审计 |
| API-09 | `POST /api/v1/versions/{version_id}/generation` | 无副作用写，完整实现 | 版本冻结校验、并发线程校验、创建内存 AgentRun 与澄清中断 |
| API-10 | `POST /api/v1/agent-runs/{run_id}/answers` | 无副作用写，完整实现 | 仅运行发起人；线程、回答键与类型校验；重复回答返回 `GEN-409` |
| API-11 | `GET /api/v1/versions/{version_id}/design` | 只读，完整实现 | 返回内存设计；未就绪返回 `API-409`；HOCON 已脱敏 |
| API-12 | `POST /api/v1/versions/{version_id}/prepare` | Harness 副作用，返回 503 | 版本冻结、设计门禁、幂等后调用 `pdp_decide`，返回 `API-503` |
| API-13 | `POST /api/v1/approval-requests/{approval_id}/decisions` | 无副作用写，完整实现 | 自批拦截、角色槽、不同审批人、决策不可变、幂等、审计 |
| API-14 | `POST /api/v1/preparations/{preparation_id}/commit` | Harness 副作用，返回 503 | Ops 权限、审批完成与职责分离校验后调用 `issue_capability`，返回 `CMT-503`；不创建 Run |
| API-15 | `GET /api/v1/execution-runs/{id}` | 只读，完整实现 | 内存运行详情、指标、质量报告、监督快照、日志脱敏 |
| API-16 | `POST /api/v1/execution-runs/{id}/cancel` | Harness 副作用，返回 503 | 终态校验、幂等后调用 `replay_guard_check`，返回 `OPS-503`；不修改运行状态 |
| API-17 | `POST /api/v1/execution-runs/{id}/rollback` | Harness 副作用，返回 503 | 仅失败/取消运行可回滚、确认串校验、幂等后调用 `replay_guard_check`，返回 `OPS-503` |
| API-18 | `POST /api/v1/benchmarks/run` | Harness 副作用，返回 503 | Checker2 权限、同套件运行冲突、幂等后调用 `replay_guard_check`，返回 `BENCH-503`；不生成 Benchmark ID |

所有接口均使用契约 v1.0 的统一成功信封：

```json
{"data": {}, "correlation_id": "corr_xxx"}
```

错误信封：

```json
{
  "error_code": "CONN-422",
  "message": "invalid connection parameter",
  "correlation_id": "corr_xxx",
  "details": {}
}
```

## 6. 返回 503 的接口

以下接口在依赖未实现时**必须**返回 503，不得返回演示成功数据：

| 接口 | HTTP 状态 | 错误码 | `details.dependency` | 失败原因 |
|---|---|---|---|---|
| API-05 `POST /api/v1/connections/{id}/tests` | 503 | `CONN-503` | `harness` | `conn.test` 属于 Harness Tool Broker，Stub 未实现 |
| API-06 `POST /api/v1/connections/{id}/profiles` | 503 | `META-503` | `harness` | `metadata.profile` 需要 PDP 与 Tool Broker，Stub 未实现 |
| API-07 `POST /api/v1/file-assets` | 503 | `FILE-503` | `harness` | `file.parse` 需要 Harness，Stub 未实现 |
| API-12 `POST /api/v1/versions/{version_id}/prepare` | 503 | `API-503` | `harness` | 准备单编排与 `pdp_decide` 未实现 |
| API-14 `POST /api/v1/preparations/{preparation_id}/commit` | 503 | `CMT-503` | `harness` | `issue_capability` 与 Outbox 投递未实现 |
| API-16 `POST /api/v1/execution-runs/{id}/cancel` | 503 | `OPS-503` | `harness` | Replay Guard 与 `run.cancel` 工具未实现 |
| API-17 `POST /api/v1/execution-runs/{id}/rollback` | 503 | `OPS-503` | `harness` | Replay Guard 与 `shadow.rollback` 工具未实现 |
| API-18 `POST /api/v1/benchmarks/run` | 503 | `BENCH-503` | `harness` | `benchmark.run` 工具与评测数据未实现 |

503 响应不会包含 `execution_run_id`、`capability_digest`、`benchmark_run_id`、延迟、质量指标或任何成功标志。

## 7. 契约中缺失、本交付未创建的接口

以下接口在 PRD/Spec 中没有路径定义。为避免自造契约，本交付**没有创建任何路由**。前端在 `frontend/src/api/missing.js` 中使用 mock 适配器，README 也保持同步标注。

| 待确认项 | 缺失的接口能力 | 影响 |
|---|---|---|
| P-18 | PipelineVersion 创建、列表、历史、冻结、门禁结果查询 | Studio 冻结与提交无法完整实现 |
| P-19 | 总览聚合、连接详情、Profile 读取、文件列表/状态、Preparation 列表/详情、审批列表/详情、ExecutionRun 列表 | 多个页面缺少读取来源；后端不做聚合拼装 |
| P-20 | 安全重跑、资源清理、回滚预览、诊断导出、操作审计查询 | 运维页部分动作无法实现 |
| P-21 | 审计事件、Evidence Ledger 查询、链验证 | 审计与证据页面无法实现 |
| P-22 | 项目成员与角色分配 | 角色配置无法实现；不新增角色 |
| P-23 | 实时日志流 | 执行监控无法实时推送 |
| P-24 | Benchmark 历史、结果详情、导出、候选审查、灰度开关、紧急停用；数据集字段与评分公式 | 治理页面无法完整实现 |

Provider 的默认值、切换与降级策略（P-17）同样未在契约中定义，本交付只在 API-09 中接受可选 `provider` 枚举，不实现切换接口。

## 8. 数据库 schema 与未定义表

迁移 `migrations/versions/0001_initial_13_tables.py` 只创建 Spec 10.1 / PRD 7.1 列出的 13 张表：

`users`、`projects`、`project_memberships`、`project_role_grants`、`pipelines`、`pipeline_versions`、`pipeline_artifacts`、`agent_runs`、`approval_requests`、`execution_runs`、`file_assets`、`runtime_supervision_snapshots`、`audit_events`。

已落地的数据库约束：

- 主键、外键、唯一约束：成员/职责槽、Pipeline 编码、版本号、审批 Preparation + 角色、Capability 摘要、审批唯一、审计事件哈希等；
- 非负检查：`agent_runs.step_count`、执行行数/字节数、`file_assets.file_size`；
- 摘要检查：`artifact_digest`、`capability_token_digest`、`payload_digest`、`prev_event_hash`、`event_hash` 为 64 位小写十六进制；
- `audit_events` 禁止 `UPDATE`、`DELETE`、`TRUNCATE`；
- `pipeline_versions.is_immutable=true` 后禁止修改 `etl_plan_json`、`hocon_text`、`artifact_digest`，禁止解冻，禁止删除；
- `approval_requests` 已决策后禁止修改 `decision`、`approver_id`、`decided_at`。

PostgreSQL 是生产目标；SQLite 触发器变体用于无数据库服务器的迁移测试。数据库层面没有链序号字段（P-09 未决），不以 `created_at` 充当唯一链序。

契约第 10.3 节列出的持久化阻塞项均**没有建表**，相关数据仍只存在于进程内存：

- 连接配置、元数据 Profile、采样结果；
- Preparation；
- Outbox 事件；
- Capability 消费记录 / JTI；
- Benchmark 结果、数据集版本、候选、灰度状态；
- Ledger 链序。

API 运行时尚未切换到数据库 Repository，进程重启后这些内存数据仍会丢失。这是当前交付边界，不是持久化实现。

## 9. 幂等、分页、脱敏与审计

### 幂等

- 所有写接口要求 `Idempotency-Key` 请求头，API-05 按契约豁免，API-10 使用可选幂等键。
- 同键同载荷返回首次成功结果；同键不同载荷返回对应冲突错误码（如 `CONN-409`、`API-409`、`GEN-409`、`APR-409`、`OPS-409`）。
- API-13、API-14、API-16、API-17、API-18 的请求体也包含 `idempotency_key`，必须与请求头一致；不一致返回 400 或 422（按各接口契约）。
- 依赖未就绪的 5xx 不缓存为成功，重试仍会返回 503。

### 分页

API-02 使用 `page`、`page_size`，默认 `page=1`、`page_size=20`，上限默认 100。返回：

```json
{"items": [], "total": 0, "page": 1, "page_size": 20}
```

`page_size` 超过上限返回 `400 API-400`。默认值与上限在契约中仍待确认（P-19 / Spec 9.1）。

### 脱敏

- 手机号、邮箱、主机、JDBC URL 在返回前脱敏。
- 连接只保存 `secret_ref_digest`，不保存 `secret_ref` 原文。
- 不返回 Secret、Capability 明文、`token_digest`、`capability_token_digest`。
- 执行日志逐行清洗 `password`、`token`、手机号、邮箱、IP。

### 审计

- `connection.created`、`connection.updated`、`agent.run.started`、`agent.run.interrupted`、`agent.run.resumed`、`approval.decision.recorded`、`approval.self_approval_blocked` 写入进程内的审计暂存链，只保存载荷摘要。每条日志都标记 `ledger_status=pending_ledger`，表示该记录尚未进入真正的 Evidence Ledger。
- `run.queued`、`file.asset.parse_failed`、`agent.run.failed` 等仍在 Spec 12.2 目录之外的事件只写结构化日志，**不进入暂存链**，状态为“待接入 Ledger”。
- Harness 内核 `EvidenceLedger` 已实现内存哈希链与检查点，但它没有接入 API 审计服务；API 的 `HarnessPort.append_ledger` 仍由 Stub 失败关闭。Ledger 查询/链验证接口（P-21）和持久化链序（P-09/P-32）未实现。

## 10. 待确认项

以下事项在契约/PRD/Spec 中未闭合。本交付不擅自固化，README 与代码保持可配置或显式标注。

| 编号 | 待确认内容 | 本交付处理 |
|---|---|---|
| P-16 | 执行状态采用轮询还是订阅，周期与通道 | 未实现状态推送；只提供 API-15 单次读取 |
| P-17 | 多模型 Provider 默认选择、切换、降级策略 | 仅接受可选 `provider` 枚举，不实现切换 |
| P-18 | PipelineVersion 创建、列表、历史、冻结、门禁查询 | 不创建路由；前端使用 mock |
| P-19 | 总览聚合、连接详情、Profile/文件/Preparation/审批/执行列表 | 不创建路由；不做后端聚合 |
| P-20 | 安全重跑、清理、回滚预览、诊断导出、操作审计查询 | 不创建路由 |
| P-21 | 审计事件、Ledger 查询与链验证 | 不创建路由；审计仅内存 |
| P-22 | 项目成员与角色分配 | 不创建路由；不新增角色 |
| P-23 | 实时日志流 | 不创建路由；仅 API-15 返回脱敏后的近期日志 |
| P-24 | Benchmark 历史、结果、导出、候选、灰度、停用；数据集与评分公式 | 不创建路由；API-18 只返回 503 |
| P-25 | SecretProvider / Vault KV v2 部署、轮换周期、租约 | SecretPort + Stub，不连接 Vault |
| P-26 | 用户认证机制、会话/令牌、登出、密码策略 | 仅 Bearer 演示用户，不签发 JWT |
| P-27 | `GET /health` 是否公开、是否暴露组件细节 | 当前要求认证；组件状态如实返回 |
| P-28 | PostgreSQL/Redis 版本与部署拓扑；Celery 并发与队列 | 不连接数据库/Redis，不启动 Celery |
| P-31 | Capability 编码格式与 Ed25519 密钥生命周期 | 内核使用 EdDSA 紧凑令牌和临时进程密钥；API 仍走 Stub，生产格式与密钥生命周期不固化 |
| P-32 | Ledger 链范围与检查点频率 | 内核按项目维护内存哈希链，按需生成 Ed25519 检查点；不持久化、不设定生产频率 |
| P-33 | 只读/运维工具是否也需 Capability | 未扩展令牌类型；内核按 PDP + 权限 + Replay 处理只读/运维工具 |
| P-34 | 前端 UI 组件库、状态管理、HTTP 客户端、图表库 | 不影响接口契约 |

此外，P-11（审批串并行与意见必填）、P-12（审批有效期）、P-13（P0-P3 语义）、P-14（质量阈值）、P-15（文件大小上限）、P-29（Swap 后回滚边界）、P-30（数据保留）、P-35（状态枚举）、P-36（审计脱敏级别）也未闭合。实现采用保守默认值并保留配置项，不把演示值固化为业务规则。

## 11. 测试

测试文件与覆盖范围：

| 文件 | 覆盖内容 |
|---|---|
| `tests/test_contract.py` | OpenAPI 路径、统一信封、相关性 ID、错误处理、掩码工具、幂等键缺失与冲突 |
| `tests/test_connections.py` | API-02 ~ API-06 的成功、参数错误、权限、404、503、脱敏与审计 |
| `tests/test_files.py` | API-07 的格式、扩展名、空文件、大小上限、对象存储路径、幂等 |
| `tests/test_studio.py` | API-08 ~ API-11 的创建、幂等、状态机、角色、设计读取 |
| `tests/test_preparations.py` | API-12 ~ API-14 的准备、审批、自批、角色槽冲突、提交 503 |
| `tests/test_operations.py` | API-15 ~ API-18 的运行读取、取消、回滚、Benchmark 503 |
| `tests/test_schema.py` | 13 张表集合、迁移升级/降级、约束与不可变触发器 |
| `tests/test_harness.py` | PDP、Capability、Replay Guard、Outbox、Ledger、Tool Broker 与内核端到端链路 |

当前测试全部通过（134 项）。API 测试不依赖真实数据库、Redis、SeaTunnel 或 Vault；schema 测试使用临时 SQLite；Harness 内核测试使用内存适配器和固定时钟。
