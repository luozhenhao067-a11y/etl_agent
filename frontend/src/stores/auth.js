import { computed, reactive } from 'vue'

// 认证与角色状态（机制待确认 P-26）。
// 安全约束：令牌仅存内存，绝不进入 localStorage / sessionStorage / 日志。
// dev 模式内置 5 类演示角色用于验证 Spec 2.3 权限矩阵；
// 真实认证接入后替换本文件与 composables/useAuth.js 即可。

export const DEV_USERS = [
  { id: 'user_demo_001', username: 'maker01', display_name: '张三', role: 'maker', slots: [], title: '数据工程师（申请人 / Maker）' },
  { id: 'user_demo_002', username: 'checker1_01', display_name: '李四', role: 'checker1', slots: ['data_checker'], title: '数据审批人（Checker 1）' },
  { id: 'user_demo_003', username: 'checker2_01', display_name: '王五', role: 'checker2', slots: ['security_checker'], title: '安全审批人（Checker 2）' },
  { id: 'user_demo_004', username: 'ops01', display_name: '赵六', role: 'ops', slots: [], title: '系统操作员（Ops）' },
  { id: 'user_demo_005', username: 'auditor01', display_name: '钱七', role: 'auditor', slots: [], title: '审计人员（Auditor）' },
]

const state = reactive({
  user: null,
  token: null,
})

export function useAuthStore() {
  const isAuthenticated = computed(() => Boolean(state.user))

  function setUser(user) {
    state.user = user
    // 占位令牌仅用于演示请求头；真实令牌格式与获取方式待确认 P-26。
    // 后端 mock 认证只接受 Authorization: Bearer <user_demo_xxx>，
    // 因此这里把演示用户 ID 作为占位令牌，切换用户即切换角色。
    state.token = user ? `Bearer ${user.id}` : null
  }

  function clearSession() {
    state.user = null
    state.token = null
  }

  function init() {
    if (!state.user) setUser(DEV_USERS[0])
  }

  return { state, isAuthenticated, setUser, clearSession, init, DEV_USERS }
}
