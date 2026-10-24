# Harness 内核实现记录

- 日期：2026-10-23
- 范围：Spec 3.4～3.9 / 5.1～5.4 的本地内核
- 状态：本地实现与测试完成，**未接入 API**；API-05/06/07/12/14/16/17/18 仍按既有口径返回 503

## 一、实现边界

本次实现的目标是建立可执行的 Harness 内核，验证组件状态机、授权链和失败关闭行为。以下事项明确不在本次范围：

- 不接入 API 路由，不改变 8 个 Harness 接口的 503 口径。
- 不建 Outbox、Capability 消费记录、Preparation 等契约未定义表。
- 不连接 PostgreSQL、Redis、Vault、SeaTunnel 或对象存储。
- 不宣称 Commit 的数据库原子性、持久化单次消费或生产级 Ledger。
- 不新增契约接口、字段、角色或公开错误码。

## 二、组件与文件

| 组件 | 文件 | 关键行为 |
|---|---|---|
| 错误类型 | `app/core/harness/errors.py` | 统一 `HarnessError`，包含状态码、内部错误码、消息与 `details` |
| 共享模型 | `app/core/harness/models.py` | 工具注册表、P0-P3 临时策略、时钟、摘要校验、Secret 明文拒绝 |
| PDP | `app/core/harness/pdp.py` | 意图校验、风险等级、审批槽、预算校验、决策摘要、Preparation 绑定；策略异常 fail closed |
| Capability | `app/core/harness/capability.py` | Ed25519 紧凑令牌、TTL、jti/token_digest、签名/Scope/绑定/单次消费校验、双人审批与自批拒绝 |
| Replay Guard | `app/core/harness/replay.py` | 内存原子占位、作用域绑定、TTL、重复/过期/缺失/不可用错误 |
| Tool Broker | `app/core/harness/broker.py` | 工具注册、PDP 决策摘要复核、Capability、Replay、处理器执行、结果摘要、外部引用脱敏 |
| Outbox | `app/core/harness/outbox.py` | PENDING/PUBLISHED/RETRYING/CONSUMED/DEAD_LETTER、租约、过期租约接管、重复事件拒绝 |
| Evidence Ledger | `app/core/harness/ledger.py` | 按项目哈希链、链验证、载荷摘要、Ed25519 检查点 |
| 内核组合 | `app/core/harness/kernel.py` | 组合上述组件，记录 PDP、Capability、Tool、Outbox 审计事件 |
| 内存适配器 | `app/adapters/memory/harness.py` | 实现 HarnessPort 的本地适配器；**未注入 API** |

## 三、关键安全与一致性处理

### PDP 决策不能被伪造

Tool Broker 不信任调用方传入的决策对象。它要求 `decision_digest`，回到 PDP 的决策记录中查找原始决策，并逐项比较 `tool`、`actor_id`、`project_id`、`environment`、`resource_scope`、`artifact_digest`。未登记摘要、伪造摘要、作用域不一致均返回 `TB-403`。

PDP 的硬拒绝和执行类工具的四眼最低要求不能被评估器覆盖；评估器异常返回 `PDP-500`，不会降级为放行。

### Capability 单次消费

- 签发时校验 `jti`、主体、项目、环境、工具、资源范围、制品摘要、Preparation、ExecutionRun。
- 服务端只保留 `jti` 与 `token_digest`，令牌只返回一次，不写入日志或 Ledger。
- TTL 默认 300 秒；到达 `exp` 即过期。
- 验证时区分 Scope 不匹配（`CAP-403`）与绑定声明不匹配（`CAP-422`）。
- 要求两个不同的已批准审批人；如审批事实带审批槽，还要求至少两个不同槽位；内核按工具规格要求覆盖 `data_checker`/`security_checker` 槽位；申请人自批返回 `CAP-422`。
- 已消费、已过期、重复展示均拒绝。

### Replay 与 Broker

- Capability 使用 `capability:{jti}:{token_digest}` 作为 Replay 键。
- 运维工具使用工具、主体和幂等键组成 Replay 键。
- 先占位、后执行；执行结果未知时不回滚占位。
- Broker 先校验 PDP，再检查处理器是否存在，随后消费 Capability/Replay；失败关闭。
- 超时返回 `UNKNOWN`、`TB-504`，避免把可能已发生的副作用报告为干净失败。
- 工具输出只返回摘要；`external_ref` 如检测到凭据材料则丢弃，不返回原文。

### Outbox 与 Ledger

- Outbox 在内存中维护状态机与派发租约；过期租约允许新派发者接管，旧租约随后无法发布。
- 重复事件 ID 或重复幂等键返回 `OBX-409`；非法载荷返回 `OBX-422`。
- Ledger 按项目分链，事件只保存载荷摘要；链验证使用 Spec 规定的规范化哈希输入。
- 检查点对 `{last_sequence, last_event_hash, checkpoint_at}` 做 Ed25519 签名；检查点频率未定，按需生成。
- 私钥由进程启动时临时生成，不落库、不写日志。

## 四、测试结果

执行命令：

```bash
cd backendpoint
python -m pytest tests/test_harness.py -o addopts= -q
python -m pytest -o addopts= -q
```

结果：

| 项目 | 结果 |
|---|---|
| Harness 内核测试 | **35 passed** |
| 全量后端测试 | **134 passed，0 failed，4.88s** |
| 测试方式 | 固定时钟、确定性 Ed25519 密钥、内存适配器；不连接外部服务 |

覆盖范围包括：

- PDP 的正常决策、非法意图、缺失资源范围、工具白名单、制品摘要、预算、硬拒绝、评估器异常与四眼下限。
- Capability 的签发、验证、消费、签名篡改、Scope/绑定不匹配、过期边界、重复消费、双审批人、自批和 Secret 明文拒绝。
- Replay 的占位、作用域冲突、过期、缺失键与不可用。
- Outbox 的正常流转、重试、死信、重复事件、载荷拒绝、过期租约拒绝与接管。
- Ledger 的哈希公式、链验证、篡改检测、检查点签名与检查点校验。
- Broker 的只读工具、未知工具、PDP 决策伪造、处理器缺失、Capability 单次消费、Replay 重复、依赖失败、超时、敏感 `external_ref` 拒绝。
- 内核端到端链路与 `InMemoryHarnessAdapter` 的 Port 包装。

## 五、未闭合事项

| 编号 | 未闭合内容 | 当前影响 |
|---|---|---|
| P-06 | Outbox 无持久化表 | 无法提供 Commit 事务原子性；内核不接入 API Commit |
| P-07 | Capability 消费记录/JTI 无独立表 | 单次消费只在进程内存有效，重启丢失 |
| P-09 | `audit_events` 无链序字段 | Ledger 序号只在内存有效，不能作为生产链序 |
| P-13 | P0-P3 业务语义与等级审批差异未定义 | 当前工具风险表是显式临时策略 |
| P-31 | Capability 编码与密钥生命周期未定 | 当前为本地 EdDSA 紧凑令牌和临时密钥；无轮换与信任分发 |
| P-32 | Ledger 链范围与检查点频率未定 | 当前按项目分链、按需检查点；无全局链和定时策略 |
| P-33 | 只读/运维工具是否也需要 Capability 未定 | 当前只对执行/高风险管理工具要求 Capability |

另外，内核尚未实现 Outbox 派发器、`capability.consumed`/`capability.rejected` 独立审计事件、Ledger 查询/链验证 API（P-21）和持久化重放窗口。上述缺口不影响本地状态机测试结论，但在接入 API 前必须补齐或由契约明确降级范围。

## 六、结论

Harness 内核的组件边界、状态机、授权链和失败关闭行为已在本地可执行并通过 35 项专项测试；全量后端测试 134 项通过。由于 P-06/P-07/P-09 未闭合，内核不接入 API，8 个 Harness 接口继续返回 503。本次交付不构成 Harness 业务成功路径或生产可靠投递的验收。
