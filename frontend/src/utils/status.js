// 状态徽标颜色（Spec 7.x）：成功绿、运行中蓝、待审批橙、失败/高风险红、禁用灰。
// 状态枚举本身待确认 P-35，本映射仅为展示层约定，不构成契约。

const COLOR_MAP = [
  ['success', ['ok', 'active', 'succeeded', 'completed', 'passed', 'approved', 'committed', 'configured', 'parsed', 'verified', 'frozen', 'quality_pass', 'within_budget', 'completed_ok', 'done', 'cleaned', 'rolled_back']],
  ['running', ['running', 'generating', 'profiling', 'uploading', 'queued', 'dispatched', 'committing', 'diagnosing', 'resumed', 'executing']],
  ['pending', ['pending', 'pending_approval', 'prepared', 'partial_approved', 'warning', 'interrupted', 'draft', 'candidate_pending', 'partial', 'idle', 'parsing']],
  ['danger', ['failed', 'rejected', 'error', 'broken', 'high_risk', 'commit_failed', 'infer_failed', 'parse_failed', 'kill_switch', 'cancelled', 'supervision_breached', 'not_configured']],
  ['gray', ['disabled', 'inactive', 'unknown', 'expired', 'null', 'todo', 'not_started']],
]

export function statusColor(status) {
  const s = String(status ?? '').toLowerCase()
  for (const [color, list] of COLOR_MAP) {
    if (list.includes(s)) return color
  }
  return 'gray'
}

const LABELS = {
  ok: '正常',
  active: '已启用',
  inactive: '已停用',
  succeeded: '成功',
  completed: '已完成',
  passed: '通过',
  approved: '已批准',
  committed: '已提交',
  configured: '已配置',
  not_configured: '未配置',
  parsed: '已解析',
  parse_failed: '解析失败',
  infer_failed: '推断失败',
  verified: '已验证',
  broken: '链路断裂',
  frozen: '已冻结',
  queued: '排队中',
  dispatched: '已派发',
  running: '运行中',
  generating: '生成中',
  profiling: '探查中',
  uploading: '上传中',
  parsing: '解析中',
  diagnosing: '诊断中',
  executing: '执行中',
  committing: '提交中',
  pending: '待审批',
  pending_approval: '待审批',
  prepared: '已准备',
  partial_approved: '部分批准',
  warning: '预警',
  interrupted: '等待回答',
  draft: '草稿',
  candidate_pending: '候选待审查',
  resumed: '已恢复',
  failed: '失败',
  rejected: '已驳回',
  error: '错误',
  commit_failed: '提交失败',
  cancelled: '已取消',
  cleaned: '已清理',
  rolled_back: '已回滚',
  kill_switch: '紧急停用',
  supervision_breached: '监督越线',
  high_risk: '高风险',
  expired: '已过期',
  disabled: '已禁用',
  unknown: '未知',
  todo: '未开始',
  done: '完成',
  idle: '空闲',
}

export function statusLabel(s) {
  if (s === null || s === undefined) return '—'
  return LABELS[String(s).toLowerCase()] ?? s
}
