# ETL-Agent 数据集成平台 · 前端（演示工程）

生产级 ETL-Agent 数据集成平台前端。以 [spec.md](../项目信息/spec.md)、[接口契约.md](../项目信息/接口契约.md)、[需求文档prd.txt](../项目信息/需求文档prd.txt) 与线框图为依据，可运行、可演示，并严格标注所有待确认项。

## 运行方式

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # 产物 dist/
npm run preview
```

- 默认 **mock 模式**：所有接口由 `src/api/mock/` 提供演示数据（已脱敏合成示例），无需后端即可完整演示。
- 连接真实后端：设置环境变量 `VITE_USE_MOCK=false`（后端地址代理见 `vite.config.js`，**后端地址待确认 P-28**，当前代理到 `http://localhost:8000`）。
- dev 内置 5 类演示角色（见下），顶栏可切换，用于验证 Spec 2.3 权限矩阵。

## 技术选型（均标注待确认）

| 项 | 当前实现 | 说明 |
| --- | --- | --- |
| 框架 | Vue 3（Composition API，`<script setup>`） | 已明确（PRD） |
| UI 组件库 | 手写 CSS（`src/styles/base.css`） | **待确认 P-34** |
| 状态管理 | 最小 reactive store（`src/stores/`） | **待确认 P-34**（未引入 Pinia） |
| HTTP 客户端 | 原生 fetch（`src/api/http.js`） | **待确认 P-34**（未引入 axios） |
| 图表 | 手写 SVG/CSS | **待确认 P-34**（未引入图表库） |
| 构建工具 | Vite | **待确认 P-34**（最小可用选型） |
| 路由 | vue-router 4 | 与 Vue 配套最小依赖 |

## 路由（固定 12 条，Spec 6.1，不增不减）

| 路由 | 页面 | 说明 |
| --- | --- | --- |
| `/dashboard` | 工作台总览 | Spec 6.2 |
| `/connections` | 连接管理 | Spec 6.3 |
| `/connections/profiles` | 元数据探查 | Spec 6.4 |
| `/assets/files` | 文件资产 | Spec 6.5 |
| `/studio/:versionId` | 生成 Studio | Spec 6.6-6.9 |
| `/runs/preparations` | 变更准备（审批） | Spec 6.10 |
| `/runs/executions` | 运行监控 | Spec 6.11 |
| `/runs/quality` | 质量诊断 | Spec 6.11 |
| `/runs/operations` | 运维操作 | Spec 6.12 |
| `/governance/benchmark` | 安全评测与进化 | Spec 6.14 |
| `/governance/evolution` | 安全进化（占位） | **原型缺失**（Spec 6.14） |
| `/audit` | 审计与证据（占位） | **路由路径待确认 P-21**（Spec 6.13） |

## 目录说明

```
frontend/
├─ index.html
├─ vite.config.js          # 代理 /api、/health（后端地址待确认 P-28）
├─ package.json
└─ src/
   ├─ main.js              # 入口：dev 自动登录 + 挂载
   ├─ App.vue
   ├─ router/index.js      # 12 条路由 + document.title
   ├─ layouts/AppLayout.vue# 侧边栏 / 顶栏 / 健康点(API-01) / 通知 / 认证门 / dev 角色切换
   ├─ pages/               # 12 个页面（每页顶部注释列出所用 API ID）
   ├─ components/          # 状态框 / 徽标 / 步骤条 / 审批卡 / HOCON 高亮 / DAG / Diff / 门禁 / 日志 / 确认弹窗 等
   ├─ api/
   │  ├─ http.js           # 统一封装：Authorization / X-Correlation-Id / Idempotency-Key / 统一错误解析
   │  ├─ health.js ~ benchmarks.js  # API-01 ~ API-18 的领域封装
   │  ├─ missing.js        # 缺失接口适配层（P-18~P-24），接口确认后替换
   │  └─ mock/
   │     ├─ index.js       # mock 注册 / 时延 / 统一信封 / 分页
   │     ├─ db.js          # 演示内存数据（全部脱敏合成）
   │     ├─ mockApi.js     # API-01~18 处理器（含服务端语义：权限/状态机/审批约束）
   │     └─ missing.js     # 缺失接口（P-17~P-24）演示处理器
   ├─ composables/
   │  ├─ useAuth.js        # 认证适配层（待确认 P-26）
   │  ├─ usePermission.js  # Spec 2.3 权限矩阵
   │  └─ useRunStatus.js   # 状态刷新适配层（待确认 P-16，轮询占位 3s）
   ├─ stores/              # auth / project / notice（最小 reactive）
   ├─ utils/               # errors（统一错误脱敏）/ mask / idem / time / status
   └─ styles/base.css      # 深色控制台设计令牌与组件样式
```

## 待确认清单（来自 Spec 附录）

| 编号 | 内容 | 当前处理 |
| --- | --- | --- |
| P-01 | 审计与证据页原型缺失 | `/audit` 空态占位 |
| P-16 | 执行状态刷新：轮询 vs 订阅 | `useRunStatus` 适配层，默认轮询占位（间隔 3s，仅演示），连续 2 次失败进入 log-disconnected 可重连 |
| P-17 | Provider 列表接口 | `src/api/mock/missing.js` 的 `providers.list` |
| P-18 | Pipeline 版本创建/列表/冻结/历史接口 | mock：`versions.create/list/freeze/history` |
| P-19 | 总览聚合、探查结果、文件列表、准备单/审批/执行列表接口 | mock：`dashboard.aggregate`、`profiles.results`、`files.list`、`preparations.list/detail`、`approvals.list`、`executions.list` |
| P-20 | 诊断导出、安全重跑、清理、回滚预览、操作审计接口 | mock：`diagnosis.export`、`ops.rerun/cleanup/rollbackPreview/audit` |
| P-21 | 审计与证据页路由路径与接口 | `/audit` 占位；mock：`audit.events`、`ledgerVerify` |
| P-22 | 项目选择 / 成员与角色分配接口 | 固定演示项目 `prj_demo_001` |
| P-23 | 实时日志流 | mock：`executions.logs`（游标轮询占位） |
| P-24 | 安全进化（候选/审查/灰度/停用）与评测历史/结果接口 | mock：`governance.*`、`benchmark.history/results` |
| P-26 | 登录页与认证机制 | dev 模拟登录 + 布局层认证门；令牌仅内存 |
| P-28 | 后端地址 | vite 代理默认 `http://localhost:8000` |
| P-34 | UI 库 / 状态管理 / HTTP 客户端 / 图表库 / 构建工具 | 见「技术选型」表 |
| P-35 | 状态枚举 | `src/utils/status.js` 展示层映射，注明待确认 |

## Mock 清单

**已定义接口（API-01 ~ API-18）的演示 mock**（`src/api/mock/mockApi.js`）：

- API-01 健康检查；API-02 连接列表（筛选/分页）；API-03 创建连接（CONN-409/422）；API-04 更新（类型不可变 CONN-422）；API-05 测试（幂等豁免；含 CONN-504 演示）；API-06 探查（目标端 META-422）；API-07 文件上传（FILE-422）；API-08 创建 Pipeline（META-409/422）；API-09 生成（冻结版本 VER-409、并发 GEN-409、澄清中断流）；API-10 回答（状态机 GEN-409/422，回答完毕产出设计）；API-11 设计读取（GEN-409，澄清问题经 409 details 返回）；API-12 准备单（未冻结 PREP-409、在途 PREP-409）；API-13 审批决策（自批 APR-403、职责槽 APR-403、不可变更 APR-409、状态重算）；API-14 Commit（非 Ops CMT-403、审批未完 CMT-409、指纹不符 CMT-409，响应仅三项）；API-15 运行状态（mock 内部状态机推进）；API-16 取消（OPS-403/409）；API-17 回滚（confirmation 校验 OPS-422、终态 OPS-409）；API-18 评测触发（BENCH-403/409/422）。

**缺失接口（Spec P-17 ~ P-24）的演示 mock**（`src/api/mock/missing.js`）：`dashboard.aggregate`、`profiles.results`、`files.list`、`versions.list/create/freeze/history`、`providers.list`、`preparations.list/detail`、`approvals.list`、`executions.list/logs`、`diagnosis.export`、`ops.rerun/cleanup/rollbackPreview/audit`、`benchmark.history/results`、`governance.candidates/review/gray/killSwitch`、`audit.events`、`ledgerVerify`。接口确认后替换 `src/api/missing.js` 对应函数即可，页面无需改动。

## 安全与合规要点（实现约定）

- 请求头：`Authorization`、`X-Correlation-Id` 始终携带；写接口带 `Idempotency-Key`（API-05 豁免；API-10 是否强制待确认）。
- 错误统一解析 `{error_code, message, correlation_id, details}`，按状态码脱敏提示；不渲染堆栈/主机/Secret/令牌/原始敏感样本。
- 掩码（Spec 12.3）：手机号 `138****6621`、邮箱 `z***@example.com`、主机 `10.20.*.*`、JDBC URL、姓名/证件号等；Secrets/密码/Capability/JTI/token_digest 不展示、不写日志、不进 localStorage（令牌仅内存）。
- 权限矩阵（Spec 2.3）控制按钮显隐：审批按钮按 `required_role` 与职责槽；申请人按钮禁用并提示「申请人禁止自批」；Commit/取消/重跑/回滚/清理仅 Ops；Auditor 全只读。**前端隐藏不构成安全边界**，服务端二次复核（mock 同样强制）。
- 无「跳过审批直接执行」「申请人自批」入口；无前端海量数据聚合（聚合指标来自服务端/mock 服务端）。
- 演示数值（200MB、2M 行、5%、10min、99.0 分等）不写成业务默认值，页面均有「演示数据」标注。
- 回滚需输入 `ROLLBACK` 且原因必填；Commit 成功仅展示 `execution_run_id` / `status` / `capability_digest`。

## dev 角色切换（演示）

顶栏可切换 5 类角色：张三（maker）、李四（checker1 / data_checker）、王五（checker2 / security_checker）、赵六（ops）、钱七（auditor）。用于演示权限矩阵；真实认证接入后替换 `stores/auth.js` 与 `composables/useAuth.js`（待确认 P-26）。
