import { useAuth } from './useAuth'

// Spec 2.3 权限矩阵（前端显隐渲染）。
// 前端隐藏按钮不构成安全边界：所有写操作由服务端二次复核。
// 取值：allow = 可执行；readonly = 只读；forbid = 禁止；pending = 待确认（按只读渲染并标注）。

const MATRIX = {
  // 查看（全部页面可见）
  view: { maker: 'allow', checker1: 'allow', checker2: 'allow', ops: 'allow', auditor: 'allow' },
  // 连接管理：新建/编辑/测试限 Maker
  'connection.manage': { maker: 'allow', checker1: 'readonly', checker2: 'readonly', ops: 'readonly', auditor: 'readonly' },
  'connection.test': { maker: 'allow', checker1: 'readonly', checker2: 'readonly', ops: 'readonly', auditor: 'readonly' },
  // 只读元数据探查：限 Maker
  'metadata.profile': { maker: 'allow', checker1: 'readonly', checker2: 'readonly', ops: 'readonly', auditor: 'readonly' },
  // 文件资产上传：限 Maker
  'file.upload': { maker: 'allow', checker1: 'readonly', checker2: 'readonly', ops: 'readonly', auditor: 'readonly' },
  // Studio：生成、澄清回答、有限修复限 Maker
  'studio.generate': { maker: 'allow', checker1: 'readonly', checker2: 'readonly', ops: 'readonly', auditor: 'readonly' },
  // 冻结不可变版本 / 提交审批申请：仅 Maker
  'studio.freeze': { maker: 'allow', checker1: 'forbid', checker2: 'forbid', ops: 'forbid', auditor: 'forbid' },
  'studio.submit': { maker: 'allow', checker1: 'forbid', checker2: 'forbid', ops: 'forbid', auditor: 'forbid' },
  // 审批决策：按职责槽（data_checker 仅 Checker 1；security_checker 仅 Checker 2）
  'approval.data': { maker: 'forbid', checker1: 'allow', checker2: 'forbid', ops: 'forbid', auditor: 'forbid' },
  'approval.security': { maker: 'forbid', checker1: 'forbid', checker2: 'allow', ops: 'forbid', auditor: 'forbid' },
  // Commit：仅 Ops
  'run.commit': { maker: 'forbid', checker1: 'forbid', checker2: 'forbid', ops: 'allow', auditor: 'forbid' },
  // 取消、安全重跑、回滚、清理：仅 Ops
  'run.ops': { maker: 'forbid', checker1: 'forbid', checker2: 'forbid', ops: 'allow', auditor: 'forbid' },
  // Benchmark：触发评测、候选审查、灰度开关限 Checker 2
  'benchmark.trigger': { maker: 'readonly', checker1: 'readonly', checker2: 'allow', ops: 'readonly', auditor: 'readonly' },
  'benchmark.govern': { maker: 'readonly', checker1: 'readonly', checker2: 'allow', ops: 'readonly', auditor: 'readonly' },
  // 审计与证据账本：Auditor 允许；其他角色待确认（Spec 2.3）
  'audit.view': { maker: 'pending', checker1: 'pending', checker2: 'pending', ops: 'pending', auditor: 'allow' },
}

const SLOT_ACTIONS = {
  data_checker: 'approval.data',
  security_checker: 'approval.security',
}

export function usePermission() {
  const { role, slots } = useAuth()

  function verdict(action) {
    const row = MATRIX[action]
    if (!row) return 'forbid'
    return row[role.value] || 'forbid'
  }

  const can = (action) => verdict(action) === 'allow'
  const readonly = (action) => ['readonly', 'pending'].includes(verdict(action))
  const forbidden = (action) => verdict(action) === 'forbid'
  const pending = (action) => verdict(action) === 'pending'

  // 审批决策：对应职责槽（required_role 由审批单据读取，不由前端传入）
  function canDecide(requiredRole) {
    const action = SLOT_ACTIONS[requiredRole]
    if (!action) return false
    return can(action) && slots.value.includes(requiredRole)
  }

  return { verdict, can, readonly, forbidden, pending, canDecide }
}
