// 页面状态机常量（Spec 6.1 路由总表 / 6.2~6.13 各页面「页面状态」行）。
// 单一来源：页面新增状态一律先在此登记；AppState 组件负责渲染。
// 注：真实后端依赖未就绪（503）时部分状态不可达，mock 模式可走通全流程。

export const PAGE_STATES = {
  dashboard: ['loading', 'empty', 'partial', 'stale', 'error', 'forbidden'],
  connections: ['loading', 'empty', 'filtered-empty', 'drawer-open', 'submitting', 'test-running', 'test-success', 'test-failed', 'error', 'forbidden'],
  profiles: ['idle', 'profiling', 'success', 'partial', 'failed', 'sample-masked', 'empty', 'forbidden'],
  files: ['idle', 'uploading', 'parsing', 'inferred', 'infer-failed', 'empty', 'error', 'forbidden'],
  studio: ['draft', 'generating', 'interrupted', 'resumed', 'gate-failed', 'repairing', 'gate-passed', 'frozen', 'submitted', 'stale', 'error', 'forbidden'],
  preparations: ['pending', 'partial-approved', 'approved', 'rejected', 'committing', 'committed', 'commit-failed', 'error', 'forbidden'],
  executions: ['running', 'succeeded', 'failed', 'cancelled', 'queued', 'stale', 'log-disconnected', 'error', 'forbidden'],
  quality: ['loading', 'quality-pass', 'quality-warning', 'failed', 'diagnosing', 'supervision-breached', 'empty', 'forbidden'],
  operations: ['idle', 'confirming', 'validating', 'executing', 'success', 'failed', 'rejected', 'stale', 'forbidden'],
  benchmark: ['idle', 'running', 'completed', 'warning', 'failed', 'candidate-pending', 'gray-enabled', 'kill-switch', 'error', 'forbidden'],
}

// 页面态是否在 Spec 6.1 定义集合内（展示层归一化用；API 原始值不强制等于页面态）。
export function isPageState(page, state) {
  const s = String(state ?? '').toLowerCase()
  return PAGE_STATES[page]?.includes(s) ?? false
}
