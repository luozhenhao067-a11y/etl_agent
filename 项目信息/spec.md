# 生产级 ETL-Agent 数据集成平台 技术规格（Spec）

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 生成日期 | 2026-10-23 |
| 需求源 | `D:\资料\三项\ETL-Agent 数据集成平台\项目信息\需求文档prd.txt` |
| 页面结构依据 | `D:\资料\三项\ETL-Agent 数据集成平台\项目信息\wireframe.pen` |
| 冲突裁决 | PRD 优先；PRD 未定义项标“待确认”；不设需求优先级 |
| 技术栈 | Vue；Python + FastAPI + Uvicorn；Celery；Redis；PostgreSQL；SeaTunnel Zeta；LangGraph；SecretProvider / Vault KV v2 |

## 1. 文档依据与范围

### 1.1 依据与读取结论

| 依据 | 读取结论 | 在 Spec 中的用途 |
|---|---|---|
| PRD 全文 12 节 | 已读取；唯一需求源；含 23 条 FR、18 个接口、13 张表、9 条验收标准 | 业务范围、角色、流程、接口、数据、验收的唯一裁决依据 |
| wireframe.pen | 已通过 pen.dev 读取；顶层 15 个画板，其中 2 个组件画板（Sidebar、TopBar），13 个页面画板（00 封面、01-10 业务页、11 关键流程、12 验收对照） | 页面结构、布局区、组件、页面状态、角色视图差异 |
| 原型页面地图 | 列出 01-13 共 13 项；其中“11 安全进化管理”无对应画板 | 标为“原型缺失”，见第 15 章 P-01 |
| 原型验收画板 | 12 屏验收条目文本与 PRD 第 10 节不完全一致 | 以 PRD 第 10 节为准；原型验收画板不纳入验收基线 |

### 1.2 冲突与缺失处理规则

| 规则 | 约束 |
|---|---|
| 需求冲突 | PRD 与 wireframe 冲突时以 PRD 为准 |
| 原型缺失 | 标“待确认”；不得以页面地图文字替代页面规格 |
| 原型演示值 | 200MB 文件上限、2M 行预算、5% 错误率、10min 超时、99.0 质量分等均为演示数据，不构成需求 |
| 未定义角色 | 不新增；仅使用 PRD 3.1 的 5 类角色 |
| 未定义页面 | 不新增；原型说明画板不包装为产品页面 |
| 未定义接口 | 不新增；页面所需但 PRD 第 8 节未列出的接口统一列入“待确认” |
| 未定义数据表 | 不新增；PRD 7.1 未列出的持久化实体列入“待确认” |
| 需求优先级 | 不设置；全文不出现 P0/P1 排期语义，P0-P3 仅指 PDP 风险等级 |

### 1.3 范围

| 范围内 | 规格落点 |
|---|---|
| 认证鉴权、多租户项目、成员与角色、Secret 受管存储 | 第 2、8、12 章 |
| 异构数据库与文件/API 接入、只读元数据探查、脱敏样本 | 第 6、8、9、12 章 |
| 自然语言解析、LangGraph 中断恢复、多模型 Provider、EtlPlan/HOCON 生成、门禁、有限修复 | 第 6、7、8、9、11 章 |
| Harness：PDP、Capability、Tool Broker、Replay Guard、Outbox、Evidence Ledger | 第 3、4、5 章（主轴） |
| Celery 执行、SeaTunnel 数据面、影子表、原子 Swap、质量契约、运行监督、取消与回滚 | 第 4、8、11、13 章 |
| Benchmark L0/L1/L2、安全进化候选与灰度 | 第 6、11、14 章 |
| 审计、脱敏、证据链、防篡改 | 第 5、12、14 章 |

| 范围外 | 说明 |
|---|---|
| 控制面直连搬运海量业务数据 | 数据搬运只能由 SeaTunnel 在数据面执行 |
| PRD 未定义的角色、页面、接口、数据表、业务能力 | 一律不新增 |
| PRD 未定义的需求优先级与排期 | 不设置 |
| PRD 未定义的 Benchmark 评分公式、数据集字段结构 | 标“待确认”，不擅自定稿 |

### 1.4 FR 覆盖索引

| FR | 规格章节 | 主要页面 | 关键接口 |
|---|---|---|---|
| FR-DASH-01 | 6.2、9 | `/dashboard` | API-02、API-15（聚合接口待确认） |
| FR-CONN-01 | 6.3、7.1、8.3、9 | `/connections` | API-02、API-03、API-04、API-05 |
| FR-CONN-02 | 6.3、11 | `/connections` | API-02、API-03 |
| FR-META-01 | 6.4、7.1、8.3、9 | `/connections/profiles` | API-06 |
| FR-META-02 | 6.4、12.3、14 | `/connections/profiles` | API-06 |
| FR-FILE-01 | 6.5、7.1、8.4、9 | `/assets/files` | API-07 |
| FR-FILE-02 | 6.5、11 | `/assets/files` | API-07 |
| FR-STUDIO-01 | 6.6、7.2、8.5、9 | `/studio/:versionId` | API-08、API-09 |
| FR-STUDIO-02 | 6.6、7.2、9 | `/studio/:versionId` | API-09、API-10、API-11 |
| FR-STUDIO-03 | 6.6、7.3、9 | `/studio/:versionId` | API-11 |
| FR-STUDIO-04 | 6.6、7.3、9 | `/studio/:versionId`、`/runs/preparations` | API-12 |
| FR-STUDIO-05 | 6.6、7.2、9 | `/studio/:versionId` | API-09 |
| FR-STUDIO-06 | 6.6、7.2、9、11 | `/studio/:versionId` | API-09、API-10 |
| FR-STUDIO-07 | 6.6、7.2、8.6、9 | `/studio/:versionId` | API-09、API-11 |
| FR-RUN-01 | 3、4、6.7、7.4、9 | `/runs/preparations` | API-12、API-13、API-14 |
| FR-RUN-02 | 4、5、6.8、7.5、9、11 | `/runs/executions` | API-14、API-15 |
| FR-RUN-03 | 6.9、11、12 | `/runs/quality` | API-15 |
| FR-RUN-04 | 6.10、7.5、9、13 | `/runs/operations` | API-16、API-17 |
| FR-RUN-05 | 6.9、11、13、14 | `/runs/quality`、`/runs/operations` | API-15、API-17 |
| FR-GOV-01 | 6.11、11.8、9 | `/governance/benchmark` | API-18 |
| FR-GOV-02 | 6.11、6.12、11.8 | `/governance/benchmark`、`/governance/evolution`（缺失） | 待确认 |
| FR-GOV-03 | 6.11、11.8 | `/governance/benchmark` | API-18 |
| FR-GOV-04 | 6.11、11.8、5.4、14 | `/governance/benchmark` | 待确认 |

## 2. 术语、角色与权限矩阵

### 2.1 术语

| 术语 | 定义 |
|---|---|
| Pipeline | 项目内的数据集成定义，含源端、目标端、调度与版本 |
| PipelineVersion | 某一时刻的不可变方案版本；冻结后 `is_immutable=true` |
| Artifact Digest | 版本制品内容的 SHA256 摘要，用于指纹与审批绑定 |
| EtlPlan | 结构化 ETL 设计，含字段映射、转换、质量规则、调度 |
| HOCON | SeaTunnel 配置文本；由生成器产出，经语法与 Schema 门禁 |
| 确定性门禁 | 对语法、Schema、脱敏规则、运行预算的硬校验；失败禁止冻结与提交 |
| Preparation | 准备单；冻结输入指纹、资源范围、影响范围、数据分级、预算、回滚方案；不产生外部副作用 |
| 输入指纹 | Preparation 绑定的不可变事实摘要集合，至少含制品 SHA256、源/目标 Profile 引用、环境、预算、质量契约、监督契约 |
| 职责槽 | `role_slot`；数据审批人与安全审批人的独立审批职责位置 |
| ToolIntent | 一次工具调用的意图描述：工具、主体、环境、资源范围、参数摘要 |
| PDP | 策略决策点；输出 P0-P3 风险等级与审批要求 |
| Capability | Ed25519 签名、短时、单次、绑定工具/主体/环境/制品指纹的执行令牌 |
| JTI | Capability 唯一标识；用于单次消费与重放检测 |
| Tool Broker | 所有副作用执行的唯一出口；校验授权、Capability、Replay Guard 后执行工具 |
| Replay Guard | 防重放组件；保证 Capability 与运维幂等键只能消费一次 |
| Transactional Outbox | 业务事实与 Worker 投递命令在同一 PostgreSQL 事务原子落库的可靠投递机制 |
| Evidence Ledger | 只追加审计证据账本；`prev_event_hash` 与 `event_hash` 形成哈希链 |
| ExecutionRun | 一次实际执行实例；记录 SeaTunnel Job ID、指标、质量报告与状态 |
| Shadow Table | 影子表；有效数据先写入，质量通过后原子 Swap |
| Error Table | 错误表；按质量契约分流错误行并打错误码 |
| Atomic Swap | Doris `REPLACE TABLE ... swap=true` 等原子替换；正式表切换 |
| QualityContract | 质量契约；字段级规则、错误码、错误数据流向 |
| RuntimeSupervisionContract | 运行监督契约；行数、字节、时长、放大比、拒绝率阈值与动作 |
| Safe Rerun | 安全重跑；复用同一冻结版本 SHA，重新创建准备单并重新审批，不是失败运行重入 |
| Maker / Checker | 申请人 / 审批人；四眼职责分离 |

### 2.2 角色

| 角色 | 职责 | 可占职责槽 | 关键限制 |
|---|---|---|---|
| 数据工程师（申请人 / Maker） | 连接与探查、需求输入、生成与修复、冻结、提交审批 | 否 | 禁止自批；禁止 Commit |
| 数据审批人（Checker 1） | 数据维度审批：需求、Schema 映射、脱敏前后、质量规则、DAG | `data_checker` | 不占安全审批槽；禁止 Commit |
| 安全审批人（Checker 2） | 安全维度审批：资源范围、敏感分级、预算、Secret 引用、回滚方案；管理 Benchmark 与安全进化 | `security_checker` | 不占数据审批槽；禁止 Commit |
| 系统操作员（Ops） | 审批完成后 Commit、触发受管执行、监控、取消/重跑/回滚/清理、凭据轮转 | 否 | 禁止审批；禁止修改冻结版本 |
| 审计人员（Auditor） | 查看执行历史、审计事件、签名证据账本、质量报告、Benchmark 大盘 | 否 | 全链路只读；禁止执行、审批、修改 |

### 2.3 权限矩阵

图例：允许 = 可执行；只读 = 可查看不可变更；禁止 = 服务端拒绝；待确认 = PRD 未定义。

| 操作 | Maker | Checker 1 | Checker 2 | Ops | Auditor |
|---|---|---|---|---|---|
| 登录并查看所属项目 | 允许 | 允许 | 允许 | 允许 | 允许 |
| 查看总览工作台 | 允许 | 允许 | 允许 | 允许 | 允许 |
| 新建/编辑连接、测试连接 | 允许 | 只读 | 只读 | 只读 | 只读 |
| 发起只读元数据探查 | 允许 | 只读 | 只读 | 只读 | 只读 |
| 上传/解析文件资产 | 允许 | 只读 | 只读 | 只读 | 只读 |
| Studio 生成、澄清回答、有限修复 | 允许 | 只读 | 只读 | 只读 | 只读 |
| 冻结不可变版本 | 允许 | 禁止 | 禁止 | 禁止 | 禁止 |
| 提交审批申请 | 允许 | 禁止 | 禁止 | 禁止 | 禁止 |
| 数据审批决策 | 禁止（自批） | 允许 | 禁止 | 禁止 | 禁止 |
| 安全审批决策 | 禁止 | 禁止 | 允许 | 禁止 | 禁止 |
| Commit | 禁止 | 禁止 | 禁止 | 允许 | 禁止 |
| 取消、安全重跑、回滚、清理 | 禁止 | 禁止 | 禁止 | 允许 | 禁止 |
| 触发 Benchmark 评测 | 只读 | 只读 | 允许 | 只读 | 只读 |
| 安全进化候选审查 / 灰度开关 | 只读 | 只读 | 允许 | 只读 | 只读 |
| 查看审计与证据账本 | 待确认 | 待确认 | 待确认 | 待确认 | 允许 |
| 项目成员与角色分配 | 待确认 | 待确认 | 待确认 | 待确认 | 待确认 |

### 2.4 强制职责分离

| 规则 | 服务端强制点 | 失败码 | 审计事件 |
|---|---|---|---|
| 申请人禁止自批 | 审批决策接口比对 `actor_id` 与申请人；申请人身份获取方式待确认 | `APR-403 SELF_APPROVAL_FORBIDDEN` | `approval.self_approval_blocked` |
| 高风险操作同一人不得占多个审批职责槽 | Preparation 分配槽位与审批决策时校验两个审批人不同且均非申请人 | `APR-409 ROLE_SLOT_CONFLICT` | `approval.slot_conflict_blocked` |
| 数据审批人与安全审批人独立配置 | 项目内 `project_role_grants` 校验 | `APR-403 ROLE_GRANT_MISSING` | `approval.role_denied` |
| 审批不可撤销或覆盖 | 审批记录只追加；已决策记录禁止更新 | `APR-409 DECISION_IMMUTABLE` | `approval.decision.recorded` |
| 不得绕过审批直接执行 | Commit 校验 2/2 审批通过；Tool Broker 拒绝无 Preparation 的执行调用 | `CMT-409 APPROVAL_INCOMPLETE`、`TB-403 CAPABILITY_REQUIRED` | `tool.call.rejected` |

## 3. Harness 安全执行内核规格

### 3.1 内核定位与边界

| 约束 | 规格 |
|---|---|
| 定位 | Harness 是控制面不可绕过的执行内核；不是普通业务 service |
| 唯一入口 | FastAPI 路由不得直接执行副作用；只能调用 Harness 执行入口 |
| 唯一副作用出口 | 所有外部副作用必须经 Tool Broker |
| 控制面职责 | 编排、校验、审批、签发、记录；不搬运海量业务数据 |
| 数据面职责 | SeaTunnel 执行数据搬运；Worker 只执行受管命令 |
| 业务服务关系 | 业务服务可写控制面业务表；不得绕过 Harness 调用 SeaTunnel、SecretProvider、影子表、正式表 |
| 禁止项 | 控制面直连搬运；跳过审批执行；自批；明文 Secret；明文密码；明文敏感样本；Capability 明文回传或落库 |

### 3.2 副作用分类

| 类别 | 示例 | 执行路径 | Capability |
|---|---|---|---|
| 外部数据面执行 | SeaTunnel 作业提交、Kill、原子 Swap | Tool Broker → `etl.execute` / `run.cancel` / `table.swap` | 必须 |
| 外部只读受管工具 | 连接测试、元数据探查、文件解析 | Tool Broker → `conn.test` / `metadata.profile` / `file.parse` | 不签发执行 Capability；校验主体权限与只读约束 |
| 运维副作用 | 回滚影子表、清理资源 | Tool Broker → `shadow.rollback` / `resource.cleanup` | 不签发执行 Capability；PDP 决策 + 权限 + Replay Guard |
| Secret 访问 | Worker 物化 Secret | Tool Broker → `secret.materialize`，仅限受管执行上下文 | 必须绑定执行 Capability |
| 控制面 DB 写入 | 创建准备单、审批记录、状态更新 | 业务服务 PostgreSQL 事务 | 不适用；必须写审计事件 |
| 前端操作 | 表单、筛选、查看 | 仅调用 HTTP API | 不适用 |

说明：只读受管工具与运维工具的 Capability 适用范围 PRD 未明确，列为待确认 P-33；本 Spec 不扩展 PRD 未定义的令牌类型。

### 3.3 Harness 请求与结果协议

| 字段 | 类型 | 说明 |
|---|---|---|
| `request_id` | string | 单次 Harness 请求唯一标识 |
| `tool` | enum | 已注册工具名；未知工具拒绝 |
| `actor_id` | string | 主体；系统任务使用服务主体 |
| `project_id` | string | 租户隔离键 |
| `environment` | enum | `prod` / `preprod` / `test`；由 Preparation 冻结 |
| `resource_scope` | object | 源/目标对象、表、分区、Secret 引用；最小权限 |
| `params_digest` | string | 规范化参数 SHA256；禁止在协议中传 Secret 明文 |
| `artifact_digest` | string | 制品 SHA256；Capability 绑定 |
| `preparation_id` | string | 准备单 ID；执行类工具必填 |
| `capability` | string | 仅执行类工具传入；不得记录、回显、落库 |
| `idempotency_key` | string | 幂等键；与工具、主体、资源绑定 |
| `correlation_id` | string | 链路追踪 ID |
| `result.status` | enum | `SUCCEEDED` / `FAILED` / `REJECTED` / `UNKNOWN` |
| `result.domain_code` | string | 失败码；成功为空 |
| `result.output_digest` | string | 输出摘要；不返回敏感原文 |
| `result.external_ref` | string | SeaTunnel Job ID、错误表名等外部引用 |
| `result.audit_event_id` | string | 对应 Ledger 事件 ID |

### 3.4 PDP

| 字段 | 规格 |
|---|---|
| 职责 | 根据 ToolIntent、资源范围、环境、数据分级输出 P0-P3 风险决策、审批要求、预算约束；不执行副作用 |
| 输入 | `tool`、`actor_id`、`project_id`、`environment`、`resource_scope`、`data_classification`、`artifact_digest`、`requested_budget`、策略版本 |
| 输出 | `risk_level`（P0/P1/P2/P3）、`required_slots`、`constraints`、`policy_version`、`decision_digest`、`decision` |
| 状态 | `RECEIVED → EVALUATED → BOUND_TO_PREPARATION`；拒绝为 `DENIED` |
| 失败码 | `PDP-400 INVALID_INTENT`、`PDP-403 POLICY_DENY`、`PDP-409 CLASSIFICATION_CONFLICT`、`PDP-422 SCOPE_MISSING`、`PDP-500 POLICY_ENGINE_ERROR` |
| 失败策略 | Fail-closed；策略引擎不可用时不放行执行 |
| 审计事件 | `pdp.decision.recorded`；`pdp.denied` |
| 对应 FR | FR-RUN-01、FR-STUDIO-04、FR-GOV-02 |
| 约束 | P0-P3 的业务语义与各等级审批差异 PRD 未定义，待确认 P-13；任何等级均不得降低四眼原则最低要求 |

### 3.5 Capability Issuer / Verifier

| 字段 | 规格 |
|---|---|
| 职责 | Commit 通过后签发 Ed25519 短时单次 Capability；校验签名、声明、TTL、Scope、制品指纹与消费状态 |
| 输入 | Commit 事实：`preparation_id`、`execution_run_id`、`version_id`、`artifact_digest`、`tool`、`actor_id`、`environment`、`resource_scope`、`approval_facts` |
| 输出 | Capability 紧凑令牌（仅交给 Broker/Worker）、`jti`、`token_digest`、`claims`；验证结果 |
| 状态 | `NOT_ISSUED → ISSUED → PRESENTED → CONSUMED`；`ISSUED/PRESENTED → EXPIRED`；`PRESENTED → REJECTED` |
| TTL | 300 秒；`exp = iat + 300`；过期即拒绝 |
| 绑定声明 | `jti`、`sub`、`project_id`、`environment`、`tool`、`resource_scope`、`artifact_digest`、`preparation_id`、`execution_run_id`、`iat`、`exp` |
| 存储 | 仅存 `token_digest` 与 `jti`；不得存令牌明文；不得通过 API 返回 |
| 失败码 | `CAP-401 SIGNATURE_INVALID`、`CAP-403 SCOPE_MISMATCH`、`CAP-409 ALREADY_CONSUMED`、`CAP-410 EXPIRED`、`CAP-422 CLAIM_MISMATCH`、`CAP-500 SIGNER_UNAVAILABLE` |
| 审计事件 | `capability.issued`、`capability.verified`、`capability.consumed`、`capability.rejected` |
| 对应 FR | FR-RUN-01、FR-RUN-02 |
| 约束 | 令牌编码格式（JWT 或紧凑二进制）与密钥管理方式待确认 P-31；私钥不得进入应用日志或数据库 |

### 3.6 Tool Broker

| 字段 | 规格 |
|---|---|
| 职责 | 所有副作用执行的唯一出口；工具注册、授权、Capability 校验、Replay Guard 调用、工具执行、结果记录 |
| 输入 | Harness 请求协议；工具注册表；PDP 约束；Capability；幂等键 |
| 输出 | `HarnessResult`；工具输出摘要；外部引用；审计事件 |
| 工具注册表 | `conn.test`、`metadata.profile`、`file.parse`、`etl.execute`、`run.cancel`、`shadow.rollback`、`resource.cleanup`、`table.swap`、`secret.materialize`、`benchmark.run` |
| 状态 | `RECEIVED → AUTHORIZED → EXECUTING → SUCCEEDED / FAILED / UNKNOWN`；未授权为 `REJECTED` |
| 失败码 | `TB-400 INVALID_TOOL_CALL`、`TB-403 UNAUTHORIZED`、`TB-403 CAPABILITY_REQUIRED`、`TB-409 CONFLICT`、`TB-424 DEPENDENCY_FAILED`、`TB-503 TOOL_UNAVAILABLE`、`TB-504 TOOL_TIMEOUT` |
| 失败策略 | 授权失败、签名失败、重放、依赖不可用均拒绝；`UNKNOWN` 不自动重试，进入诊断 |
| 审计事件 | `tool.call.authorized`、`tool.call.executed`、`tool.call.rejected`、`tool.call.unknown` |
| 对应 FR | FR-CONN-01、FR-META-02、FR-FILE-01、FR-RUN-02、FR-RUN-04、FR-RUN-05、FR-GOV-01 |
| 约束 | 业务服务不得直接调用工具适配器；Broker 不得被绕过；工具参数不得含 Secret 明文 |

### 3.7 Replay Guard

| 字段 | 规格 |
|---|---|
| 职责 | 保证 Capability 与运维幂等键只能消费一次；拒绝过期、重复、缺失键的请求 |
| 输入 | `jti`、`token_digest`、`idempotency_key`、`tool`、`actor_id`、`project_id`、`environment` |
| 输出 | `ACCEPT` / `REJECT`；消费记录；拒绝原因 |
| 存储 | Redis 原子占位 + PostgreSQL 唯一约束双保险；Redis 不可用即 fail-closed |
| 状态 | `UNSEEN → RESERVED → CONSUMED`；`RESERVED → REJECTED`；`UNSEEN/RESERVED → EXPIRED` |
| 失败码 | `RG-409 REPLAY_DETECTED`、`RG-410 KEY_EXPIRED`、`RG-422 KEY_MISSING`、`RG-503 GUARD_UNAVAILABLE` |
| 审计事件 | `replay.rejected`、`capability.consumed` |
| 对应 FR | FR-RUN-02、FR-RUN-04、FR-RUN-05 |
| 约束 | Capability 消费窗口 300 秒；运维幂等键保留窗口待确认；先占位后执行，执行结果未知不回滚占位 |

### 3.8 Transactional Outbox

| 字段 | 规格 |
|---|---|
| 职责 | 在同一 PostgreSQL 事务内原子写入执行业务事实与投递命令；异步派发；至少一次投递；消费者幂等 |
| 输入 | Commit 事务内的 `ExecutionRun` 事实、`execution_run_id`、`version_id`、`preparation_id`、`capability_digest`、`tool`、`idempotency_key`、`correlation_id` |
| 输出 | Outbox 事件；派发结果；消费确认；死信状态 |
| 逻辑事件字段 | `event_id`、`event_type=execution.command`、`aggregate_id`、`payload_digest`、`idempotency_key`、`attempts`、`available_at`、`created_at`、`status` |
| 状态 | `PENDING → PUBLISHED → CONSUMED`；`PENDING/PUBLISHED → RETRYING → PUBLISHED`；`RETRYING → DEAD_LETTER` |
| 失败码 | `OBX-409 DUPLICATE_EVENT`、`OBX-422 INVALID_EVENT`、`OBX-500 DISPATCH_FAILED`、`OBX-503 BROKER_UNAVAILABLE`、`OBX-410 LEASE_EXPIRED` |
| 审计事件 | `outbox.event.created`、`outbox.event.published`、`outbox.event.consumed`、`outbox.event.failed` |
| 对应 FR | FR-RUN-02 |
| 持久化约束 | PRD 7.1 未定义 Outbox 表；本 Spec 不新增表。Commit 事务必须至少原子写入 `execution_runs` 与对应 `audit_events`；完整 Outbox 物理载体待确认 P-06，确认前视为实现阻塞项 |

### 3.9 Evidence Ledger

| 字段 | 规格 |
|---|---|
| 职责 | 只追加记录关键事件；哈希链防篡改；Ed25519 签名检查点；提供验证结果，不提供修改/删除 |
| 输入 | 审计事件：`project_id`、`actor_id`、`event_type`、`resource_type`、`resource_id`、`payload_digest`、`occurred_at`、`correlation_id` |
| 输出 | Ledger 条目、`prev_event_hash`、`event_hash`、检查点签名、验证结果 |
| 状态 | 条目不可变；链路验证状态 `UNVERIFIED → VERIFIED` 或 `BROKEN` |
| 哈希公式 | `event_hash = SHA256(canonical_json(prev_event_hash, project_id, actor_id, event_type, resource_type, resource_id, payload_digest, occurred_at))`；规范化为 UTF-8、键排序 JSON |
| 检查点 | 对 `{last_sequence, last_event_hash, checkpoint_at}` 做 Ed25519 签名；检查点频率待确认 P-32 |
| 失败码 | `EL-409 CHAIN_CONFLICT`、`EL-422 HASH_MISMATCH`、`EL-500 APPEND_FAILED`、`EL-410 CHECKPOINT_INVALID` |
| 审计事件 | `ledger.checkpoint`、`ledger.verify_failed`、`ledger.tamper_detected` |
| 对应 FR | FR-RUN-03、FR-RUN-05、FR-GOV-04 |
| 约束 | `audit_events` 禁止 UPDATE/DELETE；链序字段 PRD 未定义，待确认 P-09；不得以 `created_at` 作为唯一链序 |

### 3.10 子组件协作矩阵

| 阶段 | 调用链 | 必须通过 | 任一失败结果 |
|---|---|---|---|
| 生成与门禁 | LangGraph → 制品/门禁服务 | 语法、Schema、脱敏、预算 | 禁止冻结与提交 |
| Prepare | 审批服务 → PDP | 权限、资源范围、分级、预算 | 不生成准备单 |
| Approve | 审批服务 → Ledger | 具名、角色槽、非自批、指纹一致 | 拒绝决策并留痕 |
| Commit | 执行编排 → Capability Issuer → Tool Broker → Outbox | 2/2 审批、指纹一致、签名、单次消费、事务原子 | 拒绝 Commit；不产生执行 |
| Execute | Worker → Capability Verifier → Replay Guard → Tool Broker → SeaTunnel | 验签、TTL、Scope、单次消费、工具授权 | 拒绝执行；记录拒绝 |
| Supervise | 监督引擎 → PDP/策略 → Tool Broker | 预算、阈值、Kill 授权 | 预警或硬中断 |
| Rollback | 运维服务 → PDP → Tool Broker → Replay Guard | 角色、Scope、状态、二次确认、幂等 | 拒绝回滚；正式表不变 |
| Audit | 所有组件 → Evidence Ledger | 只追加、哈希链、检查点 | 写入失败即告警；不得静默丢弃 |

## 4. prepare → approve → commit 三阶段协议与状态机

### 4.1 阶段规则

| 阶段 | 触发 | 输入 | 输出 | 副作用 | 失败码 | 审计 | FR |
|---|---|---|---|---|---|---|---|
| Prepare | `POST /versions/{id}/prepare` | 已冻结版本、SHA256、源/目标 Profile、环境、预算、质量契约、监督契约、回滚方案 | Preparation、指纹、风险等级、职责槽、审批请求 | 无外部副作用；仅控制面 DB 写入 | `PREP-409 VERSION_NOT_IMMUTABLE`、`PREP-422 GATE_NOT_PASSED`、`PREP-409 NO_ELIGIBLE_APPROVER`、`PREP-409 FINGERPRINT_CONFLICT` | `preparation.created`、`pdp.decision.recorded`、`approval.slot.assigned` | FR-STUDIO-04、FR-RUN-01 |
| Approve | `POST /approval-requests/{id}/decisions` | Preparation 冻结事实、审批人身份、角色槽、意见 | 具名审批决策；2/2 通过事实 | 无外部副作用 | `APR-403 SELF_APPROVAL_FORBIDDEN`、`APR-403 ROLE_DENIED`、`APR-409 DECISION_IMMUTABLE`、`APR-409 ROLE_SLOT_CONFLICT`、`APR-422 FINGERPRINT_MISMATCH` | `approval.decision.recorded`、`approval.self_approval_blocked` | FR-RUN-01 |
| Commit | `POST /preparations/{id}/commit` | Preparation、2/2 审批、指纹、操作员身份 | ExecutionRun、Capability（仅内部）、Outbox 事件 | 同一 PostgreSQL 事务写入执行事实与 Outbox；签发令牌 | `CMT-403 ROLE_DENIED`、`CMT-409 APPROVAL_INCOMPLETE`、`CMT-409 FINGERPRINT_MISMATCH`、`CMT-409 ALREADY_COMMITTED`、`CMT-503 SIGNER_UNAVAILABLE`、`CMT-503 OUTBOX_WRITE_FAILED` | `approval.validated`、`capability.issued`、`run.committed`、`outbox.event.created` | FR-RUN-01、FR-RUN-02 |

### 4.2 Prepare 规格

| 项 | 规格 |
|---|---|
| 前置条件 | 版本存在；`is_immutable=true`；确定性门禁 4/4 通过；artifact_digest 为 64 位 SHA256；提交人为项目 Maker |
| 冻结事实 | 制品 SHA256、源/目标 Profile 引用、环境、资源范围、数据分级、读取行数/字节/时长预算、质量契约、监督契约、回滚方案、调度策略 |
| 风险决策 | 调用 PDP；输出 P0-P3、约束、审批要求；PDP 拒绝则准备失败 |
| 职责槽 | 按项目 `project_role_grants` 分配 `data_checker`、`security_checker`；两人不得相同且均不得为申请人 |
| 审批请求 | 每个槽生成一条 `approval_requests`，`required_role` 对应槽；状态 `PENDING` |
| 幂等 | 同一 `version_id + artifact_digest + 环境 + 调度 + 预算 + 质量契约` 返回同一 Preparation；不同指纹返回 `PREP-409 FINGERPRINT_CONFLICT` |
| 不可变 | Preparation 创建后冻结事实不可修改；版本变更必须重新 Prepare |
| 禁止 | 不执行 SeaTunnel；不读取业务数据；不物化 Secret；不签发 Capability |

### 4.3 Approve 规格

| 项 | 规格 |
|---|---|
| 审批主体 | 必须为项目内对应职责槽的具名用户；申请人不得审批 |
| 审批绑定 | `approval_id`、`preparation_id`、`version_id`、`artifact_digest`、`actor_id`、`decision`、`opinion`、`decided_at` |
| 决策值 | `approve` / `reject`；拒绝后流程终止，不允许继续 Commit |
| 不可撤销 | 已决策记录不可修改；如需重审，必须重新 Prepare |
| 审批顺序 | PRD 未规定串行或并行；原型标注“数据审批 → 安全审批串行”；待确认 P-11。确认前状态机不得硬编码顺序，只校验 2/2 |
| 意见 | 原型标注审批意见必填；PRD 未定义强制级别，待确认 |
| 失败策略 | 非具名、非角色槽、自批、指纹变化、重复决策全部拒绝 |

### 4.4 Commit 规格

| 项 | 规格 |
|---|---|
| 操作角色 | 仅系统操作员 |
| 服务端复核 | 2/2 审批均 `APPROVED`；两个审批人均非申请人且互不相同；`artifact_digest` 与 Preparation 一致；版本仍不可变；Preparation 未提交过 |
| Capability | 复核通过后签发；绑定工具 `etl.execute`、主体、环境、资源范围、制品指纹、Preparation、ExecutionRun；TTL 300 秒 |
| 原子事务 | 同一 PostgreSQL 事务：创建 `execution_runs`（含 `capability_token_digest` 唯一约束）→ 写 Outbox 事件 → 写审计事件；全部成功才提交 |
| 返回 | 仅返回 `execution_run_id`、状态、`capability_digest`；不返回 Capability 明文 |
| 幂等 | 同一 `preparation_id + Idempotency-Key` 返回同一 ExecutionRun；同一 Preparation 换键再次 Commit 返回 `CMT-409 ALREADY_COMMITTED` |
| 失败策略 | 审批缺失、指纹变化、签名失败、Outbox 写入失败均整体回滚；不产生执行 |
| 禁止 | 不允许 Maker/Checker 调用；不允许跳过 Prepare；不允许直接创建 ExecutionRun |

### 4.5 三阶段状态机

| 当前状态 | 事件 | 目标状态 | 守卫 | 审计 |
|---|---|---|---|---|
| `NOT_PREPARED` | Prepare 成功 | `PREPARED` | 版本不可变、门禁通过、PDP 允许 | `preparation.created` |
| `NOT_PREPARED` | Prepare 失败 | `NOT_PREPARED` | 记录失败码 | `preparation.failed` |
| `PREPARED` | 任一审批拒绝 | `REJECTED` | 决策不可撤销 | `approval.decision.recorded` |
| `PREPARED` | 2/2 审批通过 | `APPROVED` | 两审批人不同且非申请人 | `approval.completed` |
| `APPROVED` | Commit 成功 | `COMMITTED` | 指纹一致、事务成功 | `run.committed` |
| `APPROVED` | Commit 失败 | `APPROVED` | 整体回滚，可重试 | `run.commit_failed` |
| `COMMITTED` | 后续执行 | 由执行状态机接管 | 不回到 Prepare | `run.queued` |

### 4.6 审批状态机

| 当前状态 | 事件 | 目标状态 | 守卫 |
|---|---|---|---|
| `PENDING` | `approve` | `APPROVED` | 具名、角色槽匹配、非申请人、指纹一致 |
| `PENDING` | `reject` | `REJECTED` | 具名、角色槽匹配、非申请人、意见按确认规则 |
| `APPROVED` | 再次决策 | `APPROVED` | 拒绝并返回 `APR-409 DECISION_IMMUTABLE` |
| `REJECTED` | 再次决策 | `REJECTED` | 拒绝并返回 `APR-409 DECISION_IMMUTABLE` |

### 4.7 执行状态机

| 当前状态 | 事件 | 目标状态 | 守卫/动作 |
|---|---|---|---|
| `QUEUED` | Outbox 派发成功 | `DISPATCHED` | 至少一次投递 |
| `QUEUED` | 派发进入死信 | `FAILED` | 记录 `OBX-*`；不自动执行 |
| `DISPATCHED` | Worker 验签与单次消费通过 | `RUNNING` | Capability 验签、Replay Guard 占位 |
| `DISPATCHED` | 验签/重放/Scope 失败 | `FAILED` | 无副作用；记录拒绝 |
| `RUNNING` | SeaTunnel 完成、质量通过、Swap 成功 | `SUCCEEDED` | 正式表已发布 |
| `RUNNING` | 异常、监督硬中断、质量失败 | `FAILED` | 保留快照；不执行 Swap |
| `RUNNING` | 操作员取消 | `CANCELLED` | Kill Job；保留快照与日志 |
| `FAILED` | 受管回滚完成 | `ROLLED_BACK` | 仅清理本 Run 影子表；正式表不变 |
| `CANCELLED` | 受管回滚完成 | `ROLLED_BACK` | 仅清理本 Run 影子表 |
| `SUCCEEDED` | 回滚请求 | `SUCCEEDED` | 拒绝；Swap 后回滚未定义，待确认 P-29 |

### 4.8 拒绝路径总则

| 场景 | 行为 |
|---|---|
| 门禁未过 | 禁止冻结与提交；返回具体校验项 |
| 审批未齐 | Commit 拒绝；不签发 Capability |
| 指纹变化 | Commit 拒绝；必须重新 Prepare |
| Capability 过期或重复 | Worker 拒绝；不执行；记录 `CAP-*` / `RG-*` |
| 执行结果未知 | 进入 `UNKNOWN` 诊断；不自动重试；不自动回滚 |
| 质量未过 | 不执行 Swap；错误行已分流；按失败诊断处理 |
| 监督硬中断 | Kill Job；冻结写入；保留快照；不绕过质量门禁 |

## 5. Capability、Replay Guard、Outbox、Evidence Ledger 规格

### 5.1 Capability 令牌

| 项 | 规格 |
|---|---|
| 算法 | Ed25519 |
| 有效期 | 300 秒，单次消费 |
| 绑定 | 工具、主体、项目、环境、资源范围、制品指纹、Preparation、ExecutionRun |
| 唯一性 | `jti` 全局唯一；`token_digest = SHA256(token)` |
| 签发时机 | Commit 服务端复核 2/2 审批与指纹后 |
| 使用时机 | Worker 消费受管命令前；Tool Broker 执行前复核 |
| 消费语义 | 原子占位成功后才允许执行；失败不返还令牌；重试必须重新走 Prepare/Approve/Commit |
| 存储 | 仅 `jti` 与 `token_digest`；明文不落库、不写日志、不回传 |
| 失败码 | 见 3.5 |
| 审计 | `capability.issued`、`capability.verified`、`capability.consumed`、`capability.rejected` |
| FR | FR-RUN-01、FR-RUN-02 |

#### 5.1.1 Capability 状态机

| 当前状态 | 事件 | 目标状态 | 守卫 |
|---|---|---|---|
| `NOT_ISSUED` | Commit 复核通过 | `ISSUED` | 2/2 审批、指纹一致、签名成功 |
| `ISSUED` | Worker 首次出示 | `PRESENTED` | 签名、TTL、Scope、绑定声明全部通过 |
| `PRESENTED` | Replay Guard 占位成功 | `CONSUMED` | 单次消费 |
| `ISSUED` | 超过 `exp` | `EXPIRED` | 300 秒到期 |
| `PRESENTED` | 重放、Scope 不符、声明不符 | `REJECTED` | 拒绝且无副作用 |
| `CONSUMED` | 再次出示 | `CONSUMED` | 返回 `CAP-409 ALREADY_CONSUMED` |

### 5.2 Replay Guard

| 项 | 规格 |
|---|---|
| 键 | `jti + token_digest`；运维操作使用 `tool + actor_id + idempotency_key` |
| 原子性 | Redis `SET NX EX` 占位；PostgreSQL 唯一约束兜底 |
| TTL | Capability 300 秒；运维幂等键窗口待确认 |
| 失败策略 | 存储不可用即拒绝；不得降级放行 |
| 重放结果 | `RG-409 REPLAY_DETECTED`；返回拒绝原因；写审计；不执行工具 |
| 结果未知 | 占位保持 `CONSUMED`；进入诊断；不自动重放 |
| FR | FR-RUN-02、FR-RUN-04、FR-RUN-05 |

#### 5.2.1 Replay Guard 状态机

| 当前状态 | 事件 | 目标状态 | 说明 |
|---|---|---|---|
| `UNSEEN` | 首次请求 | `RESERVED` | 原子占位成功 |
| `UNSEEN` | 键缺失 | `REJECTED` | `RG-422` |
| `RESERVED` | 工具开始执行 | `CONSUMED` | 单次消费完成 |
| `RESERVED` | TTL 到期 | `EXPIRED` | 不得再消费 |
| `RESERVED` | 重复请求 | `REJECTED` | `RG-409` |
| `CONSUMED` | 重复请求 | `REJECTED` | `RG-409` |

### 5.3 Transactional Outbox

| 项 | 规格 |
|---|---|
| 事务边界 | Commit 的 `execution_runs` 插入与 Outbox 事件写入同一 PostgreSQL 事务 |
| 投递语义 | 至少一次；允许重复投递；消费者按 `execution_run_id + idempotency_key` 去重 |
| 派发 | Celery Beat 或专用派发任务扫描待投递事件；派发间隔待确认 |
| 重试 | 仅投递重试；执行失败不自动重放；超过上限进入死信 |
| 状态只前进 | 不允许 `CONSUMED → PUBLISHED` 等回退 |
| 失败处理 | Broker 不可用保留 `PENDING/RETRYING`；死信告警；人工处理 |
| 持久化 | PRD 未定义 Outbox 表；待确认 P-06 |
| FR | FR-RUN-02 |

#### 5.3.1 Outbox 状态机

| 当前状态 | 事件 | 目标状态 | 说明 |
|---|---|---|---|
| `PENDING` | 派发成功 | `PUBLISHED` | 已投递到 Celery/Redis |
| `PENDING` | 派发失败 | `RETRYING` | 记录尝试次数 |
| `RETRYING` | 派发成功 | `PUBLISHED` | 至少一次 |
| `RETRYING` | 超过上限 | `DEAD_LETTER` | 人工介入 |
| `PUBLISHED` | 消费者确认 | `CONSUMED` | 幂等消费 |
| `PUBLISHED` | 消费者拒绝且不可恢复 | `DEAD_LETTER` | 保留证据 |

### 5.4 Evidence Ledger

| 项 | 规格 |
|---|---|
| 存储 | `audit_events` 只追加；复用 `prev_event_hash`、`event_hash` |
| 链范围 | 按项目链；`genesis` 的 `prev_event_hash=0000...`；跨项目事件按 `project_id` 分链，待确认 P-32 |
| 哈希 | 见 3.9；`payload_digest` 为事件载荷 SHA256，不存敏感原文 |
| 检查点 | 定期对最后序号与哈希签名；签名算法 Ed25519 |
| 验证 | 定时校验链完整性；发现断链标记 `BROKEN` 并告警 |
| 不可变 | 无更新、删除接口；数据库权限禁止 UPDATE/DELETE |
| 失败处理 | 追加失败不得静默；阻断对应业务流程或标记待补偿 |
| FR | FR-RUN-03、FR-RUN-05、FR-GOV-04 |

#### 5.4.1 哈希链状态

| 链路状态 | 条件 | 行为 |
|---|---|---|
| `UNVERIFIED` | 有条目但尚无检查点 | 允许追加；异步验证 |
| `VERIFIED` | 链哈希连续且检查点签名有效 | 正常 |
| `BROKEN` | 哈希不连续、签名无效、条目缺失 | 告警；禁止删除；进入安全事件处理 |

### 5.5 5 分钟单次消费时序

1. Commit 服务端复核 2/2 审批、审批人独立性、制品指纹、Preparation 状态。
2. Capability Issuer 生成 `jti`，签发 Ed25519 令牌，`exp=iat+300`。
3. 同一 PostgreSQL 事务插入 `execution_runs`，`capability_token_digest` 唯一；写入 Outbox 事件与 `run.committed` 审计事件。
4. 事务提交后，Outbox 派发受管命令。
5. Worker 收到命令，校验任务签名、`execution_run_id`、`artifact_digest`、`environment`、`scope`。
6. Worker 调用 Verifier 校验 Capability 签名、TTL、声明绑定。
7. Worker 调用 Replay Guard 原子占位 `jti + token_digest`；失败即拒绝，无副作用。
8. Tool Broker 复核主体权限、PDP 约束、工具注册与 Scope。
9. Broker 调用 `etl.execute` 适配器；Worker 仅在受管上下文内通过 `secret.materialize` 获取 Secret。
10. 执行结果写回；成功/失败/未知均写 Ledger；重复投递被幂等键或 Replay Guard 拒绝。

### 5.6 状态机覆盖检查

| 状态机 | 规格位置 | 关键约束 |
|---|---|---|
| 三阶段协议 | 4.5 | Prepare 无外部副作用；Approve 不可撤销；Commit 原子 |
| 审批状态 | 4.6 | 2/2；自批拒绝；职责槽独立 |
| 执行状态 | 4.7 | 失败不 Swap；成功不因回滚回到执行 |
| Capability 5 分钟单次消费 | 5.1.1 | TTL 300 秒；消费后不可复用 |
| Replay Guard 拒绝 | 5.2.1 | 重复即拒绝；fail-closed |
| Outbox 投递 | 5.3.1 | 至少一次；状态只前进；死信保留 |
| Evidence Ledger 哈希链 | 5.4.1 | 只追加；断链告警；检查点签名 |

## 6. 页面与路由规格

### 6.1 路由总表

| 路由 | 页面 | 可见角色 | 原型画板 | 对应 FR | 状态 |
|---|---|---|---|---|---|
| `/dashboard` | 总览工作台 | 全部 | 01 | FR-DASH-01 | 已定义 |
| `/connections` | 数据连接与资产 / 连接管理 | 全部；编辑限 Maker | 02 | FR-CONN-01/02 | 已定义 |
| `/connections/profiles` | 元数据探查 | 全部；探查限 Maker | 03 | FR-META-01/02 | 已定义 |
| `/assets/files` | 文件资产 | 全部；上传限 Maker | 04 | FR-FILE-01/02 | 已定义 |
| `/studio/:versionId` | Pipeline Studio | 全部；编辑限 Maker | 05 | FR-STUDIO-01..07 | 已定义 |
| `/runs/preparations` | 运行中心 / 准备与审批 | 全部；审批限 Checker | 06 | FR-RUN-01 | 页面已定义；列表与详情接口待确认 |
| `/runs/executions` | 运行中心 / 执行与监控 | 全部；运维限 Ops | 07 | FR-RUN-02 | 已定义 |
| `/runs/quality` | 运行中心 / 质量与诊断 | 全部；运维限 Ops | 08 | FR-RUN-03/05 | 已定义 |
| `/runs/operations` | 运行中心 / 运维操作 | 全部；操作限 Ops | 09 | FR-RUN-04/05 | 已定义 |
| `/governance/benchmark` | 安全治理 / Benchmark 大盘 | 全部；治理限 Checker 2 | 10 | FR-GOV-01..04 | 已定义 |
| `/governance/evolution` | 安全治理 / 安全进化管理 | 待确认 | 无画板 | FR-GOV-02/04 | 原型缺失，待确认 |
| 待确认 | 审计与证据 | 待确认 | 侧栏占位 | 无 FR | 占位，待确认 |

### 6.2 总览工作台 `/dashboard`

| 字段 | 规格 |
|---|---|
| 路由 | `/dashboard` |
| 可见角色 | 全部角色 |
| 页面目标 | 展示当前项目连接数、Pipeline 数量、待审批门禁概况、运行成功率与核心资源分布 |
| 布局区 | 页面头；权限提示条；4 指标卡；运行状态与资源分布；待审批门禁；最近执行；快捷入口与控制面健康 |
| 核心组件 | MetricCard、DonutChart、LegendList、ResourceBar、PendingApprovalList、RunsTable、StatusBadge、HealthList、PermissionBar |
| 数据来源接口 | `GET /api/v1/projects/{project_id}/connections`（连接数）；执行列表、审批列表、聚合指标接口 PRD 未定义，待确认 P-19 |
| 页面状态 | loading；empty；partial（部分接口失败）；stale（超过刷新周期）；error；forbidden |
| 操作 | 刷新；进入审批面板；进入运行中心；查看运行详情 |
| 权限差异 | Maker 无 Commit 入口；Checker 显示待我审批；Ops 显示 Commit/运维入口；Auditor 全只读、无操作按钮 |
| 异常提示 | 401 重新认证；403 无项目权限；404 项目不存在；503 控制面依赖异常；单个卡片失败不阻断其他区域，显示“数据暂不可用” |
| 对应 FR | FR-DASH-01 |

### 6.3 连接管理 `/connections`

| 字段 | 规格 |
|---|---|
| 路由 | `/connections` |
| 可见角色 | 全部；新建/编辑/测试限 Maker |
| 页面目标 | 维护数据库连接与文件数据源；连接测试；Secret 密文保存状态；进入元数据探查与文件资产 |
| 布局区 | 页面头；权限提示条；Tab；筛选栏；Secret 提示条；连接表格；接入类型覆盖条；新建连接 Drawer |
| 核心组件 | Tabs、FilterBar、ConnectionTable、StatusBadge、SecretStateBadge、ConnectionDrawer、FieldRow、SegmentedControl、PermissionBar |
| 数据来源接口 | API-02、API-03、API-04、API-05、API-06 |
| 页面状态 | loading；empty；filtered-empty；drawer-open；submitting；test-running；test-success；test-failed；error；forbidden |
| 操作 | 搜索/筛选/重置；批量测试；新建连接；编辑；单条测试；查看详情；发起元数据探查；上传文件入口 |
| 权限差异 | Maker 可新建/编辑/测试；Checker 1/2、Ops、Auditor 只读；Secret 字段所有角色均只显示引用摘要与保存状态 |
| 异常提示 | 连接测试失败显示错误码与脱敏原因，不显示密码/完整主机；409 名称冲突；422 参数非法；503 Vault/网络不可用；Secret 未配置时禁止保存敏感字段 |
| 对应 FR | FR-CONN-01、FR-CONN-02、FR-FILE-02 |

### 6.4 元数据探查 `/connections/profiles`

| 字段 | 规格 |
|---|---|
| 路由 | `/connections/profiles` |
| 可见角色 | 全部；发起探查限 Maker |
| 页面目标 | 展示数据表 Schema、字段类型、主键、近似统计与脱敏样本；只读、不写入源库 |
| 布局区 | 页面头；权限提示条；Tab；连接/表选择工具栏；探查概况；Schema 与字段统计；脱敏样本视图；敏感字段分级；脱敏策略说明 |
| 核心组件 | ConnectionSelector、TableSelector、ReadonlyBadge、MetaStatCard、SchemaTable、RiskBadge、MaskChip、SampleTable、PermissionBar |
| 数据来源接口 | API-06；探查结果读取接口 PRD 未定义，待确认 P-19 |
| 页面状态 | idle；profiling；success；partial（部分表失败）；failed；sample-masked；empty；forbidden |
| 操作 | 选择连接与表；发起探查；刷新状态；查看字段统计；查看脱敏样本 |
| 权限差异 | Maker 可发起；其他角色只读；所有角色均不可查看原始样本、不可导出 |
| 异常提示 | 只读连接失败；源库超时；采样失败时禁止展示未脱敏数据；脱敏策略缺失时整块样本不展示；503 探查工具不可用 |
| 对应 FR | FR-META-01、FR-META-02 |

### 6.5 文件资产 `/assets/files`

| 字段 | 规格 |
|---|---|
| 路由 | `/assets/files` |
| 可见角色 | 全部；上传/对象导入限 Maker |
| 页面目标 | 上传与解析本地/对象存储文件，提取文件头与字段推断，展示脱敏预览 |
| 布局区 | 页面头；权限提示条；Tab；上传区；文件列表；字段推断结果；文件头预览；底部说明 |
| 核心组件 | UploadDropzone、FileTable、FormatBadge、InferStatusBadge、FileHeadPreview、InferenceTable、ConfidenceLabel、PermissionBar |
| 数据来源接口 | API-07；文件列表、解析状态、推断结果读取接口 PRD 未定义，待确认 P-19 |
| 页面状态 | idle；uploading；parsing；inferred；infer-failed；empty；error；forbidden |
| 操作 | 选择文件；对象存储导入；刷新；查看文件头与推断结果 |
| 权限差异 | Maker 可上传/导入；其他角色只读；文件样本与文件头按字段策略脱敏；不可导出原始文件 |
| 异常提示 | 格式不支持；大小超限（上限待确认 P-15）；解析失败；字段推断失败；对象存储凭据不可用；上传中断可重试 |
| 对应 FR | FR-FILE-01、FR-FILE-02 |

### 6.6 Pipeline Studio `/studio/:versionId`

| 字段 | 规格 |
|---|---|
| 路由 | `/studio/:versionId` |
| 可见角色 | 全部；生成、冻结、提交限 Maker |
| 页面目标 | 自然语言需求输入、LangGraph 澄清与恢复、EtlPlan/HOCON 生成与审查、门禁、版本冻结与审批提交 |
| 布局区 | 页面头；权限提示条；需求输入区；Agent 对话与澄清区；方案与配置审查区（EtlPlan、HOCON、DAG、字段 Diff、脱敏对比）；确定性门禁；版本与审批提交区 |
| 核心组件 | RequirementForm、ProfileSelector、AgentTimeline、ClarificationForm、RepairNotice、PlanTable、HoconCodeBlock、DagCanvas、DiffViewer、GateChecklist、VersionPanel、ApprovalSlotCard、PermissionBar |
| 数据来源接口 | API-08、API-09、API-10、API-11、API-12；版本创建/列表/历史、冻结、Provider 切换接口 PRD 未定义，待确认 P-18 |
| 页面状态 | draft；generating；interrupted（等待回答）；resumed；gate-failed；repairing；gate-passed；frozen；submitted；stale；error；forbidden |
| 操作 | 输入需求；选择源/目标 Profile；发起生成；回答澄清；查看步骤；查看 EtlPlan/HOCON/DAG/Diff；冻结版本；配置调度；提交审批 |
| 权限差异 | Maker 可生成/修复/冻结/提交；Checker 1/2、Ops、Auditor 只读；申请人不可审批；冻结按钮仅在门禁通过时可用；提交后显示职责槽 |
| 异常提示 | 门禁失败列出具体项并禁用冻结/提交；Provider 不可用可切换（策略待确认）；Checkpoint 恢复失败要求重新生成；版本非草稿禁止编辑；HOCON/Schema 错误必须可定位 |
| 对应 FR | FR-STUDIO-01、FR-STUDIO-02、FR-STUDIO-03、FR-STUDIO-04、FR-STUDIO-05、FR-STUDIO-06、FR-STUDIO-07 |

### 6.7 准备与审批 `/runs/preparations`

| 字段 | 规格 |
|---|---|
| 路由 | `/runs/preparations` |
| 可见角色 | 全部；审批限对应 Checker |
| 页面目标 | 展示 Preparation 冻结事实、影响范围、回滚方案、审批人列表与具名审批入口 |
| 布局区 | 页面头；权限提示条；准备单摘要；三阶段状态条；数据审批卡；安全审批卡；审批链路与操作记录；风险与数据画像；Capability 预览；职责分离校验；审批策略 |
| 核心组件 | PreparationSummary、PhaseStepper、ApprovalCard、Checklist、OpinionInput、ApprovalHistoryTable、RiskPanel、BudgetBar、CapabilityPreview、SeparationPanel、PermissionBar |
| 数据来源接口 | API-12、API-13、API-14；Preparation 详情/审批列表接口 PRD 未定义，待确认 P-19 |
| 页面状态 | pending；partial-approved；approved；rejected；committing；committed；commit-failed；error；forbidden |
| 操作 | 批准；驳回；填写意见；查看链路；查看风险画像；Commit 入口仅 Ops 可见 |
| 权限差异 | Maker 只读且不可见审批按钮；Checker 1 仅数据审批；Checker 2 仅安全审批；Ops 在 2/2 后可见 Commit；Auditor 只读；申请人审批按钮禁用 |
| 异常提示 | 非本人职责槽禁止审批；自批拦截并提示；已决策不可修改；指纹变化要求重新 Prepare；Commit 时审批未齐显示缺失槽位 |
| 对应 FR | FR-RUN-01、FR-RUN-02 |

### 6.8 执行与监控 `/runs/executions`

| 字段 | 规格 |
|---|---|
| 路由 | `/runs/executions` |
| 可见角色 | 全部；取消/运维限 Ops |
| 页面目标 | 展示 ExecutionRun 列表、实时运行状态、读取/写入/过滤行数、字节、时长、吞吐与实时日志 |
| 布局区 | 页面头；权限提示条；KPI 条；运行中详情；进度与指标；实时日志；最近执行实例；执行阶段；资源与吞吐；监督与预警 |
| 核心组件 | KpiStrip、RunHeader、ProgressBar、MetricGrid、LogViewer、RunsTable、StageTimeline、ResourceGauge、AlertList、PermissionBar |
| 数据来源接口 | API-15、API-16；执行列表与日志流接口 PRD 未定义，待确认 P-19/P-23 |
| 页面状态 | running；succeeded；failed；cancelled；queued；stale；log-disconnected；error；forbidden |
| 操作 | 刷新；查看详情；查看完整日志；导出日志；取消运行；进入运维操作 |
| 权限差异 | Ops 可取消并进入运维；其他角色只读；取消需二次确认；不可修改冻结版本 |
| 异常提示 | 轮询/订阅中断显示 stale；日志断流保留最后位置；SeaTunnel 不可达；取消失败保留原状态；403 无运维权限 |
| 对应 FR | FR-RUN-02 |

### 6.9 质量与诊断 `/runs/quality`

| 字段 | 规格 |
|---|---|
| 路由 | `/runs/quality` |
| 可见角色 | 全部；运维操作限 Ops |
| 页面目标 | 展示有效写入、错误表分流、错误码分布、质量契约命中与可解释根因诊断 |
| 布局区 | 页面头；权限提示条；KPI 条；错误码分布；错误表脱敏样本；质量契约结果；根因诊断；监督指标；隔离告警 |
| 核心组件 | KpiStrip、ErrorDistribution、ErrorSampleTable、QualityContractList、RootCauseChain、SuggestionList、SupervisionPanel、IsolationPanel、PermissionBar |
| 数据来源接口 | API-15；诊断报告导出接口 PRD 未定义，待确认 P-20 |
| 页面状态 | loading；quality-pass；quality-warning；failed；diagnosing；supervision-breached；empty；forbidden |
| 操作 | 查看质量报告；查看错误样本；查看根因；导出诊断报告（接口待确认）；发起运维操作 |
| 权限差异 | Ops 可发起运维；其他角色只读；诊断与建议只读；不得直接修改质量契约 |
| 异常提示 | 无错误行时展示空态；错误样本必须脱敏；质量契约缺失显示未配置；诊断置信度仅作参考；失败运行不可重入 |
| 对应 FR | FR-RUN-03、FR-RUN-05 |

### 6.10 运维操作 `/runs/operations`

| 字段 | 规格 |
|---|---|
| 路由 | `/runs/operations` |
| 可见角色 | 全部；操作限 Ops |
| 页面目标 | 提供取消、安全重跑、影子表回滚、清理资源入口；二次确认与权限校验 |
| 布局区 | 页面头；权限提示条；操作卡列表；最近运维操作；权限上下文；影子表状态；安全护栏；二次确认弹窗 |
| 核心组件 | OperationCard、RiskBadge、ScopeTag、OpsHistoryTable、PermissionContext、ShadowTablePanel、GuardList、ConfirmDialog、TypedConfirmInput、PermissionBar |
| 数据来源接口 | API-16、API-17；安全重跑、清理、回滚预览、操作审计接口 PRD 未定义，待确认 P-20 |
| 页面状态 | idle；confirming；validating；executing；success；failed；rejected；stale；forbidden |
| 操作 | 取消运行；安全重跑；回滚影子表；清理资源；查看操作审计；查看影子表状态 |
| 权限差异 | 仅 Ops 可执行；高风险操作需二次确认、原因必填、输入确认词；Maker/Checker/Auditor 只读 |
| 异常提示 | 权限不足直接拒绝；环境不匹配拒绝；幂等键缺失拒绝；状态不允许拒绝；回滚失败保留正式表并告警；操作不可撤销 |
| 对应 FR | FR-RUN-04、FR-RUN-05 |

### 6.11 Benchmark 大盘 `/governance/benchmark`

| 字段 | 规格 |
|---|---|
| 路由 | `/governance/benchmark` |
| 可见角色 | 全部；触发评测与治理限 Checker 2 |
| 页面目标 | 运行自动化 Benchmark，展示生成准确率、Schema 覆盖率、P0/P1 拦截率、延迟对比；管理安全进化候选与灰度 |
| 布局区 | 页面头；权限提示条；KPI 条；Benchmark 分层；延迟对比；Benchmark 记录；安全进化候选；治理审查报告；灰度与影子开关 |
| 核心组件 | KpiStrip、LayerCard、LatencyCompare、BenchmarkTable、CandidateList、RiskBadge、GovernanceReport、GrayToggle、GrayBar、KillSwitch、PermissionBar |
| 数据来源接口 | API-18；Benchmark 历史、结果详情、候选、审查、灰度接口 PRD 未定义，待确认 P-19、P-24 |
| 页面状态 | idle；running；completed；warning；failed；candidate-pending；gray-enabled；kill-switch；error；forbidden |
| 操作 | 选择套件与层；触发评测；查看分层结果；查看延迟；查看记录；审查候选；调整灰度；紧急停用 |
| 权限差异 | Checker 2 可触发评测、审查候选、调整灰度；其他角色只读；候选不自动上线；不可修改 Benchmark 基线与阈值 |
| 异常提示 | 数据集版本缺失；评测超时；L0 未过禁止发布候选；灰度调整需复核；紧急停用立即切回 0% 且不删除证据 |
| 对应 FR | FR-GOV-01、FR-GOV-02、FR-GOV-03、FR-GOV-04 |

### 6.12 安全进化管理 `/governance/evolution`

| 字段 | 规格 |
|---|---|
| 路由 | `/governance/evolution`（来自原型页面地图） |
| 可见角色 | 待确认（PRD 仅说明安全审批人管理安全进化） |
| 页面目标 | 展示 Prompt/策略改进候选、审查报告与小流量/影子授权开关 |
| 布局区 | 待确认；无对应画板 |
| 核心组件 | 待确认 |
| 数据来源接口 | PRD 第 8 节未定义，待确认 P-24 |
| 页面状态 | 待确认 |
| 操作 | 待确认 |
| 权限差异 | Checker 2 管理；其他角色只读或禁止，待确认 |
| 异常提示 | 待确认 |
| 对应 FR | FR-GOV-02、FR-GOV-04 |

### 6.13 审计与证据（侧栏占位）

| 字段 | 规格 |
|---|---|
| 路由 | 待确认；原型未给出 |
| 可见角色 | 审计人员；其他角色待确认 |
| 页面目标 | 查看执行历史、审计事件、签名证据账本、质量报告与 Benchmark 评测大盘 |
| 布局区 | 待确认；侧栏标注“占位” |
| 核心组件 | 待确认 |
| 数据来源接口 | PRD 第 8 节未定义审计/账本查询接口，待确认 P-21 |
| 页面状态 | 待确认 |
| 操作 | 只读查询与证据验证；不得修改或删除 |
| 权限差异 | Auditor 只读；其他角色待确认 |
| 异常提示 | 链验证失败告警；无权限拒绝 |
| 对应 FR | 无直接 FR；对应 PRD 2.8.2 审计职责与 2.8.6 Evidence Ledger |

### 6.14 非产品页面

| 画板 | 性质 | 处理 |
|---|---|---|
| 00 封面 · 页面地图 | 原型说明画板 | 不设产品路由；仅作为页面地图与组件规范依据 |
| 11 关键流程 | 原型说明画板 | 不设产品路由；流程规则落入第 4、5、11 章 |
| 12 验收对照 | 原型说明画板 | 不设产品路由；验收以 PRD 第 10 节为准 |

## 7. 前端组件与交互规格

### 7.1 连接与 Profile 管理模块

| 字段 | 规格 |
|---|---|
| 模块名 | 连接与 Profile 管理模块 |
| 职责 | 数据连接表单、连通性测试、元数据安全探查、脱敏样本渲染、文件资产上传与字段推断展示 |
| 依赖接口 | API-02、API-03、API-04、API-05、API-06、API-07；Profile/文件读取接口待确认 |
| 状态管理 | 连接列表、筛选条件、Drawer 表单、测试状态、探查状态、样本数据；状态库选型待确认 |
| 交互事件 | 新建/编辑连接；保存；测试；批量测试；选择连接与表；发起探查；刷新；上传文件；对象存储导入；查看推断结果 |
| 权限控制 | 仅 Maker 显示新建/编辑/测试/上传/探查按钮；服务端二次校验；非 Maker 只读 |
| 异常处理 | 表单字段级错误；Secret 永不回显；网络错误可重试；探查/解析失败显示脱敏错误；空态与部分失败 |
| 对应 FR | FR-CONN-01、FR-CONN-02、FR-META-01、FR-META-02、FR-FILE-01、FR-FILE-02 |

### 7.2 Pipeline Studio 交互模块

| 字段 | 规格 |
|---|---|
| 模块名 | Pipeline Studio 交互模块 |
| 职责 | 自然语言提示词输入、Profile 选择、LangGraph 澄清交互、步骤时间线、HOCON 语法高亮、DAG 图形化、有限修复展示 |
| 依赖接口 | API-08、API-09、API-10、API-11；Provider 切换与版本历史接口待确认 |
| 状态管理 | 需求草稿、生成中、中断问题、回答、恢复状态、步骤状态、修复次数、设计结果、门禁结果；状态库选型待确认 |
| 交互事件 | 提交需求；发起生成；回答问题；恢复执行；切换 Provider；查看 EtlPlan/HOCON/DAG/Diff；刷新设计 |
| 权限控制 | 仅 Maker 可生成/回答/修复；其他角色只读；申请人不可审批；冻结/提交按钮按角色与门禁状态显隐 |
| 异常处理 | 生成失败可重试；中断问题未答禁止继续；Checkpoint 恢复失败提示重新生成；门禁失败定位到具体项；Provider 不可用可切换（策略待确认） |
| 对应 FR | FR-STUDIO-01、FR-STUDIO-02、FR-STUDIO-03、FR-STUDIO-05、FR-STUDIO-06、FR-STUDIO-07 |

### 7.3 不可变版本与 Diff 模块

| 字段 | 规格 |
|---|---|
| 模块名 | 不可变版本与 Diff 模块 |
| 职责 | 对比不同 Pipeline 版本的 Schema、HOCON、质量规则差异；展示冻结状态、SHA256 摘要、版本历史 |
| 依赖接口 | API-11、API-12；版本历史/冻结接口待确认 |
| 状态管理 | 当前版本、对比版本、Diff 结果、冻结状态、门禁状态、摘要 |
| 交互事件 | 选择对比版本；查看新增/删除/修改；查看 HOCON Diff；查看质量规则 Diff；冻结版本；提交审批 |
| 权限控制 | 仅 Maker 可冻结/提交；其他角色只读；冻结后禁止编辑 |
| 异常处理 | 版本不存在；未生成设计；门禁未过禁止冻结；摘要不一致阻断提交；Diff 仅基于不可变版本 |
| 对应 FR | FR-STUDIO-03、FR-STUDIO-04 |

### 7.4 审批流与准备单模块

| 字段 | 规格 |
|---|---|
| 模块名 | 审批流与准备单模块 |
| 职责 | 展示 Preparation 冻结事实、影响分析、回滚方案、Capability 预览、职责槽与具名审批操作 |
| 依赖接口 | API-12、API-13、API-14；准备单列表/详情接口待确认 |
| 状态管理 | 准备单详情、审批状态、意见、当前角色槽、Commit 可用性、风险画像 |
| 交互事件 | 批准；驳回；填写意见；查看审批链；查看风险；Commit；刷新 |
| 权限控制 | 按 `required_role` 与 `actor_id` 控制按钮；申请人按钮禁用；Ops 仅 2/2 后可 Commit；Auditor 只读 |
| 异常处理 | 非本人槽位拒绝；自批拦截；已决策只读；指纹变化要求重新 Prepare；Commit 失败显示缺失审批或系统错误 |
| 对应 FR | FR-RUN-01、FR-RUN-02 |

### 7.5 运行监控与指标模块

| 字段 | 规格 |
|---|---|
| 模块名 | 运行监控与指标模块 |
| 职责 | 轮询或订阅执行状态；展示吞吐曲线、行数/字节/时长、实时日志、质量分流、监督预警与诊断 |
| 依赖接口 | API-15、API-16、API-17；执行列表、日志流、诊断导出接口待确认 |
| 状态管理 | 运行状态、指标快照、日志缓冲、监督告警、质量报告、诊断结果、刷新连接状态 |
| 交互事件 | 刷新；查看日志；取消；查看质量；查看根因；发起运维；导出诊断报告（待确认） |
| 权限控制 | 运维按钮仅 Ops；其他角色只读；取消/回滚二次确认 |
| 异常处理 | 轮询/订阅失败显示 stale 并可重连；日志断流保留位置；指标缺失显示占位；取消失败保留原状态；禁止展示敏感日志 |
| 对应 FR | FR-RUN-02、FR-RUN-03、FR-RUN-04、FR-RUN-05 |

### 7.6 安全治理与评测模块

| 字段 | 规格 |
|---|---|
| 模块名 | 安全治理与评测模块 |
| 职责 | 展示 Benchmark 用例集与分层结果；触发评测；渲染准确率、覆盖率、拦截率、延迟；展示安全进化候选、审查报告与灰度开关 |
| 依赖接口 | API-18；Benchmark 历史/结果、候选、审查、灰度接口待确认 |
| 状态管理 | 套件选择、层选择、评测状态、结果、候选状态、灰度比例、开关状态 |
| 交互事件 | 选择套件/层；触发评测；查看分层；查看延迟；审查候选；调整灰度；紧急停用 |
| 权限控制 | 仅 Checker 2 可触发评测与治理操作；其他角色只读；候选不自动上线 |
| 异常处理 | 数据集缺失；评测超时；L0 未过禁止候选发布；灰度调整需复核；停止操作保留证据 |
| 对应 FR | FR-GOV-01、FR-GOV-02、FR-GOV-03、FR-GOV-04 |

### 7.7 公共前端约束

| 约束 | 规格 |
|---|---|
| 路由守卫 | 未认证跳转登录；无项目权限拒绝；页面级角色控制 |
| 权限渲染 | 前端隐藏按钮不构成安全边界；所有写操作服务端复核 |
| 敏感信息 | 不展示 Secret 明文、密码、Capability 明文、原始敏感样本、完整主机凭据 |
| 轮询/订阅 | 执行状态采用轮询或订阅由 PRD 待确认项决定，前端不得自行定稿；见 P-16 |
| 错误处理 | 统一错误结构；显示 `error_code` 与脱敏消息；不显示堆栈与凭据 |
| 状态展示 | loading、empty、error、forbidden、stale 必须可区分 |
| 演示数据 | 原型数值不作为前端默认值或业务规则 |
| 版本与 Diff | 仅基于不可变版本；不只比较文本 |
| 技术选型 | UI 组件库、状态管理库、HTTP 客户端待确认；不得因选型改变接口契约 |

## 8. 后端模块与职责边界

### 8.1 API 控制面服务（FastAPI / Uvicorn）

| 字段 | 规格 |
|---|---|
| 职责 | HTTP 路由、参数校验、认证鉴权、统一错误结构、调用业务服务与 Harness 入口、返回脱敏结果 |
| 边界 | 不直接调用 SeaTunnel、Vault、影子表、正式表；不搬运业务数据；不绕过 Harness 执行副作用 |
| 依赖表 | 按接口读取业务表；写入仅经业务服务事务 |
| 对外接口 | API-01 至 API-18 |
| 内部协议 | REST/JSON；Harness 请求协议见 3.3；错误结构见 9.2 |
| 异常码 | `API-400`、`API-401`、`API-403`、`API-404`、`API-409`、`API-422`、`API-500`、`API-503` |
| 审计事件 | 不直接写业务审计；由业务服务写领域事件；请求拒绝写安全事件 |
| 对应 FR | 全部 |

### 8.2 认证鉴权与项目成员服务

| 字段 | 规格 |
|---|---|
| 职责 | 用户身份、会话/令牌、项目成员、角色分配、职责槽授权、服务端权限判定 |
| 边界 | 认证机制待确认 P-26；不定义 PRD 之外角色；不提供自批例外 |
| 依赖表 | `users`、`projects`、`project_memberships`、`project_role_grants` |
| 对外接口 | 成员与角色管理接口 PRD 未定义，待确认 P-22 |
| 内部协议 | `authorize(actor, project, action, resource)`；返回允许/拒绝与拒绝码 |
| 异常码 | `AUTH-401`、`AUTH-403`、`ROLE-403`、`ROLE-409` |
| 审计事件 | `project.member.granted`、`project.member.revoked`、`role.grant.changed` |
| 对应 FR | PRD 2.8.1、2.8.2；FR-RUN-01 |

### 8.3 连接与元数据服务

| 字段 | 规格 |
|---|---|
| 职责 | 连接配置、Secret 引用、连通性测试、只读元数据探查、脱敏样本、字段分级 |
| 边界 | 不保存 Secret 明文；不写源库；探查经 Tool Broker；控制面不落地原始样本 |
| 依赖表 | 连接与 Profile 持久化表 PRD 7.1 未定义，待确认 P-04；`audit_events` |
| 对外接口 | API-02 至 API-06 |
| 内部协议 | Tool Broker 工具 `conn.test`、`metadata.profile`；SecretProvider 仅返回引用/句柄 |
| 异常码 | `CONN-409`、`CONN-422`、`CONN-503`、`CONN-504`、`META-403`、`META-422`、`META-503` |
| 审计事件 | `connection.created`、`connection.updated`、`connection.tested`、`metadata.profile.requested`、`metadata.profile.completed` |
| 对应 FR | FR-CONN-01、FR-CONN-02、FR-META-01、FR-META-02 |

### 8.4 文件资产服务

| 字段 | 规格 |
|---|---|
| 职责 | 文件上传、对象存储导入、文件头提取、字段推断、脱敏预览、元数据保存 |
| 边界 | 文件内容不落控制面；解析在 Worker 沙箱；仅保存元数据与推断结果 |
| 依赖表 | `file_assets`、`audit_events` |
| 对外接口 | API-07；列表/状态接口待确认 |
| 内部协议 | Tool Broker 工具 `file.parse`；对象存储受管凭据 |
| 异常码 | `FILE-422`、`FILE-503`、`FILE-504` |
| 审计事件 | `file.asset.uploaded`、`file.asset.parsed`、`file.asset.parse_failed` |
| 对应 FR | FR-FILE-01、FR-FILE-02 |

### 8.5 LangGraph 编排引擎

| 字段 | 规格 |
|---|---|
| 职责 | 可恢复 ETL 生成状态机：意图解析 → 元数据探查 → EtlPlan/HOCON 生成 → 确定性门禁 → 试运行 → 准备审批；中断提问与 Checkpoint 恢复 |
| 边界 | 只生成建议与状态；不执行副作用；不审批；不冻结版本 |
| 依赖表 | `agent_runs`、`pipeline_versions`、`pipeline_artifacts`；Checkpoint 持久化表 PRD 未定义，待确认 |
| 对外接口 | API-09、API-10、API-11 |
| 内部协议 | LangGraph 状态图；Checkpoint 读写；Provider 适配接口 |
| 异常码 | `GEN-409`、`GEN-422`、`GEN-503`、`GEN-504` |
| 审计事件 | `agent.run.started`、`agent.run.interrupted`、`agent.run.resumed`、`agent.run.failed` |
| 对应 FR | FR-STUDIO-01、FR-STUDIO-02、FR-STUDIO-05、FR-STUDIO-06、FR-STUDIO-07 |

### 8.6 制品、门禁与版本服务

| 字段 | 规格 |
|---|---|
| 职责 | EtlPlan/HOCON 制品保存、SHA256 计算、确定性门禁、不可变版本冻结、Diff 生成 |
| 边界 | 门禁未过禁止冻结；冻结后禁止修改；不得只比较文本 |
| 依赖表 | `pipelines`、`pipeline_versions`、`pipeline_artifacts` |
| 对外接口 | API-08、API-11、API-12；冻结接口待确认 P-18 |
| 内部协议 | 门禁校验器；制品摘要；版本差异计算 |
| 异常码 | `GATE-422`、`VER-409`、`VER-422` |
| 审计事件 | `gate.evaluated`、`version.frozen`、`version.diff.generated` |
| 对应 FR | FR-STUDIO-03、FR-STUDIO-04、FR-STUDIO-07 |

### 8.7 Harness 内核接入层

| 字段 | 规格 |
|---|---|
| 职责 | 业务服务到 Harness 的唯一适配层；构造 Harness 请求、传递 Capability、映射结果与审计 |
| 边界 | 不实现 Harness 内部策略；不得绕过 Tool Broker；不得直接执行工具 |
| 依赖表 | 无独立表；引用 Harness 组件与 `audit_events` |
| 对外接口 | 内部调用；无公开 HTTP 接口 |
| 内部协议 | 3.3 Harness 请求与结果协议 |
| 异常码 | `HARNESS-403`、`HARNESS-409`、`HARNESS-503` |
| 审计事件 | 由 Harness 组件写；接入层不重复写 |
| 对应 FR | FR-RUN-01、FR-RUN-02、FR-RUN-04、FR-RUN-05 |

### 8.8 审批服务

| 字段 | 规格 |
|---|---|
| 职责 | Preparation 生成、职责槽分配、审批请求、审批决策、四眼校验、审批链路查询 |
| 边界 | 不签发 Capability；不执行；不修改冻结事实；不撤销审批 |
| 依赖表 | `approval_requests`、`pipeline_versions`、`project_role_grants`、`audit_events`；Preparation 表未定义，待确认 P-05 |
| 对外接口 | API-12、API-13、API-14（Commit 由执行编排调用） |
| 内部协议 | PDP 决策；Ledger 写入；角色校验 |
| 异常码 | `PREP-409`、`PREP-422`、`APR-403`、`APR-409`、`APR-422` |
| 审计事件 | `preparation.created`、`approval.slot.assigned`、`approval.decision.recorded`、`approval.self_approval_blocked` |
| 对应 FR | FR-RUN-01、FR-STUDIO-04 |

### 8.9 执行编排与 Commit 服务

| 字段 | 规格 |
|---|---|
| 职责 | Commit 复核、Capability 签发调用、ExecutionRun 创建、Outbox 原子写入、执行状态查询 |
| 边界 | 仅 Ops 可 Commit；不直接执行 SeaTunnel；不返回 Capability 明文 |
| 依赖表 | `execution_runs`、`approval_requests`、`pipeline_versions`、`audit_events`；Outbox 表未定义，待确认 P-06 |
| 对外接口 | API-14、API-15 |
| 内部协议 | Capability Issuer；Tool Broker；Outbox；Ledger |
| 异常码 | `CMT-403`、`CMT-409`、`CMT-503` |
| 审计事件 | `approval.validated`、`capability.issued`、`run.committed`、`outbox.event.created` |
| 对应 FR | FR-RUN-01、FR-RUN-02 |

### 8.10 Celery Worker / Beat

| 字段 | 规格 |
|---|---|
| 职责 | 消费受管命令、验签、单次消费、执行受管工具、回传状态与指标；Beat 负责派发、监督、检查点等周期任务 |
| 边界 | 只执行 Broker 派发命令；不直接接受用户请求；不绕过 Capability 与 Replay Guard；不自动重入失败运行 |
| 依赖表 | `execution_runs`、`runtime_supervision_snapshots`、`audit_events` |
| 对外接口 | 无公开 HTTP；内部任务协议 |
| 内部协议 | Celery 任务消息；Harness 命令；SeaTunnel 适配器 |
| 异常码 | `EXE-409`、`EXE-410`、`EXE-503`、`EXE-504` |
| 审计事件 | `run.started`、`run.succeeded`、`run.failed`、`tool.call.executed` |
| 对应 FR | FR-RUN-02、FR-RUN-05 |

### 8.11 SeaTunnel 适配与运行监督

| 字段 | 规格 |
|---|---|
| 职责 | SeaTunnel Zeta 作业提交、状态查询、Kill、影子表写入、错误表分流、原子 Swap；实时监督预算与阈值 |
| 边界 | 数据面执行；控制面不搬运数据；监督越线只预警/硬中断/隔离告警，不跳过审批 |
| 依赖表 | `execution_runs`、`runtime_supervision_snapshots`、`audit_events` |
| 对外接口 | 无公开 HTTP；由 Tool Broker 调用 |
| 内部协议 | SeaTunnel REST/Zeta 客户端；监督指标采集 |
| 异常码 | `SUP-409`、`SUP-422`、`SUP-503`、`SUP-504` |
| 审计事件 | `supervision.warning`、`supervision.interrupted`、`quality.report.generated`、`swap.completed` |
| 对应 FR | FR-RUN-02、FR-RUN-03、FR-RUN-05 |

### 8.12 诊断服务

| 字段 | 规格 |
|---|---|
| 职责 | 提取错误堆栈与失败快照，生成可解释根因与修复建议；只读 |
| 边界 | 不自动修复；不自动重跑；不修改质量契约；不展示敏感原文 |
| 依赖表 | `execution_runs`、`runtime_supervision_snapshots`、`audit_events` |
| 对外接口 | API-15 响应内质量/诊断字段；独立诊断接口待确认 |
| 内部协议 | 日志与快照读取；规则/模型诊断 |
| 异常码 | `DIAG-422`、`DIAG-503` |
| 审计事件 | `diagnosis.generated` |
| 对应 FR | FR-RUN-03、FR-RUN-05 |

### 8.13 Benchmark 与安全进化服务

| 字段 | 规格 |
|---|---|
| 职责 | 运行 L0/L1/L2 Benchmark，计算准确率、覆盖率、拦截率、延迟；管理候选、审查报告、灰度开关 |
| 边界 | 候选不自动上线；不修改基线/阈值；L2 仅影子执行；不写正式表 |
| 依赖表 | Benchmark 结果、数据集版本、候选、灰度持久化表 PRD 未定义，待确认 P-08 |
| 对外接口 | API-18；其余待确认 |
| 内部协议 | Celery 评测任务；Harness `benchmark.run`；Ledger 记录 |
| 异常码 | `BENCH-403`、`BENCH-409`、`BENCH-422`、`BENCH-503` |
| 审计事件 | `benchmark.run.started`、`benchmark.run.completed`、`governance.candidate.reviewed`、`governance.gray.changed` |
| 对应 FR | FR-GOV-01、FR-GOV-02、FR-GOV-03、FR-GOV-04 |

### 8.14 SecretProvider 适配

| 字段 | 规格 |
|---|---|
| 职责 | Vault KV v2 凭据读写、Secret 引用生成、Worker 受管物化、轮换 |
| 边界 | 控制面只保存引用；明文仅存在于受管执行上下文内存；不写日志、不落库、不回传 |
| 依赖表 | 无；Secret 存 Vault |
| 对外接口 | 无公开 HTTP；由 Tool Broker `secret.materialize` 调用 |
| 内部协议 | Vault KV v2 API；短期租约 |
| 异常码 | `SEC-403`、`SEC-404`、`SEC-503`、`SEC-504` |
| 审计事件 | `secret.materialized`、`secret.access_denied`、`secret.rotated` |
| 对应 FR | FR-CONN-01、FR-META-02、FR-RUN-02 |

### 8.15 职责边界矩阵

| 调用方 | 允许 | 禁止 |
|---|---|---|
| Vue 前端 | 仅调用 API-01 至 API-18 | 直连数据库、Vault、Tool Broker、SeaTunnel |
| FastAPI 路由 | 业务服务、Harness 接入层 | 直接执行 SeaTunnel、直接物化 Secret、直接写影子表/正式表 |
| LangGraph | 生成、门禁、状态持久化 | 执行工具、审批、冻结、Commit |
| 审批服务 | 生成 Preparation、写审批 | 签发 Capability、执行 |
| 执行编排 | Commit、创建 ExecutionRun、写 Outbox | 直接提交 SeaTunnel 作业 |
| Celery Worker | 消费 Broker 命令、执行受管工具 | 接受用户请求、绕过 Replay Guard、自动重试执行 |
| Celery Beat | 派发、监督、检查点 | 直接执行数据搬运 |
| Tool Broker | 调用注册工具适配器 | 被业务服务绕过；执行未注册工具 |
| 数据面 SeaTunnel | 影子表、错误表、Swap | 写控制面业务表、审批、签发令牌 |

## 9. 接口契约

### 9.1 通用规则

| 项 | 规格 |
|---|---|
| 基线 | 仅使用 PRD 第 8 节 18 个接口；不新增路径 |
| 认证 | 认证机制待确认 P-26；写接口必须服务端鉴权 |
| 项目隔离 | 资源必须属于当前项目；跨项目访问拒绝 |
| 幂等键 | 写接口使用 `Idempotency-Key` 请求头；同键同载荷返回首次结果；同键不同载荷返回 `409`；请求体携带 `idempotency_key` 的接口（API-13/14/16/17/18）须与请求头一致，不一致返回 `422` |
| 追踪 | 接受 `X-Correlation-Id`；响应回传 |
| 错误结构 | `{"error_code":string,"message":string,"correlation_id":string,"details":object}`；不得含 Secret、令牌、原始敏感值 |
| 成功结构 | `{"data": object, "correlation_id": string}`；列表响应的 `data` 内回显 `page_size` |
| 成功状态码 | 创建类接口（API-03/07/08/09/12/14/18）返回 `201`；其余返回 `200` |
| 503 结构 | 依赖未就绪时 `details` 为 `{"dependency": "<组件名>", "status": "not_implemented"}` |
| 分页 | 列表接口使用 `page`、`page_size`；上限待确认 |
| 审计 | 每个写操作至少写一条领域审计事件；只读查询默认不写 Ledger |
| 时间 | ISO 8601；服务端时区统一；展示时区按项目配置 |

### 9.2 接口清单

| ID | 方法 / 路径 | 用途 | 权限 | 请求字段 | 响应字段 | 错误码 | 幂等 / 重放 | 审计 | FR |
|---|---|---|---|---|---|---|---|---|---|
| API-01 | GET `/health` | 检查系统组件与依赖就绪状态 | 未定义；建议公开只读，待确认 P-27 | 无 | `status`、`components[{name,status,latency_ms}]`、`version`、`time` | `503` | GET 无副作用；不适用重放 | 不写 Ledger | 交付物；FR-RUN-02（关联） |
| API-02 | GET `/api/v1/projects/{project_id}/connections` | 查询项目数据源连接列表 | 项目成员只读 | 路径 `project_id`；查询 `type`、`env`、`status`、`page`、`page_size` | `items[{id,name,type,env,status,host_masked,source_target,last_tested_at,secret_state}]`、`total`、`page` | `400`、`401`、`403`、`404`、`500` | GET 无副作用 | 不写 Ledger | FR-CONN-01、FR-CONN-02 |
| API-03 | POST `/api/v1/connections` | 创建数据源连接 | Maker | `name`、`type`、`env`、`host`、`port`、`database`、`username`、`secret_ref`、`readonly`、`tls`、`file_source` | `id`、`status`、`secret_state`、`created_at` | `400`、`401`、`403`、`409`、`422`、`503` | `Idempotency-Key`；同键同载荷返回首次结果；冲突 `409` | `connection.created`、`secret.ref.bound` | FR-CONN-01、FR-CONN-02 |
| API-04 | PUT `/api/v1/connections/{id}` | 编辑数据源连接 | Maker | 路径 `id`；可编辑字段同 API-03；Secret 仅 `secret_ref` | `id`、`status`、`secret_state`、`updated_at` | `400`、`401`、`403`、`404`、`409`、`422`、`503` | `Idempotency-Key`；不返回 Secret | `connection.updated` | FR-CONN-01 |
| API-05 | POST `/api/v1/connections/{id}/tests` | 测试数据源连通性 | Maker | 路径 `id`；可选 `timeout_ms` | `success`、`latency_ms`、`error_code`、`tested_at` | `401`、`403`、`404`、`422`、`503`、`504` | 测试可重复；经 Tool Broker；失败原因脱敏 | `connection.tested` | FR-CONN-01 |
| API-06 | POST `/api/v1/connections/{id}/profiles` | 发起只读元数据探查与脱敏样本采集 | Maker | 路径 `id`；`schemas`、`tables`、`sample_rows`、`readonly=true` | `profile_status`、`sampled_at`、`tables`、`columns`、`masked_samples`；异步时返回任务标识 | `401`、`403`、`404`、`422`、`503`、`504` | `Idempotency-Key`；同连接同范围去重；不得写源库 | `metadata.profile.requested`、`metadata.profile.completed` | FR-META-01、FR-META-02 |
| API-07 | POST `/api/v1/file-assets` | 上传并解析异构文件数据源 | Maker | multipart 文件或对象存储路径；`format`、`source`、`project_id` | `id`、`status`、`file_format`、`schema_json`、`created_at` | `401`、`403`、`413`、`422`、`503` | `Idempotency-Key`；重复上传按业务键去重待确认 | `file.asset.uploaded`、`file.asset.parsed` | FR-FILE-01、FR-FILE-02 |
| API-08 | POST `/api/v1/pipelines` | 创建 Pipeline 项目定义 | Maker | `project_id`、`name`、`code`、`description` | `pipeline_id`、`status`、`created_at` | `401`、`403`、`409`、`422` | `Idempotency-Key`；`project_id + code` 唯一 | `pipeline.created` | FR-STUDIO-01、FR-STUDIO-04 |
| API-09 | POST `/api/v1/versions/{version_id}/generation` | 输入自然语言需求，触发 LangGraph 候选生成 | Maker | 路径 `version_id`；`prompt`、`source_profile_ref`、`target_profile_ref`、`provider`、`thread_id` | `agent_run_id`、`thread_id`、`status`、`interrupt{question,fields}`、`design_digest` | `401`、`403`、`404`、`409`、`422`、`503`、`504` | `Idempotency-Key`；同一 thread 并发生成拒绝 | `agent.run.started`、`agent.run.interrupted` | FR-STUDIO-01、FR-STUDIO-02、FR-STUDIO-05、FR-STUDIO-06、FR-STUDIO-07 |
| API-10 | POST `/api/v1/agent-runs/{run_id}/answers` | 提交澄清问题回答，恢复 Agent 状态机 | Maker（运行发起人） | 路径 `run_id`；`answers`、`thread_id` | `status`、`next_question`、`design_ready`、`checkpoint_ref` | `401`、`403`、`404`、`409`、`422` | 同一问题重复回答幂等；状态不允许 `409` | `agent.run.resumed` | FR-STUDIO-02、FR-STUDIO-06 |
| API-11 | GET `/api/v1/versions/{version_id}/design` | 查询 EtlPlan、HOCON、DAG、质量契约 | 项目成员只读 | 路径 `version_id` | `etl_plan_json`、`hocon_text`、`dag`、`quality_contract`、`gate_result`、`diff`、`masking` | `401`、`403`、`404`、`409`、`500` | GET 无副作用；HOCON 中主机/账号脱敏 | 不写 Ledger | FR-STUDIO-03、FR-STUDIO-07 |
| API-12 | POST `/api/v1/versions/{version_id}/prepare` | 生成 Preparation，推导影响范围与回滚方案 | Maker | 路径 `version_id`；`schedule`、`budget`、`quality_contract_ref` | `preparation_id`、`fingerprint`、`risk_level`、`approval_slots`、`rollback_plan`、`status` | `401`、`403`、`404`、`409`、`422`、`503` | 同版本同指纹幂等；不同指纹 `409` | `preparation.created`、`pdp.decision.recorded`、`approval.slot.assigned` | FR-STUDIO-04、FR-RUN-01 |
| API-13 | POST `/api/v1/approval-requests/{approval_id}/decisions` | 提交具名审批决策 | 对应角色槽 Checker | 路径 `approval_id`；`decision`、`opinion`、`idempotency_key` | `approval_id`、`status`、`decided_at`、`next_slot_status` | `401`、`403`、`404`、`409`、`422` | 同审批同决策幂等；重复决策 `409`；已决策不可覆盖 | `approval.decision.recorded`、`approval.self_approval_blocked` | FR-RUN-01 |
| API-14 | POST `/api/v1/preparations/{preparation_id}/commit` | 校验审批与指纹，签发 Capability 并原子提交执行 | Ops | 路径 `preparation_id`；`idempotency_key` | `execution_run_id`、`status`、`committed_at`、`capability_digest` | `401`、`403`、`404`、`409`、`503` | 同 Preparation 仅一次执行；同键返回同一 Run；不返回令牌明文 | `approval.validated`、`capability.issued`、`run.committed`、`outbox.event.created` | FR-RUN-01、FR-RUN-02 |
| API-15 | GET `/api/v1/execution-runs/{id}` | 查询任务执行状态、指标与质量报告 | 项目成员只读 | 路径 `id` | `status`、`engine_job_id`、`metrics`、`quality_report`、`supervision`、`started_at`、`finished_at`、`recent_logs` | `401`、`403`、`404`、`500` | GET 无副作用；日志脱敏 | 不写 Ledger | FR-RUN-02、FR-RUN-03、FR-RUN-05 |
| API-16 | POST `/api/v1/execution-runs/{id}/cancel` | 请求取消运行中作业 | Ops | 路径 `id`；`reason`、`idempotency_key` | `status`、`cancelled_at`、`external_ref` | `401`、`403`、`404`、`409`、`503`、`504` | 同 Run 重复取消幂等；终态 `409`；经 Tool Broker | `run.cancel_requested`、`run.cancelled` | FR-RUN-04 |
| API-17 | POST `/api/v1/execution-runs/{id}/rollback` | 触发受管影子表回滚与清理 | Ops | 路径 `id`；`reason`、`confirmation=ROLLBACK`、`idempotency_key` | `rollback_status`、`ledger_event_id`、`finished_at` | `401`、`403`、`404`、`409`、`422`、`503` | 同 Run 同键幂等；Replay Guard；仅失败/取消运行可回滚 | `run.rollback_requested`、`run.rolled_back`、`run.cleaned` | FR-RUN-04、FR-RUN-05 |
| API-18 | POST `/api/v1/benchmarks/run` | 触发自动化安全与准确率 Benchmark | Checker 2 | `suite_id`、`layer`、`dataset_version`、`idempotency_key` | `benchmark_run_id`、`status`、`started_at` | `401`、`403`、`409`、`422`、`503` | `Idempotency-Key`；同套件同层并发拒绝 | `benchmark.run.started`、`benchmark.run.completed` | FR-GOV-01、FR-GOV-03、FR-GOV-04 |

### 9.3 缺失接口（待确认）

| 能力 | 被谁需要 | PRD 第 8 节状态 | 处理 |
|---|---|---|---|
| 总览聚合指标 | `/dashboard` | 未定义 | 待确认 P-19；不得前端聚合海量数据 |
| 连接详情 / Secret 状态查询 | `/connections` | 仅有列表与创建/编辑 | 待确认 |
| Profile 结果读取 | `/connections/profiles` | 仅有触发探查 | 待确认 P-19 |
| 文件资产列表 / 解析状态 / 推断结果 | `/assets/files` | 仅有上传 | 待确认 P-19 |
| Pipeline 版本创建 / 列表 / 历史 | `/studio/:versionId` | 仅有创建 Pipeline | 待确认 P-18 |
| 版本冻结 | `/studio/:versionId` | 未定义 | 待确认 P-18；阻塞冻结动作 |
| 门禁结果单独查询 | `/studio/:versionId` | 未定义；设计接口可能内含 | 待确认 |
| Provider 列表 / 切换 | `/studio/:versionId` | 未定义；生成请求可带 provider | 待确认 P-17 |
| Preparation 列表 / 详情 | `/runs/preparations`、`/dashboard` | 仅有 Prepare 与 Commit | 待确认 P-19 |
| 审批请求列表 / 详情 | `/runs/preparations`、`/dashboard` | 仅有决策 | 待确认 P-19 |
| ExecutionRun 列表 | `/dashboard`、`/runs/executions` | 仅有详情 | 待确认 P-19 |
| 实时日志流 | `/runs/executions` | 未定义 | 待确认 P-23 |
| 质量报告导出 / 诊断导出 | `/runs/quality` | 未定义 | 待确认 P-20 |
| 安全重跑 | `/runs/operations` | 未定义 | 待确认 P-20 |
| 清理资源 | `/runs/operations` | 未定义 | 待确认 P-20 |
| 回滚预览 / 操作审计查询 | `/runs/operations` | 未定义 | 待确认 P-20 |
| Benchmark 历史 / 结果 / 导出 | `/governance/benchmark` | 仅有触发 | 待确认 P-24 |
| 安全进化候选 / 审查 / 灰度 / 停用 | `/governance/benchmark`、`/governance/evolution` | 未定义 | 待确认 P-24 |
| 审计事件 / 证据账本查询 / 链验证 | 审计与证据页 | 未定义 | 待确认 P-21 |
| 成员与角色分配 | 项目管理 | In Scope 但无接口 | 待确认 P-22 |

## 10. 数据模型与约束

### 10.1 数据表清单

| 表名 | 用途 | 关键字段 | 主外键 / 约束 | 索引建议 | 敏感字段 | 生命周期 | 对应 FR |
|---|---|---|---|---|---|---|---|
| `users` | 用户身份 | `id`、`username`、`display_name`、`email`、`status`、`created_at`、`updated_at` | PK `id`；UNIQUE `username`、`email`；`status` 枚举 | `(status)`、`(email)` | `email` | 禁用不删除；保留策略待确认 | PRD 2.8.1 |
| `projects` | 多租户项目 | `id`、`name`、`code`、`description`、`created_at`、`updated_at` | PK `id`；UNIQUE `code` | `(code)` | 无 | 归档字段未定义；生命周期待确认 | PRD 2.8.1 |
| `project_memberships` | 项目成员 | `id`、`project_id`、`user_id`、`role`、`created_at`、`updated_at` | PK `id`；FK `project_id`、`user_id`；UNIQUE `(project_id,user_id)`；`role` 枚举 | `(user_id)`、`(project_id,role)` | 无 | 成员移除需审计；是否软删待确认 | PRD 2.8.2、2.8.11 |
| `project_role_grants` | 职责槽授权 | `id`、`project_id`、`user_id`、`role_slot`、`created_at`、`updated_at` | PK `id`；FK `project_id`、`user_id`；UNIQUE `(project_id,user_id,role_slot)`；`role_slot` 枚举 | `(project_id,role_slot)` | 无 | 变更需审计；历史保留待确认 | PRD 2.8.2；FR-RUN-01 |
| `pipelines` | Pipeline 定义 | `id`、`project_id`、`name`、`code`、`description`、`status`、`created_at`、`updated_at` | PK `id`；FK `project_id`；UNIQUE `(project_id,code)`；`status` 枚举待确认 | `(project_id,status)` | 无 | 归档/删除待确认 | FR-STUDIO-01、FR-STUDIO-04 |
| `pipeline_versions` | 不可变版本 | `id`、`pipeline_id`、`version_number`、`etl_plan_json`、`hocon_text`、`artifact_digest`、`is_immutable`、`created_at`、`updated_at` | PK `id`；FK `pipeline_id`；UNIQUE `(pipeline_id,version_number)`；`artifact_digest` 64 位 SHA256；`is_immutable=true` 后禁止修改内容字段 | `(pipeline_id,created_at)`、`(artifact_digest)` | HOCON 可能含主机/账号信息，需脱敏 | 不可变版本永久保留；删除禁止 | FR-STUDIO-04；FR-RUN-01 |
| `pipeline_artifacts` | 版本制品 | `id`、`version_id`、`artifact_type`、`artifact_digest`、`content`、`created_at` | PK `id`；FK `version_id`；UNIQUE `(version_id,artifact_type,artifact_digest)` | `(version_id,artifact_type)` | `content` 禁止含 Secret 明文 | 随版本不可变；长期保留 | FR-STUDIO-03、FR-STUDIO-04 |
| `agent_runs` | Agent 运行 | `id`、`version_id`、`thread_id`、`prompt`、`status`、`step_count`、`error_message`、`created_at`、`updated_at` | PK `id`；FK `version_id`；`step_count >= 0`；`status` 枚举 | `(version_id,created_at)`、`(thread_id)` | `prompt` 可能含业务敏感信息；`error_message` 需脱敏 | 保留用于恢复与审计；期限待确认 | FR-STUDIO-02、FR-STUDIO-06、FR-STUDIO-07 |
| `approval_requests` | 审批请求 | `id`、`preparation_id`、`version_id`、`required_role`、`status`、`decision`、`approver_id`、`decided_at`、`created_at`、`updated_at` | PK `id`；FK `version_id`、`approver_id`；UNIQUE `(preparation_id,required_role)`；`decision` 枚举；已决策不可更新 | `(preparation_id)`、`(approver_id,status)`、`(version_id)` | 审批意见可能含敏感信息，需脱敏 | 只追加；保留策略待确认 | FR-RUN-01 |
| `execution_runs` | 执行实例 | `id`、`version_id`、`preparation_id`、`capability_token_digest`、`status`、`engine_job_id`、`input_records`、`output_records`、`error_records`、`bytes_processed`、`started_at`、`finished_at`、`created_at`、`updated_at` | PK `id`；FK `version_id`；UNIQUE `capability_token_digest`；计数 `>= 0`；`status` 枚举 | `(version_id,created_at)`、`(preparation_id)`、`(status)`、`(engine_job_id)` | 无直接敏感值；指标需聚合 | 长期保留；清理策略待确认 | FR-RUN-02、FR-RUN-03、FR-RUN-04、FR-RUN-05 |
| `file_assets` | 文件资产元数据 | `id`、`project_id`、`file_name`、`file_path`、`file_size`、`file_format`、`schema_json`、`created_at`、`updated_at` | PK `id`；FK `project_id`；`file_size >= 0`；`file_format` 枚举 | `(project_id,created_at)`、`(file_format)` | `file_path`、`file_name` 可能含敏感信息 | 原文件在对象存储；元数据生命周期待确认 | FR-FILE-01、FR-FILE-02 |
| `runtime_supervision_snapshots` | 运行监督快照 | `id`、`execution_run_id`、`metrics_json`、`decision`、`action_taken`、`created_at` | PK `id`；FK `execution_run_id`；只追加 | `(execution_run_id,created_at)` | `metrics_json` 不含原始业务值 | 只追加；保留期限待确认 | FR-RUN-02、FR-RUN-05 |
| `audit_events` | 审计证据账本 | `id`、`project_id`、`actor_id`、`event_type`、`resource_type`、`resource_id`、`payload_digest`、`prev_event_hash`、`event_hash`、`created_at` | PK `id`；FK `project_id`、`actor_id`；UNIQUE `event_hash`；禁止 UPDATE/DELETE；链序字段待确认 | `(project_id,created_at)`、`(resource_type,resource_id)`、`(event_type)` | `payload_digest` 仅摘要；禁止原始敏感载荷 | 只追加；永久保留或按合规期限 | FR-RUN-03、FR-RUN-05、FR-GOV-04；PRD 2.8.6 |

### 10.2 关键数据规则

| 规则 | 约束 |
|---|---|
| 不可变版本 | `pipeline_versions.is_immutable=true` 后，`etl_plan_json`、`hocon_text`、`artifact_digest` 禁止修改；应用层与数据库触发器双重保护 |
| 摘要格式 | `artifact_digest`、`capability_token_digest`、`event_hash`、`prev_event_hash` 使用小写 64 位十六进制 SHA256 |
| 单次执行 | `execution_runs.capability_token_digest` UNIQUE；同一令牌摘要只能对应一个 Run |
| 审批唯一 | 同一 Preparation 同一 `required_role` 只能有一条审批请求 |
| 审批不可撤销 | `approval_requests` 已决策记录禁止更新 `decision`、`approver_id`、`decided_at` |
| 账本只追加 | `audit_events` 禁止 UPDATE/DELETE；任何修正以新事件追加 |
| 哈希链 | 每条事件引用同项目前序 `event_hash`；创世事件前缀为固定零串；链序不得依赖 `created_at` 单独排序 |
| 计数非负 | 执行行数、字节数、错误数均 `>= 0` |
| 敏感字段 | 禁止在 `pipeline_versions`、`pipeline_artifacts`、`agent_runs`、`audit_events` 中保存 Secret 明文、密码、Capability 明文、原始敏感样本 |
| 外键 | 所有 `project_id`、`version_id`、`preparation_id`、`execution_run_id`、`approver_id` 建立外键或等效完整性校验 |

### 10.3 缺失持久化实体（待确认）

| 实体 | 被谁引用 | PRD 7.1 状态 | 影响 |
|---|---|---|---|
| 连接配置 | API-02 至 API-06、FR-CONN | 未列出 | 连接管理无法落地；待确认 P-04 |
| 元数据 Profile / 采样结果 | FR-META | 未列出 | 探查结果无法持久化；待确认 P-04 |
| Preparation | `approval_requests.preparation_id`、API-12/14 | 未列出 | `preparation_id` 无对应表；待确认 P-05 |
| 申请人身份 | 自批校验 | 未列出 | 审批表无申请人字段；待确认 P-10 |
| Outbox 事件 | FR-RUN-02 | 未列出 | 可靠投递物理载体缺失；待确认 P-06 |
| Capability 消费记录 | Replay Guard | 未列出；可用 `execution_runs.capability_token_digest` 部分承载 | 单次消费与 JTI 记录不完整；待确认 P-07 |
| Benchmark 结果 / 数据集版本 | FR-GOV | 未列出 | 评测历史无法持久化；待确认 P-08 |
| 安全进化候选 / 灰度状态 | FR-GOV-02 | 未列出 | 治理页面无法落地；待确认 P-08 |
| Ledger 链序 | FR-RUN-05 | 未列出 | 哈希链缺少可靠序号；待确认 P-09 |

说明：PRD 7.1 表述为“至少包含”，但本 Spec 遵循“不新增未定义表”硬约束，不在此处补表；上述实体确认前不得以临时表直接上线。

## 11. 异步任务、运行监督与质量契约

### 11.1 Celery 拓扑与任务契约

| 项 | 规格 |
|---|---|
| Broker / Backend | Redis；版本与拓扑待确认 P-28 |
| 任务队列 | 执行、评测、维护三类逻辑队列；具体命名待确认 |
| `dispatch_outbox` | Beat 周期扫描 Outbox；派发受管命令；间隔待确认 |
| `execute_etl_run` | 消费执行命令；验签、单次消费、调用 Tool Broker；任务键使用 `execution_run_id` |
| `run_benchmark` | 执行 L0/L1/L2 评测；L2 仅影子执行 |
| `supervision_tick` | 采集运行指标；按契约预警或硬中断 |
| `ledger_checkpoint` | 生成签名检查点；频率待确认 |
| 任务消息字段 | `task_id`、`execution_run_id`、`command_digest`、`artifact_digest`、`environment`、`attempt`、`correlation_id` |
| 重试 | 仅消息投递重试；执行失败不自动重放；超过上限进入死信 |
| 并发 | Worker 并发、队列配额待确认 |
| 审计 | 任务开始、成功、失败、死信均写 Ledger |

### 11.2 执行阶段

| 阶段 | 触发 | 成功条件 | 失败处理 | 审计 |
|---|---|---|---|---|
| 准备单已批准 | 2/2 审批 | 审批事实完整 | 回到审批 | `approval.completed` |
| Capability 已签发 | Commit | 签名成功、TTL 300s | Commit 失败 | `capability.issued` |
| Outbox 已投递 | 派发 | 至少一次投递 | 重试/死信 | `outbox.event.published` |
| Celery 任务执行 | Worker 消费 | 验签、单次消费、工具授权 | 拒绝并记录 | `run.started` |
| SeaTunnel 影子表写入 | 工具执行 | 有效行写入、错误行分流 | 失败快照 | `tool.call.executed` |
| 质量校验 | 影子表完成 | 质量契约通过 | 不 Swap；诊断 | `quality.report.generated` |
| 原子 Swap | 质量通过 | 正式表切换成功 | 不标记成功；诊断 | `swap.completed` |

### 11.3 RuntimeSupervisionContract

| 字段 | 规格 |
|---|---|
| 冻结时点 | Prepare 阶段随 Preparation 冻结 |
| 指标 | 最大读取行数、最大写入字节数、最大执行时长、输出放大比、错误拒绝率 |
| 阈值来源 | 契约；PRD 未给默认值，待确认 P-14；原型数值仅为演示 |
| 动作 | `WARN` 预警；`PAUSE_WRITE` 暂停写入；`KILL_JOB` 硬中断；`ISOLATE_ALERT` 隔离告警 |
| 触发 | 监督引擎周期采集；越线按策略执行 |
| 硬中断 | 通过 Tool Broker 调用 Kill；冻结写入；保留快照与日志；进入失败诊断 |
| 禁止 | 不自动跳过审批；不自动跳过质量门禁；不自动重跑 |
| 记录 | 每次快照写 `runtime_supervision_snapshots`；决策与动作必须落库 |
| 对应 FR | FR-RUN-02、FR-RUN-05 |

### 11.4 QualityContract

| 字段 | 规格 |
|---|---|
| 规则类型 | 非空、正数、邮箱格式、枚举、范围、自定义表达式；以 PRD 列举为基础，不扩展未定义业务规则 |
| 字段级声明 | 字段、规则、阈值、错误码、处置方式（分流错误表/置空/拒绝） |
| 错误码 | `E-1001` 主键冲突、`E-2003` 手机号格式、`E-3001` 金额非正、`E-4004` 目标端超时等；错误码目录待确认 |
| 错误数据流向 | 错误表；记录错误码、字段、脱敏值、原因、处置；不阻断有效行 |
| 错误样本 | 必须脱敏；不得展示原始值 |
| 质量报告 | 有效写入、错误行、错误率、质量分、规则命中、错误码分布 |
| 通过条件 | 契约规则全部满足且质量分达阈值；阈值来自契约，待确认 P-14 |
| 失败处理 | 不执行 Swap；保留影子表；进入诊断与运维 |
| 对应 FR | FR-RUN-03、FR-RUN-05 |

### 11.5 质量分流与原子发布

| 步骤 | 规则 |
|---|---|
| 1 | 有效数据写影子表 |
| 2 | 未命中规则的数据写专用错误表，打错误码 |
| 3 | 质量报告生成；展示有效写入、错误分流、错误码分布 |
| 4 | 质量通过且监督未硬中断，才允许 Swap |
| 5 | Swap 通过 Tool Broker 执行；Doris 示例 `REPLACE TABLE ... swap=true` |
| 6 | Swap 成功后正式表发布；记录 `swap.completed` |
| 7 | Swap 失败：正式表状态需验证；恢复策略待确认 |
| 禁止 | 控制面直接写正式表；未过质量门禁执行 Swap；错误行混入正式表 |

### 11.6 诊断

| 项 | 规格 |
|---|---|
| 输入 | 失败快照、错误堆栈、运行指标、SeaTunnel 状态、质量报告 |
| 输出 | 可解释根因、影响范围、修复建议、置信度 |
| 行为 | 只读；不自动修复；不自动重跑；不修改质量契约 |
| 展示 | 根因链、建议列表、证据引用；脱敏 |
| 失败运行 | 不可重入；安全重跑生成新 Run 并重新审批 |
| 对应 FR | FR-RUN-03、FR-RUN-05 |

### 11.7 异步可靠性

| 场景 | 规则 |
|---|---|
| 重复投递 | 消费者按 `execution_run_id + idempotency_key` 去重；Capability 单次消费 |
| 执行结果未知 | 标记 `UNKNOWN`；保留快照；人工诊断；不自动重放 |
| Worker 崩溃 | 任务重新投递；若 Capability 已消费，拒绝二次执行并进入诊断 |
| Redis 不可用 | Replay Guard fail-closed；不执行 |
| PostgreSQL 不可用 | Commit 整体失败；不签发可用执行 |
| Outbox 死信 | 告警；人工处理；不静默丢弃 |
| 检查点失败 | 告警；不删除已有证据 |

### 11.8 Benchmark 与安全进化

| 项 | 规格 |
|---|---|
| 分层 | L0 静态注入；L1 模拟故障；L2 真实链路/影子执行 |
| 数据集 | 版本化；具体字段结构与评分公式待确认 P-24 |
| 指标 | 生成准确率、Schema 覆盖率、P0/P1 拦截率、P50/P95/P99 延迟 |
| 执行 | 经 API-18 触发；评测任务异步；结果只追加；绑定代码版本与数据集版本 |
| 基线 | 冻结基线；不可修改；对比结果保留 |
| 安全进化 | 候选来自失败样本、回放差异、Benchmark；Checker 2 审查；不自动上线 |
| 灰度 | 小流量/影子开关；自动回滚阈值；紧急停用立即切回 0% 并保留证据 |
| 禁止 | L2 写正式表；候选绕过门禁；修改基线/阈值 |
| 对应 FR | FR-GOV-01、FR-GOV-02、FR-GOV-03、FR-GOV-04 |

## 12. 安全、审计与脱敏

### 12.1 安全控制

| 控制 | 规格 | 失败行为 | 对应 FR |
|---|---|---|---|
| 认证 | 用户认证鉴权；具体机制待确认 P-26 | 401 | PRD 2.8.1 |
| 项目隔离 | 所有资源按 `project_id` 隔离 | 403 | PRD 2.8.1 |
| RBAC | 5 类角色 + 职责槽；服务端判定 | 403 | PRD 2.8.2 |
| 自批拦截 | 申请人不得审批；身份比对 | 403 + 审计 | PRD 2.8.2、2.8.11 |
| 职责槽分离 | 数据/安全审批人不同且非申请人 | 409 + 审计 | PRD 2.8.2 |
| Secret | Vault KV v2；仅引用；Worker 物化 | 503；禁止回退明文 | PRD 2.8.1 |
| Capability | Ed25519；300s；单次；绑定声明 | 401/403/409/410 | PRD 2.8.4 |
| Replay Guard | 原子占位；fail-closed | 409/503 | PRD 2.8.4 |
| Tool Broker | 副作用唯一出口 | 403 | PRD 2.8.6 |
| Outbox | 原子落库；至少一次 | 503；不产生执行 | PRD 2.8.6 |
| Ledger | 只追加；哈希链；签名检查点 | 告警；阻断相关业务 | PRD 2.8.6 |
| 数据脱敏 | 样本、日志、错误表、HOCON 主机/账号 | 脱敏失败不展示 | PRD 2.8.11 |
| 控制面/数据面分离 | 控制面不搬运业务数据 | 拒绝 | PRD 2.8.4 |
| 输入校验 | 参数、文件、Prompt、HOCON | 422 | PRD 2.8.7 |
| 日志脱敏 | 禁止 Secret、令牌、密码、原始敏感值 | 丢弃敏感字段 | PRD 2.8.11 |

### 12.2 审计事件目录

| 事件类型 | 生产者 | 触发 | `payload_digest` 覆盖内容 | 对应 FR |
|---|---|---|---|---|
| `project.member.granted` | 认证鉴权服务 | 成员加入/授权 | `project_id`、`user_id`、`role` | 2.8.1/2.8.2 |
| `role.grant.changed` | 认证鉴权服务 | 职责槽变更 | `project_id`、`user_id`、`role_slot` | 2.8.2 |
| `connection.created` | 连接服务 | 创建连接 | `connection_id`、`type`、`env`、`secret_ref_digest` | FR-CONN-01 |
| `secret.ref.bound` | 连接服务 | 绑定 Secret 引用 | `connection_id`、`secret_ref_digest` | FR-CONN-01 |
| `connection.updated` | 连接服务 | 编辑连接 | `connection_id`、变更字段名、摘要 | FR-CONN-01 |
| `connection.tested` | 连接服务 | 连通性测试 | `connection_id`、结果、延迟 | FR-CONN-01 |
| `metadata.profile.requested` | 连接服务 | 发起探查 | `connection_id`、范围、采样上限 | FR-META-01/02 |
| `metadata.profile.completed` | 连接服务 | 探查完成 | `connection_id`、表数、字段数、脱敏策略 | FR-META-01/02 |
| `file.asset.uploaded` | 文件服务 | 文件上传 | `file_asset_id`、格式、大小、来源 | FR-FILE-01/02 |
| `file.asset.parsed` | 文件服务 | 解析/推断完成 | `file_asset_id`、字段数、置信度摘要 | FR-FILE-01/02 |
| `agent.run.started` | LangGraph | 生成开始 | `agent_run_id`、`version_id`、`thread_id`、Provider | FR-STUDIO-01/02 |
| `agent.run.interrupted` | LangGraph | 中断提问 | `agent_run_id`、问题摘要 | FR-STUDIO-02/06 |
| `agent.run.resumed` | LangGraph | Checkpoint 恢复 | `agent_run_id`、`thread_id`、回答摘要 | FR-STUDIO-02/06 |
| `gate.evaluated` | 门禁服务 | 确定性门禁 | `version_id`、4 项结果、摘要 | FR-STUDIO-07 |
| `pipeline.created` | Studio 服务 | 创建 Pipeline | `pipeline_id`、`project_id`、`code` | FR-STUDIO-01 |
| `version.frozen` | 版本服务 | 冻结版本 | `version_id`、`artifact_digest` | FR-STUDIO-04 |
| `preparation.created` | 审批服务 | 生成准备单 | `preparation_id`、`version_id`、指纹、预算、风险 | FR-RUN-01 |
| `preparation.failed` | 审批服务 | Prepare 失败 | `version_id`、失败码 | FR-RUN-01 |
| `pdp.decision.recorded` | PDP | 风险决策 | `risk_level`、`required_slots`、`policy_version` | FR-RUN-01 |
| `approval.slot.assigned` | 审批服务 | 分配职责槽 | `preparation_id`、`role_slot`、`approver_id` | FR-RUN-01 |
| `approval.decision.recorded` | 审批服务 | 审批决策 | `approval_id`、`decision`、`approver_id`、意见摘要 | FR-RUN-01 |
| `approval.validated` | 审批服务 | Commit 前审批校验 | `preparation_id`、`approval_ids`、校验摘要 | FR-RUN-01 |
| `approval.completed` | 审批服务 | 2/2 审批通过 | `preparation_id`、`approval_ids`、`approver_ids` | FR-RUN-01 |
| `approval.self_approval_blocked` | 审批服务 | 自批尝试 | `approval_id`、`actor_id`、拒绝码 | 2.8.2/2.8.11 |
| `approval.slot_conflict_blocked` | 审批服务 | 同人多槽尝试 | `approval_id`、`actor_id`、已占槽 | 2.8.2/2.8.11 |
| `approval.role_denied` | 审批服务 | 槽位未授权 | `approval_id`、`actor_id`、`role_slot` | 2.8.2/2.8.11 |
| `capability.issued` | Capability Issuer | 签发 | `jti`、`token_digest`、`exp`、`scope` | FR-RUN-01/02 |
| `capability.verified` | Capability Verifier | 验签 | `jti`、结果、绑定摘要 | FR-RUN-02 |
| `capability.consumed` | Replay Guard | 单次消费 | `jti`、`token_digest`、`execution_run_id` | FR-RUN-02 |
| `capability.rejected` | Verifier / Broker | 拒绝 | `jti`、拒绝码 | FR-RUN-02 |
| `replay.rejected` | Replay Guard | 重放 | `jti`/幂等键摘要、拒绝码 | FR-RUN-04/05 |
| `tool.call.authorized` | Tool Broker | 授权通过 | `tool`、`request_id`、Scope 摘要 | FR-RUN-02/04/05 |
| `tool.call.executed` | Tool Broker | 执行完成 | `tool`、`output_digest`、`external_ref` | FR-RUN-02/04/05 |
| `tool.call.rejected` | Tool Broker | 拒绝 | `tool`、拒绝码 | FR-RUN-02/04/05 |
| `run.committed` | 执行编排 | Commit | `execution_run_id`、`version_id`、`preparation_id` | FR-RUN-01/02 |
| `run.commit_failed` | 执行编排 | Commit 失败回滚 | `preparation_id`、失败码 | FR-RUN-01/02 |
| `outbox.event.created` | Outbox | 事件创建 | `event_id`、`aggregate_id`、`idempotency_key_digest` | FR-RUN-02 |
| `outbox.event.published` | Outbox | 派发 | `event_id`、`attempts` | FR-RUN-02 |
| `outbox.event.consumed` | Worker | 消费确认 | `event_id`、`execution_run_id` | FR-RUN-02 |
| `run.started` | Worker | 开始执行 | `execution_run_id`、`engine_job_id` | FR-RUN-02 |
| `run.succeeded` | Worker | 成功 | `execution_run_id`、指标摘要 | FR-RUN-02 |
| `run.failed` | Worker | 失败 | `execution_run_id`、失败码、快照引用 | FR-RUN-02/03 |
| `run.cancel_requested` | 运维服务 | 取消请求 | `execution_run_id`、`actor_id`、原因摘要 | FR-RUN-04 |
| `run.cancelled` | Worker | 取消 | `execution_run_id`、原因摘要 | FR-RUN-04 |
| `run.rollback_requested` | 运维服务 | 回滚请求 | `execution_run_id`、`actor_id`、原因摘要 | FR-RUN-04/05 |
| `run.rolled_back` | Worker | 回滚完成 | `execution_run_id`、清理范围、结果 | FR-RUN-04/05 |
| `run.cleaned` | Worker | 清理完成 | `execution_run_id`、清理范围、结果 | FR-RUN-05 |
| `supervision.warning` | 监督引擎 | 预警 | `execution_run_id`、指标、阈值 | FR-RUN-05 |
| `supervision.interrupted` | 监督引擎 | 硬中断 | `execution_run_id`、动作、快照引用 | FR-RUN-05 |
| `quality.report.generated` | 质量服务 | 质量报告 | `execution_run_id`、通过/预警、错误码分布摘要 | FR-RUN-03 |
| `swap.completed` | SeaTunnel 适配 | 原子 Swap | `execution_run_id`、目标表、结果 | FR-RUN-03 |
| `benchmark.run.started` | Benchmark 服务 | 评测开始 | `benchmark_run_id`、层、套件 | FR-GOV-01/03/04 |
| `benchmark.run.completed` | Benchmark 服务 | 评测完成 | `benchmark_run_id`、层、套件、指标摘要 | FR-GOV-01/03/04 |
| `governance.candidate.reviewed` | 治理服务 | 候选审查 | `candidate_id`、结论、审查人 | FR-GOV-02 |
| `governance.gray.changed` | 治理服务 | 灰度变更 | `candidate_id`、比例、操作人 | FR-GOV-02 |
| `ledger.checkpoint` | Ledger | 签名检查点 | `last_sequence`、`event_hash`、签名摘要 | FR-RUN-05 |
| `ledger.verify_failed` | Ledger | 链验证失败 | `expected_hash`、`actual_hash`、位置 | FR-RUN-05 |
| `secret.materialized` | SecretProvider 适配 | Worker 物化 | `secret_ref_digest`、`execution_run_id`、租约 | FR-RUN-02 |
| `secret.access_denied` | SecretProvider 适配 | 拒绝访问 | `secret_ref_digest`、拒绝码 | FR-RUN-02 |

### 12.3 脱敏规则

| 数据类别 | 控制面展示 | 控制面存储 | 采样 | 禁止 |
|---|---|---|---|---|
| 手机号 | `138****6621` | 不存原值 | 可采样，必须掩码 | 明文、可逆还原 |
| 邮箱 | `z***@example.com` | 不存原值 | 可采样，必须掩码 | 明文、导出 |
| 姓名 | 掩码或首字 | 不存原值 | 按策略 | 明文 |
| 证件号 | `****` | 不存原值 | P0 禁止采样 | 明文 |
| Secret / 密码 | 仅保存状态与引用摘要 | Vault 密文 | 不适用 | 明文、回传、日志 |
| Capability | 仅摘要 | 仅 `token_digest`/`jti` | 不适用 | 明文、回传、日志 |
| 主机 / JDBC URL | `10.20.*.*` | 连接配置中受管 | 不适用 | 完整凭据、密码 |
| 错误样本 | 脱敏值 | 错误表在数据面 | 可展示脱敏样本 | 原始值 |
| Prompt | 脱敏后展示 | 需扫描敏感信息 | 不适用 | Secret、密码、原始样本 |
| 文件头 | 脱敏预览 | 仅元数据与推断结果 | 可展示脱敏 | 原文件内容落控制面 |

### 12.4 禁止项清单

| 禁止项 | 检测点 |
|---|---|
| Secret 明文、密码明文 | API 请求/响应、日志、数据库、Prompt、HOCON |
| 敏感样本明文 | 元数据探查、文件头、错误表、诊断报告 |
| 申请人自批 | 审批决策 |
| 同一人占多个审批职责槽 | Preparation 分配、审批决策 |
| 绕过审批直接执行 | Commit、Tool Broker |
| 绕过 Harness 调用 SeaTunnel / Vault | 路由层、服务层、静态扫描 |
| 控制面直连搬运海量业务数据 | 路由层、Worker、SQL 审计 |
| Capability 明文回传或落库 | Commit 响应、日志、数据库 |
| 修改/删除审计事件 | 数据库权限、应用层 |
| 未过质量门禁执行 Swap | 执行编排、Tool Broker |
| 失败运行直接重入 | Worker、运维接口 |

## 13. 异常、取消与回滚

### 13.1 错误分类

| 阶段 | 错误码 | HTTP | 可重试 | 状态影响 | 审计 |
|---|---|---|---|---|---|
| 认证 | `AUTH-401` | 401 | 否 | 无 | 安全事件 |
| 授权 | `AUTH-403`、`ROLE-403` | 403 | 否 | 无 | 拒绝事件 |
| 连接 | `CONN-409`、`CONN-422`、`CONN-503`、`CONN-504` | 409/422/503/504 | 503/504 可重试 | 连接状态不变 | `connection.tested` |
| 元数据 | `META-403`、`META-422`、`META-503` | 403/422/503 | 503 可重试 | 探查失败 | `metadata.profile.*` |
| 文件 | `FILE-413`、`FILE-422`、`FILE-503` | 413/422/503 | 503 可重试 | 资产解析失败 | `file.asset.parse_failed` |
| 生成 | `GEN-409`、`GEN-422`、`GEN-503`、`GEN-504` | 409/422/503/504 | 503/504 可重试 | Agent 运行失败/中断 | `agent.run.failed` |
| 门禁 | `GATE-422` | 422 | 否 | 禁止冻结 | `gate.evaluated` |
| 版本 | `VER-409`、`VER-422` | 409/422 | 否 | 冻结/提交拒绝 | `version.frozen` |
| 准备 | `PREP-409`、`PREP-422` | 409/422 | 否 | 不生成准备单 | `preparation.failed` |
| 审批 | `APR-403`、`APR-409`、`APR-422` | 403/409/422 | 否 | 决策拒绝/流程终止 | `approval.*` |
| Commit | `CMT-403`、`CMT-409`、`CMT-503` | 403/409/503 | 503 可重试 | 不产生执行 | `run.commit_failed` |
| Capability | `CAP-401`、`CAP-403`、`CAP-409`、`CAP-410`、`CAP-422`、`CAP-500` | 401/403/409/410/422/500 | 否 | 执行拒绝 | `capability.rejected` |
| 重放 | `RG-409`、`RG-410`、`RG-422`、`RG-503` | 409/410/422/503 | 否 | 执行拒绝 | `replay.rejected` |
| Broker | `TB-400`、`TB-403`、`TB-409`、`TB-424`、`TB-503`、`TB-504` | 400/403/409/424/503/504 | 503/504 可重试 | 工具失败 | `tool.call.rejected` |
| Outbox | `OBX-409`、`OBX-422`、`OBX-500`、`OBX-503`、`OBX-410` | 409/422/500/503/410 | 503 可重试 | 投递失败/死信 | `outbox.event.failed` |
| 执行 | `EXE-409`、`EXE-410`、`EXE-503`、`EXE-504` | 409/410/503/504 | 否/视情况 | 失败/未知 | `run.failed` |
| 监督 | `SUP-409`、`SUP-422`、`SUP-503` | 409/422/503 | 否 | 预警/硬中断 | `supervision.*` |
| 运维 | `OPS-403`、`OPS-409`、`OPS-422`、`OPS-503` | 403/409/422/503 | 否 | 操作拒绝 | `run.rollback_requested` |
| Benchmark | `BENCH-403`、`BENCH-409`、`BENCH-422`、`BENCH-503` | 403/409/422/503 | 503 可重试 | 评测失败 | `benchmark.run.*` |
| Ledger | `EL-409`、`EL-422`、`EL-500`、`EL-410` | 409/422/500/410 | 否 | 写链失败/断链 | `ledger.*` |

### 13.2 取消运行

| 步骤 | 规格 |
|---|---|
| 1 | Ops 在 `/runs/operations` 或 `/runs/executions` 发起取消 |
| 2 | 服务端校验角色、项目、环境、Run 状态；终态拒绝 |
| 3 | 生成幂等键；写 `run.cancel_requested` |
| 4 | 经 Tool Broker 调用 `run.cancel`；Broker 校验授权与 Replay Guard |
| 5 | Worker 调用 SeaTunnel Kill；保留快照、日志、错误表 |
| 6 | 状态置 `CANCELLED`；写 `run.cancelled` |
| 7 | 不自动清理；清理需单独运维操作 |
| 禁止 | 不为取消签发执行 Capability；不直接调用 SeaTunnel；不删除证据 |

### 13.3 安全重跑

| 步骤 | 规格 |
|---|---|
| 1 | 仅 Ops 可发起；使用同一不可变版本 SHA |
| 2 | 创建新的 Preparation；重新走 PDP、审批、Commit |
| 3 | 不复用失败 Run 的 Capability；不复用失败 Run 的 ExecutionRun |
| 4 | 新 Run 必须有独立 ID、独立影子表、独立证据 |
| 5 | 重跑接口 PRD 未定义，待确认 P-20 |
| 禁止 | 失败运行直接重入；跳过审批；复用已消费令牌 |

### 13.4 回滚影子表

| 步骤 | 规格 |
|---|---|
| 1 | 仅 Ops；仅 `FAILED` / `CANCELLED` 运行 |
| 2 | 二次确认；原因必填；输入 `ROLLBACK` 确认词 |
| 3 | 服务端校验：角色 + Scope、环境、Run 归属、影子表归属、正式表未被修改 |
| 4 | 生成幂等键；Replay Guard 防重放 |
| 5 | 经 Tool Broker 调用 `shadow.rollback`；只清理本 Run 影子表与临时资源 |
| 6 | 写 `run.rollback_requested`、`run.rolled_back`；保留 Ledger |
| 7 | 正式表与历史分区零变更 |
| 禁止 | 回滚正式表；跨 Run 清理；无原因执行；自动降级权限 |
| 未定义 | Swap 后回滚、部分 Swap 失败恢复，待确认 P-29 |

### 13.5 清理资源

| 项 | 规格 |
|---|---|
| 范围 | Worker、临时目录、隔离快照、本 Run 影子表残留 |
| 前提 | 运行已终止；归属校验通过；不删除 Ledger |
| 幂等 | 同一 Run 重复清理幂等 |
| 审计 | `run.cleaned` |
| 接口 | PRD 未定义，待确认 P-20 |

### 13.6 部分失败与未知结果

| 场景 | 实际状态 | 处理 |
|---|---|---|
| Capability 已消费、SeaTunnel 提交失败 | 令牌不可复用；Run 失败 | 诊断；安全重跑需新审批 |
| SeaTunnel 已提交、Worker 失联 | 结果未知 | 标记 `UNKNOWN`；查询 Job 状态；不自动重放 |
| 影子表部分写入 | 正式表未变 | 保留影子表；质量不通过；回滚或诊断 |
| 质量通过、Swap 失败 | 正式表状态需验证 | 不标记成功；人工诊断；待确认 P-29 |
| Outbox 重复投递 | 已消费 | 幂等拒绝；不重复执行 |
| Ledger 写入失败 | 业务事实可能已存在 | 阻断后续或标记补偿；不得静默 |

### 13.7 幂等与重放矩阵

| 操作 | 幂等键 | 重放保护 | 重复结果 |
|---|---|---|---|
| Create Connection | `Idempotency-Key` | 业务唯一键 | 返回首次结果或 409 |
| Test Connection | 无强制 | 可重复 | 允许重复测试 |
| Profile | 连接 + 范围 | 任务去重 | 返回进行中/首次结果 |
| File Upload | `Idempotency-Key` | 业务键待确认 | 返回首次结果 |
| Generation | `Idempotency-Key` | thread 并发锁 | 拒绝并发 |
| Answers | `run_id + question` | 状态机 | 幂等返回 |
| Prepare | `version + fingerprint` | 唯一约束 | 返回同一 Preparation |
| Approval | `approval_id + actor` | 决策唯一 | 已决策 409 |
| Commit | `preparation_id + Idempotency-Key` | Capability + 唯一 Run | 返回同一 Run；换键 409 |
| Cancel | `run_id` | 状态机 | 幂等 |
| Rollback | `run_id + Idempotency-Key` | Replay Guard | 幂等；重复拒绝或返回首次结果 |
| Cleanup | `run_id` | 状态机 | 幂等 |
| Benchmark | `Idempotency-Key` | 并发锁 | 返回首次结果 |

## 14. 验收标准映射

### 14.1 PRD 第 10 节 9 条验收

| # | PRD 验收标准 | 规格落点 | 页面 | 接口 | 数据 / 组件 | 验收证据 | FR |
|---|---|---|---|---|---|---|---|
| 1 | 项目内可配置独立的数据工程师、数据审批人与安全审批人；系统强制拦截申请人自批与职责混用 | 2.2、2.3、2.4、8.2、8.8 | 06、09 | API-13 | `project_memberships`、`project_role_grants`、`approval_requests`；审批服务 | 自批返回 `APR-403`；职责槽冲突返回 `APR-409`；审计事件存在 | FR-RUN-01 |
| 2 | 接入异构数据库与文件数据源，完成安全元数据探查并展示脱敏样本，全链路无敏感明文泄露 | 6.3、6.4、6.5、8.3、8.4、12.3 | 02、03、04 | API-02 至 API-07 | 连接/Profile 持久化待确认；`file_assets`；连接服务 | 5 类数据库 + 6 类文件/API；样本掩码；响应/日志无明文 | FR-CONN-01/02、FR-META-01/02、FR-FILE-01/02 |
| 3 | 自然语言触发 LangGraph 生成 EtlPlan 与 SeaTunnel HOCON；缺少参数时正确中断与恢复 | 6.6、8.5、9.2 | 05 | API-09、API-10、API-11 | `agent_runs`、`pipeline_versions`；LangGraph | 中断问题、回答、Checkpoint 恢复、有限修复记录 | FR-STUDIO-01/02/05/06/07 |
| 4 | 确定性门禁校验语法与 Schema；通过后生成不可变版本摘要 | 4.2、6.6、8.6 | 05 | API-11、API-12（冻结接口待确认） | `pipeline_versions.artifact_digest`、`is_immutable`；门禁服务 | 4/4 门禁结果；SHA256；冻结后不可修改 | FR-STUDIO-03/04/07 |
| 5 | 完整执行 prepare → approve → commit；生成准备单、完成四眼审批并签发单次 Capability | 4、5.1、5.5 | 06、11（原型） | API-12、API-13、API-14 | `approval_requests`、`execution_runs`；PDP、Capability、Outbox | 2/2 审批；独立审批人；Capability TTL 300s；单次消费 | FR-RUN-01/02 |
| 6 | Celery Worker 调度 SeaTunnel 完成搬运；有效数据写影子表，错误数据质量分流 | 8.10、11.4、11.5、11.7 | 07、08 | API-14、API-15 | `execution_runs`、`runtime_supervision_snapshots`；Worker、SeaTunnel 适配 | SeaTunnel Job ID；有效/错误行数；错误表错误码 | FR-RUN-02/03 |
| 7 | 数据达标后原子 Swap 发布正式表；运行中心查看实时指标与质量报告 | 6.8、6.9、11.5 | 07、08 | API-15 | `execution_runs`；质量服务、SeaTunnel 适配 | 质量通过；Swap 事件；指标与报告 | FR-RUN-02/03 |
| 8 | 超预算或异常触发运行时监督与可解释根因诊断；支持受管回滚 | 6.9、6.10、11.3、11.6、13.4 | 08、09 | API-15、API-16、API-17 | `runtime_supervision_snapshots`、`audit_events`；监督/诊断 | 预警/硬中断快照；根因链；回滚 3/3 校验；正式表零变更 | FR-RUN-04/05 |
| 9 | 运行自动化 Benchmark 评测集，输出准确率与安全拦截率报告 | 6.11、11.8、8.13 | 10 | API-18 | Benchmark 持久化待确认；Benchmark 服务 | L0/L1/L2 结果；准确率、覆盖率、拦截率、延迟 | FR-GOV-01/03/04 |

### 14.2 Harness 相关验收（单列）

| ID | 验收项 | 规格落点 | 验收证据 | 对应 FR |
|---|---|---|---|---|
| H-01 | PDP 对 ToolIntent 输出 P0-P3 风险与审批要求，策略拒绝即失败 | 3.4 | `pdp.decision.recorded`；拒绝码 `PDP-*` | FR-RUN-01 |
| H-02 | Capability 由 Ed25519 签发，绑定工具、主体、环境、制品指纹，TTL 300 秒 | 3.5、5.1 | `capability.issued`；claims 校验；过期拒绝 `CAP-410` | FR-RUN-01/02 |
| H-03 | Capability 只能消费一次，重复出示被拒绝且无副作用 | 3.7、5.2、5.5 | `replay.rejected`；`RG-409`；执行次数为 0 | FR-RUN-02 |
| H-04 | 所有副作用执行经 Tool Broker；FastAPI/Uvicorn 无绕过路径 | 3.1、3.2、8.15 | 路由/服务静态检查；`tool.call.*` 审计；绕过测试失败 | FR-RUN-02/04/05 |
| H-05 | Commit 在同一 PostgreSQL 事务原子创建 ExecutionRun 与 Outbox 命令 | 4.4、5.3 | 事务失败无残留；`run.committed` 与 `outbox.event.created` 同事务 | FR-RUN-02 |
| H-06 | Outbox 至少一次投递，消费者幂等，状态只前进 | 5.3.1、11.7 | 重复投递不重复执行；死信记录 | FR-RUN-02 |
| H-07 | Evidence Ledger 只追加、哈希链连续、签名检查点可验证 | 3.9、5.4 | 链验证通过；篡改检测 `ledger.verify_failed` | FR-RUN-03/05 |
| H-08 | 申请人自批与职责槽混用被服务端拦截 | 2.4、8.8 | `APR-403`、`APR-409`；按钮禁用仅作辅助 | FR-RUN-01 |
| H-09 | 控制面不直连搬运海量业务数据；Secret 与敏感样本无明文 | 3.1、8.15、12.3 | 网络/依赖扫描；响应与日志抽检；数据面 Job 执行 | FR-META-02、FR-RUN-02 |
| H-10 | 失败运行不可重入；安全重跑复用冻结版本但重新审批 | 4.7、13.3 | 新 Run、新 Preparation、新审批；旧 Capability 不复用 | FR-RUN-04/05 |

## 15. 待确认事项

| ID | 类别 | 待确认内容 | 影响 | 处理约束 |
|---|---|---|---|---|
| P-01 | 原型 | 页面地图列出的“11 安全进化管理”无对应画板；原型实际为 00-12 共 13 个页面画板 | 安全进化页面无法按原型实现 | 需补充画板或明确复用 Benchmark 页；不得臆造布局 |
| P-02 | 原型 | 侧栏“审计与证据”仅占位，无路由、布局、组件 | 审计人员核心视图缺失 | 需确认路由与页面；接口见 P-21 |
| P-03 | 原型 | 12 屏验收文本与 PRD 第 10 节不一致 | 验收口径冲突 | 以 PRD 第 10 节为准；原型验收画板不纳入基线 |
| P-04 | 数据模型 | 连接配置、元数据 Profile、采样结果无持久化表 | 连接与探查无法落地 | PRD 7.1 未定义；不得临时新增表；需确认 |
| P-05 | 数据模型 | Preparation 无持久化表；`approval_requests.preparation_id` 无对应表 | Prepare/Approve/Commit 链路无法完整持久化 | 需确认表或冻结事实承载方式 |
| P-06 | 数据模型 | Outbox 无持久化表 | Commit 原子投递无法完整实现 | 需确认物理载体；确认前视为实现阻塞 |
| P-07 | 数据模型 | Capability 消费记录/JTI 无独立表 | 单次消费与重放审计不完整 | 可用 `execution_runs.capability_token_digest` 部分承载；需确认 |
| P-08 | 数据模型 | Benchmark 结果、数据集版本、安全进化候选、灰度状态无表 | FR-GOV 无法落地 | 需确认持久化方案 |
| P-09 | 数据模型 | `audit_events` 无链序字段；`created_at` 不能保证唯一顺序 | 哈希链可能无法稳定验证 | 需确认序号字段或链序生成方式 |
| P-10 | 数据模型 | `approval_requests` 无申请人字段 | 自批校验缺少直接依据 | 需确认申请人来源；不得前端传入作为唯一依据 |
| P-11 | 业务规则 | 数据审批与安全审批是串行还是并行 | 影响状态机与页面按钮 | 原型标注串行；PRD 未规定；确认前只校验 2/2，不硬编码顺序 |
| P-12 | 业务规则 | 审批有效期、驳回后重审、准备单失效条件 | 影响状态机与清理 | PRD 未定义；不得擅自增加过期状态 |
| P-13 | 业务规则 | PDP P0-P3 的业务含义与各等级审批差异 | 影响风险决策与审批槽 | PRD 未定义；不得降低四眼原则 |
| P-14 | 业务规则 | QualityContract 与 RuntimeSupervisionContract 的默认阈值、质量分公式 | 影响质量判定与监督动作 | 原型数值仅为演示；需项目策略确认 |
| P-15 | 业务规则 | 文件单文件大小上限（原型示意 200MB） | 影响上传校验 | PRD 未定义；不得作为硬需求 |
| P-16 | 前端 | 执行状态采用轮询还是订阅；周期/通道 | 影响运行中心实现 | PRD 第 12 节列为待确认；前端不得自行定稿 |
| P-17 | 技术 | 多模型 Provider 默认选择、切换策略、降级策略 | 影响生成稳定性 | PRD 未定义；需确认 |
| P-18 | 接口 | PipelineVersion 创建、列表、历史、冻结、门禁结果查询接口 | Studio 冻结与提交无法完整实现 | PRD 第 8 节未定义；不得新增路径；需确认 |
| P-19 | 接口 | 总览聚合、连接详情、Profile 读取、文件列表/状态、Preparation/审批列表与详情、ExecutionRun 列表 | 多个页面数据来源缺失 | 需确认；不得前端拼装海量数据 |
| P-20 | 接口 | 安全重跑、清理资源、回滚预览、诊断导出、操作审计查询 | 运维页部分动作无法实现 | 需确认 |
| P-21 | 接口 | 审计事件、Evidence Ledger 查询与链验证接口 | 审计页无法实现 | 需确认；只读、禁止修改 |
| P-22 | 接口/页面 | 项目成员与角色分配接口与页面 | PRD In Scope 但无接口/页面 | 需确认；不得新增角色 |
| P-23 | 接口 | 实时日志流接口 | 执行监控实时日志无法实现 | 需确认轮询或流式方案 |
| P-24 | 接口/评测 | Benchmark 历史、结果详情、导出、候选审查、灰度开关、紧急停用接口；数据集字段与评分公式 | 治理页无法完整实现 | PRD 未定义；需确认 |
| P-25 | 安全 | SecretProvider / Vault KV v2 部署、轮换周期、租约 | 凭据安全与轮换无法验收 | PRD 第 12 节列为待确认 |
| P-26 | 安全 | 用户认证机制、会话/令牌、登出、密码策略 | 认证鉴权无法实现 | PRD 仅要求认证鉴权；需确认 |
| P-27 | 接口 | `GET /health` 是否公开、是否暴露组件细节 | 安全暴露面 | 需确认 |
| P-28 | 部署 | PostgreSQL/Redis 版本与部署拓扑；Celery 并发与队列 | 运行与容量规划 | PRD 第 12 节列为待确认 |
| P-29 | 业务规则 | Swap 成功后是否允许回滚；Swap 部分失败的恢复 | 回滚边界不清 | PRD 仅定义影子表回滚；确认前不得回滚正式表 |
| P-30 | 数据治理 | 审计、执行指标、Agent 运行、文件元数据保留期限与删除策略 | 合规与存储 | PRD 未定义；需确认 |
| P-31 | 安全 | Capability 编码格式与 Ed25519 密钥生命周期 | 签发/验签实现 | 需确认；私钥不得入库/入日志 |
| P-32 | 安全 | Ledger 链范围（项目级/全局）与检查点频率 | 哈希链实现 | 需确认；不得以时间戳替代链序 |
| P-33 | 架构 | 只读受管工具与运维工具是否也需要 Capability | Tool Broker 授权模型 | PRD 仅定义执行 Capability；确认前按“权限 + PDP + Replay Guard”执行，不扩展令牌类型 |
| P-34 | 前端 | UI 组件库、状态管理库、HTTP 客户端、图表库 | 前端实现 | 不得因选型改变接口契约 |
| P-35 | 数据模型 | `pipelines.status`、`execution_runs.status`、`agent_runs.status` 的合法枚举 | 状态机与数据库约束 | PRD 未给枚举；需确认 |
| P-36 | 审计 | 审批意见、诊断报告、操作原因的保留与脱敏级别 | 审计合规 | 需确认；不得保存原始敏感值 |
