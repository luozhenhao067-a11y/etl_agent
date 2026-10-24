<script setup>
// 本页 API：API-02（连接列表）。
// 缺失接口 P-19 dashboard.aggregate（总览聚合）：前端不得自行聚合替代接口，
// 因此除连接列表可直接计算的计数外，其余指标显示“待确认”，不展示伪造数据。
// 健康状态由布局顶栏调用 API-01，本页不重复拉取。
import { ref, computed, onMounted } from 'vue'
import { apiConnections } from '@/api/connections'
import { useProjectStore } from '@/stores/project'
import KpiStrip from '@/components/KpiStrip.vue'
import DonutChart from '@/components/DonutChart.vue'
import AppState from '@/components/AppState.vue'
import MockBadge from '@/components/MockBadge.vue'
import { formatCount } from '@/utils/time'

const project = useProjectStore()

const loading = ref(true)
const failed = ref(false)
const forbidden = ref(false)
const error = ref(null)
const connectionTotal = ref(0)
const activeConnections = ref(0)
const connectionTypes = ref([])

async function load() {
  loading.value = true
  failed.value = false
  forbidden.value = false
  error.value = null
  try {
    const conns = await apiConnections.list(project.state.projectId, { page: 1, page_size: 100 })
    const data = conns.data || { items: [], total: 0 }
    const items = data.items || []
    connectionTotal.value = data.total ?? items.length
    activeConnections.value = items.filter((c) => c.status === 'active').length
    const byType = {}
    items.forEach((c) => {
      byType[c.type] = (byType[c.type] || 0) + 1
    })
    connectionTypes.value = Object.entries(byType).map(([name, count]) => ({ name, count }))
  } catch (e) {
    if (e.isForbidden()) forbidden.value = true
    else failed.value = true
    error.value = e
  } finally {
    loading.value = false
  }
}

onMounted(load)

const kpis = computed(() => [
  { label: '连接总数', value: formatCount(connectionTotal.value), note: 'API-02 实际返回' },
  { label: '启用连接', value: formatCount(activeConnections.value), note: 'API-02 当前页统计' },
  { label: '冻结版本', value: '—', note: '待确认 P-19' },
  { label: '运行中 Run', value: '—', note: '待确认 P-19' },
  { label: '待审批准备单', value: '—', note: '待确认 P-19' },
  { label: '完成评测', value: '—', note: '待确认 P-24' },
])
</script>

<template>
  <div>
    <div class="flex items-center gap-8 wrap mb-16">
      <h2 style="margin: 0; font-size: 17px">工作台总览</h2>
      <MockBadge />
    </div>

    <AppState v-if="loading" state="loading" />
    <AppState v-else-if="forbidden" state="forbidden" :error="error" />
    <AppState v-else-if="failed" state="error" :error="error" :retry="load" />
    <template v-else>
      <KpiStrip :items="kpis" />

      <div class="grid cols-2">
        <div class="card">
          <div class="card-title">连接类型覆盖 <span class="sub">API-02</span></div>
          <DonutChart v-if="connectionTypes.length" :items="connectionTypes" />
          <AppState v-else state="empty" />
        </div>

        <div class="card">
          <div class="card-title">Run 状态分布 <span class="sub">待确认 P-19</span></div>
          <AppState state="partial" text="数据暂不可用：dashboard.aggregate 未定义，前端不自行聚合运行数据。" />
        </div>
      </div>

      <div class="grid cols-2">
        <div class="card">
          <div class="card-title">
            待审批准备单
            <span class="right">
              <router-link class="btn sm" to="/runs/preparations">去审批</router-link>
            </span>
          </div>
          <AppState state="partial" text="数据暂不可用：preparations.list 未定义（Spec P-19）。" />
        </div>

        <div class="card">
          <div class="card-title">
            最近 Run
            <span class="right">
              <router-link class="btn sm" to="/runs/executions">运行监控</router-link>
            </span>
          </div>
          <AppState state="partial" text="数据暂不可用：executions.list 未定义（Spec P-19）。" />
        </div>
      </div>
    </template>
  </div>
</template>
