import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

// 认证适配层（机制待确认 P-26）。
// 页面只依赖 user / role / slots / isAuthenticated 四个只读接口，
// 替换真实认证实现时页面与路由均无需改动。

export function useAuth() {
  const auth = useAuthStore()
  const user = computed(() => auth.state.user)
  const role = computed(() => auth.state.user?.role ?? null)
  const slots = computed(() => auth.state.user?.slots ?? [])
  const isAuthenticated = computed(() => auth.isAuthenticated.value)

  function loginAs(nextUser) {
    auth.setUser(nextUser)
  }

  function logout() {
    auth.clearSession()
  }

  function hasSlot(slot) {
    return slots.value.includes(slot)
  }

  return { user, role, slots, isAuthenticated, loginAs, logout, hasSlot }
}
