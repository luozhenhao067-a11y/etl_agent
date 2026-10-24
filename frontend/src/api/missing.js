// 缺失接口适配层（Spec P-18 ~ P-24，契约第 10 章）。
// 以下能力在 PRD 第 8 节没有对应接口：前端不得聚合海量数据、不得自造接口替代。
// mock 开启时由 src/api/mock/missing.js 提供演示数据；mock 关闭时必须显式暴露
// “接口待确认”，页面据此渲染空态，不得显示错误页、不得伪造数据。
import { missingHandlers } from './mock/missing'
import { ApiError, CONTRACT_PENDING_CODE } from '@/utils/errors'

const MOCK_ENABLED = import.meta.env.VITE_USE_MOCK !== 'false'

function pending(op, note) {
  return new ApiError({
    httpStatus: 0,
    errorCode: CONTRACT_PENDING_CODE,
    message: `接口未定义（${note}）。前端不得自行聚合或自造实现。`,
    correlationId: null,
    details: { operation: op, spec: note },
  })
}

function call(op, note, ...args) {
  if (!MOCK_ENABLED) return Promise.reject(pending(op, note))
  const h = missingHandlers[op]
  if (!h) return Promise.reject(pending(op, note))
  return h(...args)
}

export const missingApi = {
  // P-19 总览聚合指标（/dashboard）
  dashboardAggregate: () => call('dashboard.aggregate', '待确认 P-19'),
  // P-19 探查结果读取（/connections/profiles）
  profileResults: (connectionId) => call('profiles.results', '待确认 P-19', connectionId),
  // P-19 文件资产列表 / 解析状态 / 推断结果（/assets/files）
  fileAssetsList: () => call('files.list', '待确认 P-19'),
  // P-18 Pipeline 版本创建 / 列表 / 历史 / 冻结（/studio/:versionId）
  versionList: (pipelineId) => call('versions.list', '待确认 P-18', pipelineId),
  versionCreate: (pipelineId, body) => call('versions.create', '待确认 P-18', pipelineId, body),
  versionFreeze: (versionId) => call('versions.freeze', '待确认 P-18', versionId),
  versionHistory: (versionId) => call('versions.history', '待确认 P-18', versionId),
  // P-17 Provider 列表（/studio/:versionId）
  providerList: () => call('providers.list', '待确认 P-17'),
  // P-19 Preparation 列表 / 详情 / 审批请求列表（/runs/preparations）
  preparationList: () => call('preparations.list', '待确认 P-19'),
  preparationDetail: (id) => call('preparations.detail', '待确认 P-19', id),
  approvalList: () => call('approvals.list', '待确认 P-19'),
  // P-19 ExecutionRun 列表 / P-23 实时日志流（/runs/executions）
  executionList: () => call('executions.list', '待确认 P-19'),
  executionLogs: (runId, after) => call('executions.logs', '待确认 P-23', runId, after),
  // P-20 诊断导出（/runs/quality）
  diagnosisExport: (runId) => call('diagnosis.export', '待确认 P-20', runId),
  // P-20 安全重跑 / 清理 / 回滚预览 / 操作审计（/runs/operations）
  opsRerun: (runId, body) => call('ops.rerun', '待确认 P-20', runId, body),
  opsCleanup: (runId, body) => call('ops.cleanup', '待确认 P-20', runId, body),
  rollbackPreview: (runId) => call('ops.rollbackPreview', '待确认 P-20', runId),
  opsAudit: () => call('ops.audit', '待确认 P-20'),
  // P-24 Benchmark 历史 / 结果（/governance/benchmark）
  benchmarkHistory: () => call('benchmark.history', '待确认 P-24'),
  benchmarkResults: (runId) => call('benchmark.results', '待确认 P-24', runId),
  // P-24 安全进化候选 / 审查 / 灰度 / 停用（/governance/benchmark、/governance/evolution）
  governanceCandidates: () => call('governance.candidates', '待确认 P-24'),
  governanceReview: (candidateId, body) => call('governance.review', '待确认 P-24', candidateId, body),
  governanceGray: (candidateId, body) => call('governance.gray', '待确认 P-24', candidateId, body),
  governanceKillSwitch: () => call('governance.killSwitch', '待确认 P-24'),
  // P-21 审计事件 / 证据账本查询 / 链验证（审计与证据页）
  auditEvents: () => call('audit.events', '待确认 P-21'),
  ledgerVerify: (projectId) => call('audit.ledgerVerify', '待确认 P-21', projectId),
}
