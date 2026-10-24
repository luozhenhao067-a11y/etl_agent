<script setup>
// 应用壳：侧边导航（12 路由固定分组）+ 顶栏 + 全局通知 + 认证门。
// 认证机制待确认 P-26：未登录时显示模拟登录门（dev 角色切换）。
// 项目切换接口未定义（待确认 P-22）：当前固定演示项目。
import { ref, onMounted, computed } from 'vue'
import { useAuthStore, DEV_USERS } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import { useNoticeStore } from '@/stores/notice'
import { apiHealth } from '@/api/health'

const auth = useAuthStore()
const project = useProjectStore()
const notice = useNoticeStore()

const isAuthenticated = computed(() => Boolean(auth.state.user))

// API-01 健康检查：顶栏健康点（演示：每 30s 一次；真实间隔待确认）
const health = ref(null)
let healthTimer = null

async function checkHealth() {
  try {
    const res = await apiHealth.get()
    health.value = res.data
  } catch {
    health.value = { status: 'error' }
  }
}

onMounted(() => {
  checkHealth()
  healthTimer = setInterval(checkHealth, 30000)
})

// dev 角色切换：仅演示 Spec 2.3 权限矩阵。真实认证接入后移除。
function switchRole(event) {
  const user = DEV_USERS.find((u) => u.id === event.target.value)
  if (user) auth.setUser(user)
}

const navGroups = [
  {
    name: '工作台',
    links: [{ to: '/dashboard', label: '总览' }],
  },
  {
    name: '连接与资产',
    links: [
      { to: '/connections', label: '连接管理' },
      { to: '/connections/profiles', label: '元数据探查' },
      { to: '/assets/files', label: '文件资产' },
    ],
  },
  {
    name: 'Studio',
    links: [{ to: '/studio/ver_demo_002', label: '生成 Studio' }],
  },
  {
    name: '运行中心',
    links: [
      { to: '/runs/preparations', label: '变更准备' },
      { to: '/runs/executions', label: '运行监控' },
      { to: '/runs/quality', label: '质量诊断' },
      { to: '/runs/operations', label: '运维操作' },
    ],
  },
  {
    name: '安全治理',
    links: [
      { to: '/governance/benchmark', label: '安全评测与进化' },
      { to: '/governance/evolution', label: '安全进化', pill: '占位' },
    ],
  },
  {
    name: '审计',
    links: [{ to: '/audit', label: '审计与证据', pill: '待确认' }],
  },
]
</script>

<template>
  <div v-if="!isAuthenticated" class="auth-gate">
    <div class="ag-box">
      <div class="ag-title">会话已失效</div>
      <p class="ag-note">认证与登录机制待确认 P-26。演示环境提供模拟登录：</p>
      <button class="btn primary" @click="auth.setUser(DEV_USERS[0])">模拟登录（演示）</button>
    </div>
  </div>

  <div v-else class="app-shell">
    <aside class="app-sidebar">
      <div class="brand">
        ETL-Agent 数据集成平台
        <small>生产级 · 演示前端</small>
      </div>
      <nav v-for="group in navGroups" :key="group.name">
        <div class="side-group">{{ group.name }}</div>
        <router-link v-for="link in group.links" :key="link.to" :to="link.to" class="side-link">
          {{ link.label }}<span v-if="link.pill" class="pill">{{ link.pill }}</span>
        </router-link>
      </nav>
    </aside>

    <div class="app-main">
      <header class="app-topbar">
        <span class="page-title">{{ $route.meta.title }}</span>
        <span class="health-dot">
          <span class="dot" :class="health && health.status === 'ok' ? 'ok' : health && health.status === 'error' ? 'err' : 'warn'"></span>
          服务健康
        </span>
        <span class="dim">{{ project.state.name }} · {{ project.state.env }}</span>
        <span class="spacer"></span>
        <span class="role-chip">
          当前角色：
          <select :value="auth.state.user.id" @change="switchRole" title="dev 角色切换（演示）">
            <option v-for="u in DEV_USERS" :key="u.id" :value="u.id">{{ u.display_name }} · {{ u.role }}</option>
          </select>
        </span>
      </header>

      <main class="page-body">
        <router-view />
      </main>
    </div>

    <div class="notice-toasts">
      <div v-for="n in notice.state.items" :key="n.id" class="notice" :class="`kind-${n.kind}`">
        <div>{{ n.text }}</div>
        <div v-if="n.errorCode" class="n-code">{{ n.errorCode }}<template v-if="n.correlationId"> · {{ n.correlationId }}</template></div>
        <div v-if="n.retry" class="mt-8"><button class="btn sm" @click="notice.dismiss(n.id); n.retry()">重试</button></div>
      </div>
    </div>
  </div>
</template>
