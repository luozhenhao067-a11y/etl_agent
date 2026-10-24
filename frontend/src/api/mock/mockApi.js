// API-01 ~ API-18 的演示 mock 处理器。
// 约定：mock 扮演“服务端”——权限、状态机、审批约束均在此处强制执行，
// 与真实后端语义一致（前端隐藏不构成安全边界）。调用方身份取自 dev 角色切换
// （useAuthStore），仅用于模拟服务端会话；真实联调时 VITE_USE_MOCK=false。
import { useAuthStore } from '@/stores/auth'
import { db, APPLICANT } from './db'
import { ok, fail, paginate, nextId } from './index'

const SUPPORTED_TYPES = ['mysql', 'doris', 'postgresql', 'clickhouse', 'oracle', 'minio', 'rest_api']
const FILE_FORMATS = ['csv', 'excel', 'json', 'parquet']

// ---- 身份与通用校验（模拟服务端会话） ----
function caller() {
  return useAuthStore().state.user
}

function requireRole(ctx, roles, errorCode, message) {
  const u = caller()
  if (!u || !roles.includes(u.role)) throw fail(403, errorCode, message)
  return u
}

function findOr404(list, id, errorCode, resource) {
  const item = list.find((x) => x.id === id || x.connection_id === id || x.version_id === id || x.preparation_id === id || x.agent_run_id === id || x.approval_id === id || x.benchmark_run_id === id)
  if (!item) throw fail(404, errorCode, `${resource}不存在：${id}`)
  return item
}

function pathId(path, segment) {
  const parts = path.split('/')
  const i = parts.indexOf(segment)
  return i >= 0 ? parts[i + 1] : null
}

// ---- API-01 GET /health ----
function handleHealth() {
  db.health.time = new Date().toISOString()
  return ok({
    status: db.health.status,
    components: db.health.components,
    version: db.health.version,
    time: db.health.time,
  })
}

// ---- API-02 GET /api/v1/projects/{project_id}/connections ----
function handleConnectionList({ path, query = {} }) {
  const projectId = pathId(path, 'projects')
  let list = db.connections
  if (projectId) list = list.filter((c) => c.project_id === undefined || c.project_id === projectId || projectId === 'prj_demo_001')
  if (query.env) list = list.filter((c) => c.env === query.env)
  if (query.type) list = list.filter((c) => c.type === query.type)
  if (query.status) list = list.filter((c) => c.status === query.status)
  const page = Math.max(1, Number(query.page) || 1)
  const pageSize = Math.max(1, Number(query.page_size) || 10)
  return ok({ connections: paginate(list, page, pageSize) })
}

// ---- API-03 POST /api/v1/connections ----
function handleConnectionCreate({ body = {} }) {
  requireRole(null, ['maker'], 'ROLE-403', '仅数据工程师可管理连接')
  if (!body.name || !body.type) {
    throw fail(422, 'CONN-422', '连接名与类型为必填', { fields: { name: !body.name ? '必填' : undefined, type: !body.type ? '必填' : undefined } })
  }
  if (!SUPPORTED_TYPES.includes(body.type)) {
    throw fail(422, 'CONN-422', '不支持的连接类型', { fields: { type: `仅支持 ${SUPPORTED_TYPES.join('/')}` } })
  }
  if (db.connections.some((c) => c.name === body.name)) {
    throw fail(409, 'CONN-409', '连接名已存在', { fields: { name: '连接名冲突' } })
  }
  const conn = {
    id: nextId('conn'),
    name: body.name,
    type: body.type,
    env: body.env || 'test',
    status: 'inactive',
    host_masked: body.host ? body.host : '未配置',
    source_target: body.source_target || 'source',
    last_tested_at: null,
    secret_state: 'not_configured',
  }
  db.connections.unshift(conn)
  return ok(conn)
}

// ---- API-04 PUT /api/v1/connections/{id} ----
function handleConnectionUpdate({ path, body = {} }) {
  requireRole(null, ['maker'], 'ROLE-403', '仅数据工程师可管理连接')
  const id = pathId(path, 'connections')
  const conn = findOr404(db.connections, id, 'API-404', '连接')
  if (body.type && body.type !== conn.type) {
    throw fail(422, 'CONN-422', '连接类型创建后不可变更', { fields: { type: '不可变更' } })
  }
  const updatable = ['name', 'env', 'source_target', 'host_masked']
  updatable.forEach((k) => {
    if (body[k] !== undefined) conn[k] = body[k]
  })
  return ok(conn)
}

// ---- API-05 POST /api/v1/connections/{id}/tests（幂等豁免：不要求 Idempotency-Key） ----
function handleConnectionTest({ path }) {
  const id = pathId(path, 'connections')
  const conn = findOr404(db.connections, id, 'API-404', '连接')
  if (conn.name.toLowerCase().includes('timeout')) {
    throw fail(504, 'CONN-504', '连接依赖不可用，请稍后重试')
  }
  if (conn.secret_state === 'not_configured') {
    throw fail(422, 'CONN-422', '密钥未配置，无法测试', { fields: { secret: 'not_configured' } })
  }
  conn.status = 'active'
  conn.last_tested_at = new Date().toISOString()
  return ok({ connection_id: conn.id, status: 'connected', latency_ms: 23, tested_at: conn.last_tested_at })
}

// ---- API-06 POST /api/v1/connections/{id}/profiles ----
function handleProfileRun({ path }) {
  requireRole(null, ['maker'], 'ROLE-403', '仅数据工程师可发起元数据探查')
  const id = pathId(path, 'connections')
  const conn = findOr404(db.connections, id, 'API-404', '连接')
  if (conn.source_target !== 'source') {
    throw fail(422, 'META-422', '仅源端连接可发起探查', { fields: { source_target: '只读目标端不可探查' } })
  }
  const existing = db.profiles[id]
  if (!existing) {
    db.profiles[id] = {
      profile_status: 'completed',
      sampled_at: new Date().toISOString(),
      stats: { tables: 3, columns: 18, masked_columns: 6, sampled_rows: 20 },
      tables: [
        { name: 'orders', classification: 'P2' },
        { name: 'users', classification: 'P1', note: '含手机号/证件字段' },
      ],
      columns: [
        { name: 'id', type: 'bigint', pk: true, nullable: false, masked: false, classification: 'P3' },
        { name: 'phone', type: 'string', pk: false, nullable: false, masked: true, classification: 'P1' },
      ],
      masked_samples: [
        { id: '1', phone: '138****6621' },
        { id: '2', phone: '139****1130' },
      ],
    }
  }
  return ok({ profile_run_id: nextId('profile'), connection_id: conn.id, status: 'completed' })
}

// ---- API-07 POST /api/v1/file-assets（multipart/form-data） ----
function handleFileUpload({ formData }) {
  requireRole(null, ['maker'], 'ROLE-403', '仅数据工程师可上传文件资产')
  const file = formData && formData.get('file')
  if (!file || !(file instanceof File)) {
    throw fail(422, 'FILE-422', 'file 为必填文件字段', { fields: { file: '必填' } })
  }
  const ext = (file.name.split('.').pop() || '').toLowerCase()
  const fmt = ext === 'xlsx' || ext === 'xls' ? 'excel' : ext
  if (!FILE_FORMATS.includes(fmt)) {
    throw fail(422, 'FILE-422', '不支持的文件格式', { fields: { file: `仅支持 ${FILE_FORMATS.join('/')}` } })
  }
  const asset = {
    id: nextId('file'),
    file_name: file.name,
    file_size: file.size,
    file_format: fmt,
    source: 'local',
    status: 'parsed',
    created_at: new Date().toISOString(),
    schema_json: { fields: [] },
    head_preview: [],
  }
  db.files.unshift(asset)
  return ok({ file_asset_id: asset.id, status: 'parsed', file_name: asset.file_name })
}

// ---- API-08 POST /api/v1/pipelines ----
function handlePipelineCreate({ body = {} }) {
  requireRole(null, ['maker'], 'ROLE-403', '仅数据工程师可创建 Pipeline')
  if (!body.name || !body.code) {
    throw fail(422, 'META-422', '名称与代码为必填', { fields: { name: !body.name ? '必填' : undefined, code: !body.code ? '必填' : undefined } })
  }
  if (db.pipelines.some((p) => p.code === body.code)) {
    throw fail(409, 'API-409', 'Pipeline 代码冲突')
  }
  const pipeline = {
    pipeline_id: nextId('pipe'),
    name: body.name,
    code: body.code,
    description: body.description || '',
    status: 'draft',
    created_at: new Date().toISOString(),
  }
  db.pipelines.push(pipeline)
  return ok(pipeline)
}

// ---- API-09 POST /api/v1/versions/{version_id}/generation ----
function handleGenerate({ path, body = {} }) {
  requireRole(null, ['maker'], 'ROLE-403', '仅数据工程师可发起生成')
  const versionId = pathId(path, 'versions')
  const version = findOr404(db.versions, versionId, 'API-404', '版本')
  if (version.is_immutable) {
    throw fail(409, 'VER-409', '冻结版本不可再生成', { fields: { version_id: 'is_immutable=true' } })
  }
  const running = db.agentRuns[versionId]
  if (running && running.status === 'running') {
    throw fail(409, 'GEN-409', '该版本已有生成线程运行中')
  }
  const run = {
    agent_run_id: nextId('agent'),
    thread_id: nextId('thread'),
    status: 'running',
    question_index: 0,
    questions: [
      { question: '目标表不存在，是否创建？（演示澄清）', fields: [{ name: 'create_target', type: 'boolean' }] },
      { question: '请选择调度策略（演示澄清）', fields: [{ name: 'schedule_mode', type: 'enum', options: ['manual', 'hourly', 'daily'] }] },
    ],
    steps: [
      { step: '意图解析', status: 'done', detail: '识别源/目标与脱敏要求' },
      { step: '元数据探查', status: 'running', detail: '读取 Profile 引用' },
      { step: 'EtlPlan 生成', status: 'todo' },
      { step: 'HOCON 生成', status: 'todo' },
      { step: '确定性门禁', status: 'todo' },
      { step: '试运行校验', status: 'todo' },
    ],
    repair_count: 0,
  }
  db.agentRuns[versionId] = run
  db.design.ready = false
  // 模拟生成推进到第一个澄清问题
  setTimeout(() => {
    const r = db.agentRuns[versionId]
    if (r && r.status === 'running') {
      r.status = 'interrupted'
      r.steps[0].status = 'done'
      r.steps[1].status = 'done'
      r.steps[2].status = 'running'
    }
  }, 600)
  return ok({ agent_run_id: run.agent_run_id, status: 'running' })
}

// ---- API-10 POST /api/v1/agent-runs/{run_id}/answers（幂等键是否强制待确认） ----
function handleAnswer({ path, body = {} }) {
  requireRole(null, ['maker'], 'ROLE-403', '仅申请人可回答澄清问题')
  const runId = pathId(path, 'agent-runs')
  const entry = Object.entries(db.agentRuns).find(([, v]) => v.agent_run_id === runId)
  if (!entry) throw fail(404, 'API-404', '生成线程不存在')
  const run = entry[1]
  if (run.status !== 'interrupted') {
    throw fail(409, 'GEN-409', '当前状态不接受回答')
  }
  const question = run.questions[run.question_index]
  const fieldNames = question.fields.map((f) => f.name)
  const missing = fieldNames.filter((n) => body[n] === undefined)
  if (missing.length) {
    throw fail(422, 'GEN-422', '回答缺少字段', { fields: Object.fromEntries(missing.map((n) => [n, '必填'])) })
  }
  run.question_index += 1
  if (run.question_index < run.questions.length) {
    run.status = 'interrupted'
    run.steps[2].status = 'running'
    return ok({ agent_run_id: run.agent_run_id, status: 'interrupted', question_index: run.question_index })
  }
  run.status = 'running'
  setTimeout(() => {
    if (run.status === 'running') {
      run.status = 'design_ready'
      run.steps.forEach((s) => (s.status = 'done'))
      db.design.ready = true
    }
  }, 700)
  return ok({ agent_run_id: run.agent_run_id, status: 'running' })
}

// ---- API-11 GET /api/v1/versions/{version_id}/design ----
function handleDesignGet({ path }) {
  const versionId = pathId(path, 'versions')
  const version = findOr404(db.versions, versionId, 'API-404', '版本')
  if (version.is_immutable) return ok(db.design.data)
  if (!db.design.ready) {
    const run = db.agentRuns[versionId]
    const details = {}
    if (run) {
      details.steps = run.steps
      if (run.status === 'interrupted') {
        // 澄清问题通过 409 details 返回（演示约定；真实契约字段待确认）
        details.interrupted = true
        details.question = run.questions[run.question_index]
        details.agent_run_id = run.agent_run_id
      }
    }
    throw fail(409, 'GEN-409', run && run.status === 'interrupted' ? '需要回答澄清问题' : '设计尚未就绪', details)
  }
  return ok(db.design.data)
}

// ---- API-12 POST /api/v1/versions/{version_id}/prepare ----
function handlePrepare({ path, body = {} }) {
  requireRole(null, ['maker'], 'ROLE-403', '仅数据工程师可发起准备')
  const versionId = pathId(path, 'versions')
  const version = findOr404(db.versions, versionId, 'API-404', '版本')
  if (!version.is_immutable) {
    throw fail(409, 'PREP-409', '版本未冻结，禁止准备')
  }
  if (db.preparations.some((p) => p.version_id === versionId && ['PREPARED', 'PARTIAL_APPROVED'].includes(p.status))) {
    throw fail(409, 'PREP-409', '该版本已有在途准备单')
  }
  const env = body.environment || 'test'
  const budget = body.budget || {}
  const prep = {
    preparation_id: nextId('prep'),
    version_id: versionId,
    status: 'PREPARED',
    risk_level: 'P2',
    created_at: new Date().toISOString(),
    applicant: APPLICANT,
    fingerprint: 'sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08',
    frozen_facts: {
      environment: env,
      source_profile_ref: body.source_profile_ref || 'profile_demo_src_001',
      target_profile_ref: body.target_profile_ref || 'profile_demo_dst_001',
      artifact_digest: version.artifact_digest,
      budget: {
        max_input_rows: budget.max_input_rows || 1000000,
        max_output_bytes: budget.max_output_bytes || 5368709120,
        max_duration_seconds: budget.max_duration_seconds || 3600,
        output_amplification: budget.output_amplification || 3,
        error_reject_rate: budget.error_reject_rate || 0.05,
      },
      quality_contract_ref: body.quality_contract_ref || 'qc_demo_001',
      schedule: body.schedule || { mode: 'manual' },
    },
    impact_scope: { source_tables: ['orders'], target_tables: ['orders_shadow'], environments: [env], data_classification: 'P2' },
    rollback_plan: { mode: 'shadow_table_cleanup', steps: ['仅清理本 Run 影子表与临时资源', '正式表零变更'], limitation: 'Swap 后回滚未定义，待确认 P-29' },
    approval_requests: [
      { approval_id: nextId('apr'), required_role: 'data_checker', approver_id: 'user_demo_002', status: 'PENDING', decision: null, decided_at: null, opinion_digest: null },
      { approval_id: nextId('apr'), required_role: 'security_checker', approver_id: 'user_demo_003', status: 'PENDING', decision: null, decided_at: null, opinion_digest: null },
    ],
    approval_history: [],
    capability_preview: { tool: 'etl.execute', ttl_seconds: 300, environment: env, scope_summary: 'orders → 影子表 → 质量通过后原子 Swap', note: '前端仅可见 capability_digest' },
    commit: null,
  }
  db.preparations.unshift(prep)
  return ok(prep)
}

// ---- API-13 POST /api/v1/approval-requests/{approval_id}/decisions ----
function handleDecision({ path, body = {} }) {
  const approvalId = pathId(path, 'approval-requests')
  let target = null
  let prep = null
  for (const p of db.preparations) {
    const a = p.approval_requests.find((x) => x.approval_id === approvalId)
    if (a) {
      target = a
      prep = p
      break
    }
  }
  if (!target) throw fail(404, 'API-404', '审批单据不存在')
  if (target.decision) throw fail(409, 'APR-409', '审批决策不可变更')
  const u = caller()
  if (!u) throw fail(401, 'AUTH-401', '未登录')
  if (u.id === prep.applicant.id) throw fail(403, 'APR-403', '申请人禁止自批')
  if (!u.slots.includes(target.required_role)) throw fail(403, 'APR-403', '职责槽不匹配，无审批权限')
  const decision = body.decision
  if (!['approve', 'reject'].includes(decision)) {
    throw fail(422, 'APR-422', 'decision 仅支持 approve / reject', { fields: { decision: '非法取值' } })
  }
  target.decision = decision
  target.status = decision === 'approve' ? 'APPROVED' : 'REJECTED'
  target.decided_at = new Date().toISOString()
  target.opinion_digest = body.opinion ? 'sha256:opinion***' : null
  prep.approval_history.push({ approval_id: target.approval_id, role_slot: target.required_role, decision, decided_at: target.decided_at })
  const decided = prep.approval_requests.every((a) => a.decision)
  if (decided) {
    prep.status = prep.approval_requests.every((a) => a.decision === 'approve') ? 'APPROVED' : 'REJECTED'
  } else if (prep.approval_requests.some((a) => a.decision === 'reject')) {
    prep.status = 'REJECTED'
  } else if (prep.approval_requests.some((a) => a.decision === 'approve')) {
    prep.status = 'PARTIAL_APPROVED'
  }
  return ok({ approval_id: target.approval_id, status: target.status, decided_at: target.decided_at })
}

// ---- API-14 POST /api/v1/preparations/{preparation_id}/commit ----
function handleCommit({ path, body = {} }) {
  requireRole(null, ['ops'], 'CMT-403', '仅 Ops 可执行提交')
  const preparationId = pathId(path, 'preparations')
  const prep = findOr404(db.preparations, preparationId, 'API-404', '准备单')
  if (prep.status !== 'APPROVED') throw fail(409, 'CMT-409', '审批未完成，禁止提交')
  if (body.fingerprint && body.fingerprint !== prep.frozen_facts.artifact_digest) {
    throw fail(409, 'CMT-409', '指纹校验失败，准备单已变更')
  }
  const run = {
    id: nextId('run'),
    status: 'queued',
    engine_job_id: null,
    version_id: prep.version_id,
    preparation_id: prep.preparation_id,
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
  db.runs.unshift(run)
  prep.commit = {
    execution_run_id: run.id,
    capability_digest: 'sha256:5c4ae8e2d1b6a9f03c7d5e2a1b8f6c4d9e0a3b2c1d4e5f6a7b8c9d0e1f2a3b4c',
    committed_at: new Date().toISOString(),
  }
  // 响应仅 execution_run_id / status / committed_at / capability_digest，不返回 Capability 明文
  return ok({ execution_run_id: run.id, status: run.status, committed_at: prep.commit.committed_at, capability_digest: prep.commit.capability_digest })
}

// ---- API-15 GET /api/v1/execution-runs/{id} ----
function tickRun(run) {
  if (run.status !== 'running') return run
  run._tick = (run._tick || 0) + 1
  const stage = run.stages.find((s) => s.status === 'running')
  if (run._tick >= 3 && stage) {
    stage.status = 'done'
    const next = run.stages.find((s) => s.status === 'todo')
    if (next) next.status = 'running'
  }
  if (run._tick >= 6) {
    run.status = 'succeeded'
    run.finished_at = new Date().toISOString()
    run.stages.forEach((s) => (s.status = 'done'))
    run.metrics = { input_records: 1000, output_records: 990, error_records: 10, bytes_processed: 8192, duration_seconds: 90 }
    run.quality_report = { status: 'quality_pass', error_codes: [{ code: 'E-2003', count: 10 }], samples_masked: true, error_samples: [{ phone: '138****6621', code: 'E-2003', reason: '手机号格式不符', dispose: 'error_table' }] }
    run.recent_logs.push(`${new Date().toISOString()} swap completed masked=true`)
  }
  return run
}

function handleRunGet({ path }) {
  const id = pathId(path, 'execution-runs')
  const run = findOr404(db.runs, id, 'API-404', '执行 Run')
  const { _tick, ...rest } = tickRun(run)
  return ok(rest)
}

// ---- API-16 POST /api/v1/execution-runs/{id}/cancel ----
function handleCancel({ path }) {
  requireRole(null, ['ops'], 'OPS-403', '仅 Ops 可取消运行')
  const id = pathId(path, 'execution-runs')
  const run = findOr404(db.runs, id, 'API-404', '执行 Run')
  if (['succeeded', 'failed', 'cancelled', 'rolled_back'].includes(run.status)) {
    throw fail(409, 'OPS-409', '终态运行不可取消')
  }
  run.status = 'cancelled'
  run.finished_at = new Date().toISOString()
  run.recent_logs.push(`${new Date().toISOString()} cancelled by ops reason_digest=true`)
  db.opsHistory.unshift({ id: nextId('ops_evt'), run_id: run.id, action: 'cancel', actor_id: caller().id, reason_digest: 'sha256:reason***', result: 'success', at: new Date().toISOString() })
  return ok({ id: run.id, status: run.status })
}

// ---- API-17 POST /api/v1/execution-runs/{id}/rollback ----
function handleRollback({ path, body = {} }) {
  requireRole(null, ['ops'], 'OPS-403', '仅 Ops 可执行回滚')
  const id = pathId(path, 'execution-runs')
  const run = findOr404(db.runs, id, 'API-404', '执行 Run')
  if (body.confirmation !== 'ROLLBACK') {
    throw fail(422, 'OPS-422', '二次确认失败：请输入 ROLLBACK', { fields: { confirmation: '需输入 ROLLBACK' } })
  }
  if (!body.reason) {
    throw fail(422, 'OPS-422', '回滚原因必填', { fields: { reason: '必填' } })
  }
  if (run.status === 'running') {
    throw fail(409, 'OPS-409', '运行中不可回滚，请先取消')
  }
  run.status = 'rolled_back'
  run.finished_at = new Date().toISOString()
  run.recent_logs.push(`${new Date().toISOString()} rollback completed shadow cleanup=masked`)
  db.opsHistory.unshift({ id: nextId('ops_evt'), run_id: run.id, action: 'rollback', actor_id: caller().id, reason_digest: 'sha256:reason***', result: 'success', at: new Date().toISOString() })
  return ok({ id: run.id, status: run.status })
}

// ---- API-18 POST /api/v1/benchmarks/run ----
function handleBenchmarkRun({ body = {} }) {
  const u = requireRole(null, ['checker2'], 'BENCH-403', '仅 Checker 2 可触发评测')
  if (!body.suite_id || !body.layer || !body.dataset_version) {
    throw fail(422, 'BENCH-422', 'suite_id / layer / dataset_version 必填')
  }
  if (db.benchmarks.some((b) => b.suite_id === body.suite_id && b.layer === body.layer && b.status === 'running')) {
    throw fail(409, 'BENCH-409', '同套件同层已有评测运行中')
  }
  const bench = {
    benchmark_run_id: nextId('bench'),
    suite_id: body.suite_id,
    suite_name: body.suite_name || body.suite_id,
    layer: body.layer,
    dataset_version: body.dataset_version,
    status: 'running',
    started_at: new Date().toISOString(),
    finished_at: null,
    results: null,
  }
  db.benchmarks.unshift(bench)
  setTimeout(() => {
    if (bench.status === 'running') {
      bench.status = 'completed'
      bench.finished_at = new Date().toISOString()
      bench.results = { accuracy: 0.9, schema_coverage: 0.94, p0_p1_intercept: 0.98, latency_p50_ms: 900, latency_p95_ms: 1800, latency_p99_ms: 2300 }
    }
  }, 2500)
  return ok({ benchmark_run_id: bench.benchmark_run_id, status: bench.status })
}

export const handlers = {
  'API-01': ({ path }) => (path === '/health' ? handleHealth() : null),
  'API-02': handleConnectionList,
  'API-03': handleConnectionCreate,
  'API-04': handleConnectionUpdate,
  'API-05': handleConnectionTest,
  'API-06': handleProfileRun,
  'API-07': handleFileUpload,
  'API-08': handlePipelineCreate,
  'API-09': handleGenerate,
  'API-10': handleAnswer,
  'API-11': handleDesignGet,
  'API-12': handlePrepare,
  'API-13': handleDecision,
  'API-14': handleCommit,
  'API-15': handleRunGet,
  'API-16': handleCancel,
  'API-17': handleRollback,
  'API-18': handleBenchmarkRun,
}
