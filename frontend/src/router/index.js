import { createRouter, createWebHistory } from 'vue-router'
import AppLayout from '@/layouts/AppLayout.vue'

// 路由固定 12 条（Spec 6.1）：不增不减。
//  - /governance/evolution：原型缺失占位（Spec 6.14）
//  - /audit：审计与证据占位；路由路径本身待确认 P-21（Spec 6.13）
const routes = [
  {
    path: '/',
    component: AppLayout,
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', name: 'dashboard', component: () => import('@/pages/DashboardView.vue'), meta: { title: '工作台总览', group: '工作台' } },
      { path: 'connections', name: 'connections', component: () => import('@/pages/ConnectionsView.vue'), meta: { title: '连接管理', group: '连接与资产' } },
      { path: 'connections/profiles', name: 'connections-profiles', component: () => import('@/pages/ProfilesView.vue'), meta: { title: '元数据探查', group: '连接与资产' } },
      { path: 'assets/files', name: 'assets-files', component: () => import('@/pages/FileAssetsView.vue'), meta: { title: '文件资产', group: '连接与资产' } },
      { path: 'studio/:versionId', name: 'studio', component: () => import('@/pages/StudioView.vue'), meta: { title: '生成 Studio', group: 'Studio' } },
      { path: 'runs/preparations', name: 'runs-preparations', component: () => import('@/pages/PreparationsView.vue'), meta: { title: '变更准备', group: '运行中心' } },
      { path: 'runs/executions', name: 'runs-executions', component: () => import('@/pages/ExecutionsView.vue'), meta: { title: '运行监控', group: '运行中心' } },
      { path: 'runs/quality', name: 'runs-quality', component: () => import('@/pages/QualityView.vue'), meta: { title: '质量诊断', group: '运行中心' } },
      { path: 'runs/operations', name: 'runs-operations', component: () => import('@/pages/OperationsView.vue'), meta: { title: '运维操作', group: '运行中心' } },
      { path: 'governance/benchmark', name: 'governance-benchmark', component: () => import('@/pages/BenchmarkView.vue'), meta: { title: '安全评测与进化', group: '安全治理' } },
      { path: 'governance/evolution', name: 'governance-evolution', component: () => import('@/pages/EvolutionView.vue'), meta: { title: '安全进化', group: '安全治理' } },
      // 审计与证据页路由待确认 P-21
      { path: 'audit', name: 'audit', component: () => import('@/pages/AuditView.vue'), meta: { title: '审计与证据', group: '审计' } },
      { path: ':pathMatch(.*)*', redirect: '/dashboard' },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · ETL-Agent 数据集成平台` : 'ETL-Agent 数据集成平台'
})

export default router
