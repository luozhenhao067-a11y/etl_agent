// 缺失接口（Spec P-17 ~ P-24）的演示 mock 处理器。
// 注意：这些不是真实契约接口。前端仅在 mock 模式下调它们渲染演示数据；
// 真实联调后由 src/api/missing.js 替换为正式封装。所有值均已脱敏。
import { useAuthStore } from '@/stores/auth'
import { db } from './db'
import { latency, ok, fail, paginate, nextId } from './index'

function caller() {
  return useAuthStore().state.user
}

function requireRole(roles, errorCode, message) {
  const u = caller()
  if (!u || !roles.includes(u.role)) throw fail(403, errorCode, message)
  return u
}

function findOr404(list, id, errorCode, resource) {
  const item = list.find((x) => x.id === id || x.connection_id === id || x.version_id === id || x.preparation_id === id || x.benchmark_run_id === id)
  if (!item) throw fail(404, errorCode, `${resource}不存在：${id}`)
  return item
}

// 统一包装：模拟时延 + 同步 fail 转 rejection
function wrap(fn) {
  return async (...args) => {
    await latency()
    const result = fn(...args)
    if (result === null || result === undefined) {
      throw fail(404, 'API-404', '缺失接口 mock 无匹配数据')
    }
    return result
  }
}

// ---- P-19 总览聚合（服务端聚合演示；前端页面不得自行聚合海量数据） ----
const dashboardAggregate = wrap(() => {
  const runs = db.runs
  const runningCount = runs.filter((r) => r.status === 'running').length
  const todayFailed = runs.filter((r) => r.status === 'failed').length
  const pendingApprovals = db.preparations.filter((p) => ['PREPARED', 'PARTIAL_APPROVED'].includes(p.status)).length
  const avgDurationMs = runs.filter((r) => r.finished_at).reduce((acc, r) => acc + (r.metrics.duration_seconds || 0), 0) / Math.max(1, runs.filter((r) => r.finished_at).length)
  return ok({
    summary: {
      active_connections: db.connections.filter((c) => c.status === 'active').length,
      connections_total: db.connections.length,
      versions_frozen: db.versions.filter((v) => v.is_immutable).length,
      preparations_total: db.preparations.length,
      running_runs: runningCount,
      runs_total: runs.length,
      today_failed_runs: todayFailed,
      pending_approvals: pendingApprovals,
      avg_duration_seconds: Math.round(avgDurationMs),
      benchmarks_completed: db.benchmarks.filter((b) => b.status === 'completed').length,
    },
    distribution: {
      connection_types: ['mysql', 'doris', 'postgresql', 'clickhouse', 'oracle', 'minio', 'rest_api'].map((t) => ({
        name: t,
        count: db.connections.filter((c) => c.type === t).length,
      })),
      run_status: ['queued', 'running', 'succeeded', 'failed', 'cancelled'].map((s) => ({
        name: s,
        count: runs.filter((r) => r.status === s).length,
      })),
    },
    pending_approval_items: db.preparations
      .filter((p) => ['PREPARED', 'PARTIAL_APPROVED'].includes(p.status))
      .map((p) => ({ preparation_id: p.preparation_id, version_id: p.version_id, status: p.status, risk_level: p.risk_level, created_at: p.created_at })),
    recent_runs: runs.slice(0, 5).map(({ _tick, ...r }) => r),
  })
})

// ---- P-19 探查结果读取 ----
const profileResults = wrap((connectionId) => {
  const profile = db.profiles[connectionId]
  if (!profile) {
    const conn = db.connections.find((c) => c.id === connectionId)
    if (!conn) throw fail(404, 'API-404', '连接不存在')
    return ok({ connection_id: connectionId, profile_status: 'none', sampled_at: null, stats: null, tables: [], columns: [], masked_samples: [] })
  }
  return ok({ connection_id: connectionId, ...profile })
})

// ---- P-19 文件资产列表 ----
const fileAssetsList = wrap(() => ok({ items: db.files }))

// ---- P-18 版本列表 / 创建 / 冻结 / 历史 ----
const versionList = wrap((pipelineId) => {
  const list = pipelineId ? db.versions.filter((v) => v.pipeline_id === pipelineId) : db.versions
  return ok({ items: list })
})

const versionCreate = wrap((pipelineId, body = {}) => {
  requireRole(['maker'], 'ROLE-403', '仅数据工程师可创建版本')
  const pipeline = db.pipelines.find((p) => p.pipeline_id === pipelineId)
  if (!pipeline) throw fail(404, 'API-404', 'Pipeline 不存在')
  const maxNum = Math.max(0, ...db.versions.filter((v) => v.pipeline_id === pipelineId).map((v) => v.version_number))
  const version = {
    version_id: nextId('ver'),
    pipeline_id: pipelineId,
    version_number: maxNum + 1,
    status: 'draft',
    is_immutable: false,
    artifact_digest: null,
    frozen_at: null,
    source_profile_ref: body.source_profile_ref || null,
    target_profile_ref: body.target_profile_ref || null,
  }
  db.versions.push(version)
  return ok(version)
})

const versionFreeze = wrap((versionId) => {
  requireRole(['maker'], 'ROLE-403', '仅数据工程师可冻结版本')
  const version = findOr404(db.versions, versionId, 'API-404', '版本')
  if (version.is_immutable) throw fail(409, 'VER-409', '版本已冻结，冻结不可逆')
  version.status = 'frozen'
  version.is_immutable = true
  version.frozen_at = new Date().toISOString()
  version.artifact_digest = '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08'
  return ok(version)
})

const versionHistory = wrap((versionId) => {
  findOr404(db.versions, versionId, 'API-404', '版本')
  return ok({
    items: db.versions.map((v) => ({
      version_id: v.version_id,
      version_number: v.version_number,
      status: v.status,
      frozen_at: v.frozen_at,
      artifact_digest: v.artifact_digest,
    })),
  })
})

// ---- P-17 Provider 列表 ----
const providerList = wrap(() =>
  ok({
    items: [
      { provider_id: 'prov_demo_001', name: 'provider-internal', kind: 'llm', status: 'available' },
      { provider_id: 'prov_demo_002', name: 'provider-embedding', kind: 'embedding', status: 'available' },
    ],
  })
)

// ---- P-19 Preparation 列表 / 详情 / 审批请求列表 ----
const preparationList = wrap(() => ok({ items: db.preparations }))

const preparationDetail = wrap((id) => {
  const prep = findOr404(db.preparations, id, 'API-404', '准备单')
  return ok(prep)
})

const approvalList = wrap(() => {
  const items = db.preparations.flatMap((p) =>
    p.approval_requests.map((a) => ({
      approval_id: a.approval_id,
      preparation_id: p.preparation_id,
      version_id: p.version_id,
      required_role: a.required_role,
      status: a.status,
      decision: a.decision,
      decided_at: a.decided_at,
      applicant_id: p.applicant.id,
    }))
  )
  return ok({ items })
})

// ---- P-19 ExecutionRun 列表 / P-23 实时日志流 ----
const executionList = wrap((query = {}) => {
  let list = db.runs
  if (query.status) list = list.filter((r) => r.status === query.status)
  const page = Math.max(1, Number(query.page) || 1)
  const pageSize = Math.max(1, Number(query.page_size) || 10)
  return ok({
    items: paginate(list, page, pageSize),
  })
})

const executionLogs = wrap((runId, after = 0) => {
  const run = findOr404(db.runs, runId, 'API-404', '执行 Run')
  const from = Number(after) || 0
  const logs = run.recent_logs.slice(from)
  return ok({ items: logs, next_cursor: run.recent_logs.length, has_more: run.status === 'running' })
})

// ---- P-20 诊断导出 ----
const diagnosisExport = wrap((runId) => {
  const run = findOr404(db.runs, runId, 'API-404', '执行 Run')
  if (!run.diagnosis) throw fail(409, 'OPS-409', '仅失败 Run 有诊断报告')
  return ok({ export_id: nextId('export'), run_id: runId, status: 'ready', format: 'pdf', note: '演示导出任务；真实下载渠道待确认 P-20' })
})

// ---- P-20 安全重跑 / 清理 / 回滚预览 / 操作审计 ----
const opsRerun = wrap((runId, body = {}) => {
  requireRole(['ops'], 'OPS-403', '仅 Ops 可发起安全重跑')
  const run = findOr404(db.runs, runId, 'API-404', '执行 Run')
  if (!body.reason) throw fail(422, 'OPS-422', '重跑原因必填', { fields: { reason: '必填' } })
  const newRun = {
    id: nextId('run'),
    status: 'queued',
    engine_job_id: null,
    version_id: body.version_id || run.version_id,
    preparation_id: run.preparation_id,
    started_at: null,
    finished_at: null,
    metrics: { input_records: 0, output_records: 0, error_records: 0, bytes_processed: 0, duration_seconds: 0 },
    quality_report: null,
    supervision: null,
    stages: [
      { name: '派发', status: 'todo' },
      { name: '验签与单次消费', status: 'todo' },
      { name: '影子表写入', status: 'todo' },
      { name: '质量校验', status: 'todo' },
      { name: '原子 Swap', status: 'todo' },
    ],
    recent_logs: [],
    _tick: 0,
  }
  db.runs.unshift(newRun)
  db.opsHistory.unshift({ id: nextId('ops_evt'), run_id: runId, action: 'rerun', actor_id: caller().id, reason_digest: 'sha256:reason***', result: 'success', at: new Date().toISOString() })
  return ok({ execution_run_id: newRun.id, status: newRun.status, note: '安全重跑：复用冻结版本，需重新 Prepare / Approve / Commit（演示提示）' })
})

const opsCleanup = wrap((runId, body = {}) => {
  requireRole(['ops'], 'OPS-403', '仅 Ops 可执行清理')
  findOr404(db.runs, runId, 'API-404', '执行 Run')
  if (!body.reason) throw fail(422, 'OPS-422', '清理原因必填', { fields: { reason: '必填' } })
  db.opsHistory.unshift({ id: nextId('ops_evt'), run_id: runId, action: 'cleanup', actor_id: caller().id, reason_digest: 'sha256:reason***', result: 'success', at: new Date().toISOString() })
  return ok({ run_id: runId, status: 'cleaned', note: '仅清理本 Run 临时资源；错误表与影子表按保留策略处理（演示提示）' })
})

const rollbackPreview = wrap((runId) => {
  const run = findOr404(db.runs, runId, 'API-404', '执行 Run')
  return ok({
    run_id: runId,
    preview: {
      shadow_tables: ['orders_shadow_***'],
      error_tables: ['orders_err_***'],
      temp_resources: ['tmp_job_***'],
      target_formal_tables: ['orders'],
      steps: ['仅清理本 Run 影子表与临时资源', '正式表与历史分区零变更', '错误表保留取证'],
      limitation: 'Swap 后回滚未定义，待确认 P-29',
    },
  })
})

const opsAudit = wrap(() => ok({ items: db.opsHistory }))

// ---- P-24 Benchmark 历史 / 结果 ----
const benchmarkHistory = wrap(() => ok({ items: db.benchmarks }))

const benchmarkResults = wrap((runId) => {
  const bench = findOr404(db.benchmarks, runId, 'API-404', '评测')
  if (!bench.results) throw fail(409, 'BENCH-409', '评测尚未完成')
  return ok({ benchmark_run_id: bench.benchmark_run_id, results: bench.results })
})

// ---- P-24 安全进化候选 / 审查 / 灰度 / 停用 ----
const governanceCandidates = wrap(() => ok({ items: db.candidates }))

const governanceReview = wrap((candidateId, body = {}) => {
  requireRole(['checker2'], 'ROLE-403', '仅 Checker 2 可审查候选')
  const cand = db.candidates.find((c) => c.candidate_id === candidateId)
  if (!cand) throw fail(404, 'API-404', '候选不存在')
  if (!['approve', 'reject'].includes(body.decision)) {
    throw fail(422, 'SUP-422', 'decision 仅支持 approve / reject', { fields: { decision: '非法取值' } })
  }
  cand.status = body.decision === 'approve' ? 'reviewed' : 'rejected'
  return ok(cand)
})

const governanceGray = wrap((candidateId, body = {}) => {
  requireRole(['checker2'], 'ROLE-403', '仅 Checker 2 可管理灰度')
  const cand = db.candidates.find((c) => c.candidate_id === candidateId)
  if (!cand) throw fail(404, 'API-404', '候选不存在')
  if (body.enabled && cand.status !== 'reviewed') throw fail(409, 'SUP-409', '候选未通过审查，不可灰度')
  const percent = Number(body.percent ?? cand.gray.percent)
  if (percent < 0 || percent > 100) throw fail(422, 'SUP-422', '灰度比例需在 0-100 之间', { fields: { percent: '范围 0-100' } })
  cand.gray = { enabled: Boolean(body.enabled), percent }
  return ok(cand)
})

const governanceKillSwitch = wrap(() => {
  requireRole(['checker2'], 'ROLE-403', '仅 Checker 2 可查看停用开关')
  return ok({ enabled: false, note: '总停用开关状态（演示）；操作接口待确认 P-24' })
})

// ---- P-21 审计事件 / 证据账本查询 / 链验证 ----
const auditEvents = wrap(() => {
  requireRole(['auditor'], 'ROLE-403', '仅审计人员可查询审计事件')
  return ok({ items: db.auditEvents })
})

const ledgerVerify = wrap((projectId) => {
  requireRole(['auditor'], 'ROLE-403', '仅审计人员可验证证据账本')
  return ok({
    project_id: projectId,
    verified: true,
    integrity: 'ok',
    last_verified_at: new Date().toISOString(),
    note: '证据账本链验证结果（演示）；完整验证接口待确认 P-21',
  })
})

export const missingHandlers = {
  'dashboard.aggregate': dashboardAggregate,
  'profiles.results': profileResults,
  'files.list': fileAssetsList,
  'versions.list': versionList,
  'versions.create': versionCreate,
  'versions.freeze': versionFreeze,
  'versions.history': versionHistory,
  'providers.list': providerList,
  'preparations.list': preparationList,
  'preparations.detail': preparationDetail,
  'approvals.list': approvalList,
  'executions.list': executionList,
  'executions.logs': executionLogs,
  'diagnosis.export': diagnosisExport,
  'ops.rerun': opsRerun,
  'ops.cleanup': opsCleanup,
  'ops.rollbackPreview': rollbackPreview,
  'ops.audit': opsAudit,
  'benchmark.history': benchmarkHistory,
  'benchmark.results': benchmarkResults,
  'governance.candidates': governanceCandidates,
  'governance.review': governanceReview,
  'governance.gray': governanceGray,
  'governance.killSwitch': governanceKillSwitch,
  'audit.events': auditEvents,
  'ledgerVerify': ledgerVerify,
}
