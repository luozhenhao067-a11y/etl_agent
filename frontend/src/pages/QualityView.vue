<script setup>
// 本页 API：API-15（读取指定 Run 的指标、质量报告与监督信息）。
// 缺失接口 P-19 executions.list / P-20 diagnosis.export：不聚合、不伪造 Run 列表与诊断链。
// 错误样本由服务端掩码后返回（Spec 12.3）；诊断字段待确认 P-20，前端不自行推断。
import { ref, computed } from 'vue'
import { apiExecutions } from '@/api/executions'
import { usePermission } from '@/composables/usePermission'
import AppState from '@/components/AppState.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import KpiStrip from '@/components/KpiStrip.vue'
import BarList from '@/components/BarList.vue'
import MaskChip from '@/components/MaskChip.vue'
import PermissionBar from '@/components/PermissionBar.vue'
import MockBadge from '@/components/MockBadge.vue'
import { formatIso, formatCount } from '@/utils/time'

const { can } = usePermission()

const runIdInput = ref('')
const selectedId = ref(null)
const loading = ref(false)
const failed = ref(false)
const forbidden = ref(false)
const error = ref(null)
const detail = ref(null)

async function load() {
  const id = selectedId.value
  if (!id) return
  loading.value = true
  failed.value = false
  forbidden.value = false
  error.value = null
  try {
    const res = await apiExecutions.getRun(id)
    detail.value = res.data
  } catch (e) {
    detail.value = null
    if (e.isForbidden()) forbidden.value = true
    else failed.value = true
    error.value = e
  } finally {
    loading.value = false
  }
}

function openRun() {
  const id = runIdInput.value.trim()
  if (!id) return
  selectedId.value = id
  load()
}

const canExport = computed(() => can('run.ops') || can('audit.view'))

const kpis = computed(() => {
  const m = detail.value?.metrics
  if (!m) return []
  return [
    { label: '输入行数', value: formatCount(m.input_records) },
    { label: '错误行数', value: formatCount(m.error_records) },
    { label: '错误拒绝率', value: m.input_records ? `${Math.round((m.error_records / m.input_records) * 1000) / 10}%` : '—' },
    { label: '运行时长', value: m.duration_seconds == null ? '—' : `${Math.round(m.duration_seconds / 60)}m` },
  ]
})

const errorDist = computed(() => (detail.value?.quality_report?.error_codes || []).map((c) => ({ name: c.code, count: c.count })))
const supervisionActions = computed(() => detail.value?.supervision?.actions || [])

function actionText(action) {
  if (typeof action === 'string') return action
  return `${action.action || 'action'}：${action.reason || ''}`
}
</script>

<template>
  <div>
    <div class="flex items-center gap-8 wrap mb-16">
      <h2 style="margin: 0; font-size: 17px">质量诊断</h2>
      <MockBadge />
    </div>

    <div class="card">
      <div class="card-title">按 Run ID 查询 <span class="sub">API-15</span></div>
      <div class="tip-bar info">Run 列表接口未定义（Spec P-19）；请输入 Run ID 读取质量报告。</div>
      <div class="flex gap-8 wrap items-center">
        <input v-model="runIdInput" type="text" placeholder="如 run_demo_003" style="min-width: 260px" @keyup.enter="openRun" />
        <button class="btn primary" :disabled="!runIdInput.trim() || loading" @click="openRun">{{ loading ? '查询中…' : '查询' }}</button>
        <button v-if="selectedId" class="btn" :disabled="loading" @click="load">刷新</button>
      </div>
    </div>

    <AppState v-if="loading" state="loading" />
    <AppState v-else-if="forbidden" state="forbidden" :error="error" />
    <AppState v-else-if="failed" state="error" :error="error" :retry="load" />
    <AppState v-else-if="!selectedId" state="empty" title="尚未选择 Run" text="Run 列表待确认 P-19；输入 Run ID 后调用 API-15。" />

    <template v-else-if="detail">
      <KpiStrip :items="kpis" />

      <div class="grid cols-2">
        <div class="card">
          <div class="card-title">错误码分布 <span class="sub">Quality Report</span></div>
          <BarList v-if="errorDist.length" :items="errorDist" />
          <AppState v-else state="empty" text="无错误码统计" />
        </div>

        <div class="card">
          <div class="card-title">错误样本（掩码，Spec 12.3）</div>
          <div v-if="detail.quality_report?.error_samples?.length" class="table-wrap">
            <table class="table">
              <thead><tr><th>样本</th><th>错误码</th><th>原因</th><th>处置</th></tr></thead>
              <tbody>
                <tr v-for="(s, i) in detail.quality_report.error_samples" :key="i">
                  <td><MaskChip :value="Object.entries(s).filter(([k]) => !['code', 'reason', 'dispose'].includes(k)).map(([, v]) => v).join(' / ')" /></td>
                  <td class="mono" style="color: var(--warn)">{{ s.code }}</td>
                  <td class="dim">{{ s.reason }}</td>
                  <td class="mono dim">{{ s.dispose }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <AppState v-else state="empty" text="无样本" />
          <div class="form-hint mt-8">样本经服务端脱敏后返回，原始敏感值不出现在前端。</div>
        </div>
      </div>

      <div class="grid cols-2">
        <div class="card">
          <div class="card-title">根因诊断 <span class="sub">待确认 P-20</span></div>
          <AppState state="empty" title="诊断接口待确认" text="诊断字段与导出接口未定义（Spec P-20）；前端不自行推断根因链。" />
        </div>

        <div class="card">
          <div class="card-title">监督动作 <span class="sub">Supervision</span></div>
          <StatusBadge v-if="detail.supervision" :status="detail.supervision.status" />
          <div v-for="(a, i) in supervisionActions" :key="i" class="tip-bar warn">{{ actionText(a) }} @ {{ formatIso(detail.started_at) }}</div>
          <div v-if="!supervisionActions.length" class="form-hint">无监督动作记录</div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">诊断导出 <span class="sub">待确认 P-20</span></div>
        <PermissionBar action="run.ops" />
        <div class="tip-bar info">diagnosis.export 未定义（Spec P-20）；接口确认前不生成导出任务。</div>
        <button v-if="canExport" class="btn" disabled>导出诊断报告（待确认）</button>
      </div>
    </template>
  </div>
</template>
