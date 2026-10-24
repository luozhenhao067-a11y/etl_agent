<script setup>
// 本页 API：API-15（查询运行状态）、API-16（取消，仅 Ops）。
// 缺失接口 P-19 executions.list、P-23 executions.logs：不聚合、不伪造 Run 列表与实时日志。
// 通过 Run ID 直接查询 API-15；日志使用响应内已脱敏的 recent_logs。
// 状态刷新走 useRunStatus 适配层（Spec P-16：轮询占位，间隔 3s，方案待确认）。
import { ref, computed } from 'vue'
import { apiExecutions } from '@/api/executions'
import { useRunStatus } from '@/composables/useRunStatus'
import { usePermission } from '@/composables/usePermission'
import { useNoticeStore } from '@/stores/notice'
import AppState from '@/components/AppState.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import KpiStrip from '@/components/KpiStrip.vue'
import LogViewer from '@/components/LogViewer.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import PermissionBar from '@/components/PermissionBar.vue'
import MockBadge from '@/components/MockBadge.vue'
import { formatIso, formatCount, formatBytes, formatDuration } from '@/utils/time'

const { can } = usePermission()
const notice = useNoticeStore()

const runIdInput = ref('')
const selectedId = ref(null)

const runStatus = useRunStatus(selectedId, { intervalMs: 3000 })
const { snapshot, stale, logDisconnected, lastError } = runStatus

function openRun() {
  const id = runIdInput.value.trim()
  if (!id) return
  selectedId.value = id
  runStatus.start(id)
}

function refresh() {
  if (selectedId.value) runStatus.reconnect()
}

const initialLoading = computed(() => Boolean(selectedId.value) && !snapshot.value && !lastError.value)
const initialError = computed(() => Boolean(selectedId.value) && !snapshot.value && lastError.value)

// ---- API-16 取消（仅 Ops，二次确认） ----
const cancelOpen = ref(false)
const cancelling = ref(false)
const cancelReason = ref('')

async function doCancel() {
  cancelling.value = true
  try {
    await apiExecutions.cancel(selectedId.value, { reason: cancelReason.value.trim() })
    notice.push({ kind: 'success', text: `已请求取消：${selectedId.value}（API-16）` })
    cancelOpen.value = false
    cancelReason.value = ''
    refresh()
  } catch (e) {
    notice.push({ kind: 'error', text: e.friendly(), errorCode: e.errorCode, correlationId: e.correlationId })
  } finally {
    cancelling.value = false
  }
}

const kpis = computed(() => {
  const m = snapshot.value?.metrics
  if (!m) return []
  return [
    { label: '输入行数', value: formatCount(m.input_records) },
    { label: '输出行数', value: formatCount(m.output_records) },
    { label: '错误行数', value: formatCount(m.error_records) },
    { label: '处理字节', value: formatBytes(m.bytes_processed) },
    { label: '运行时长', value: formatDuration(m.duration_seconds) },
  ]
})

const quality = computed(() => snapshot.value?.quality_report || null)
const supervision = computed(() => snapshot.value?.supervision || null)
const recentLogs = computed(() => snapshot.value?.recent_logs || [])
const terminal = computed(() => ['succeeded', 'failed', 'cancelled', 'rolled_back'].includes(snapshot.value?.status))

function actionText(action) {
  if (typeof action === 'string') return action
  return `${action.action || 'action'}：${action.reason || ''}`
}
</script>

<template>
  <div>
    <div class="flex items-center gap-8 wrap mb-16">
      <h2 style="margin: 0; font-size: 17px">运行监控</h2>
      <MockBadge />
      <span class="faint">状态刷新：useRunStatus 适配层（轮询占位 3s，待确认 P-16）</span>
    </div>

    <div class="card">
      <div class="card-title">按 Run ID 查询 <span class="sub">API-15</span></div>
      <div class="tip-bar info">Run 列表接口未定义（Spec P-19）；前端不自行聚合，请输入 Run ID 查询。</div>
      <div class="flex gap-8 wrap items-center">
        <input v-model="runIdInput" type="text" placeholder="如 run_demo_001" style="min-width: 260px" @keyup.enter="openRun" />
        <button class="btn primary" :disabled="!runIdInput.trim()" @click="openRun">查询</button>
        <button v-if="selectedId" class="btn" @click="refresh">刷新</button>
      </div>
    </div>

    <AppState v-if="initialLoading" state="loading" />
    <AppState v-else-if="initialError && lastError?.isForbidden()" state="forbidden" :error="lastError" />
    <AppState v-else-if="initialError" state="error" :error="lastError" :retry="refresh" />
    <AppState v-else-if="!selectedId" state="empty" title="尚未选择 Run" text="Run 列表待确认 P-19；输入 Run ID 后调用 API-15。" />

    <template v-else-if="snapshot">
      <AppState v-if="stale" state="stale" :error="lastError" :retry="refresh" text="连续刷新失败，保留最后一次快照。" />

      <div class="card">
        <div class="card-title">
          Run {{ selectedId }}
          <span class="right">
            <StatusBadge :status="snapshot.status" />
            <span v-if="stale" class="badge pending">数据过期</span>
            <button v-if="can('run.ops') && !terminal" class="btn sm danger" :disabled="!cancelReason.trim()" @click="cancelOpen = true">取消运行</button>
          </span>
        </div>
        <PermissionBar action="run.ops" />
        <div v-if="can('run.ops') && !terminal" class="form-field" style="max-width: 420px; margin-bottom: 8px">
          <label>取消原因（必填）</label>
          <input v-model="cancelReason" type="text" placeholder="取消原因" />
        </div>
        <KpiStrip :items="kpis" />
        <div class="fact-list">
          <span class="fk">engine_job_id</span><span class="fv">{{ snapshot.engine_job_id || '—' }}</span>
          <span class="fk">started_at</span><span class="fv">{{ formatIso(snapshot.started_at) }}</span>
          <span class="fk">finished_at</span><span class="fv">{{ formatIso(snapshot.finished_at) }}</span>
        </div>
      </div>

      <div class="grid cols-2">
        <div class="card">
          <div class="card-title">预算监督 <span class="sub">Supervision</span></div>
          <template v-if="supervision">
            <StatusBadge :status="supervision.status" />
            <div v-if="supervision.actions?.length" class="mt-8">
              <div v-for="(a, i) in supervision.actions" :key="i" class="tip-bar warn">{{ actionText(a) }}</div>
            </div>
            <div v-else class="form-hint mt-8">无监督越线动作</div>
          </template>
          <AppState v-else state="empty" text="监督数据尚未产生" />
        </div>

        <div class="card">
          <div class="card-title">质量报告 <span class="sub">Quality</span></div>
          <template v-if="quality">
            <div class="flex items-center gap-8 mb-16">
              <StatusBadge :status="quality.status" />
              <span class="faint">错误码分布：{{ (quality.error_codes || []).map((c) => `${c.code}×${formatCount(c.count)}`).join('，') || '无' }}</span>
              <span v-if="quality.samples_masked" class="badge gray">样本已脱敏</span>
            </div>
            <div v-if="quality.error_samples?.length" class="table-wrap">
              <table class="table">
                <thead><tr><th>样本（掩码）</th><th>错误码</th><th>原因</th><th>处置</th></tr></thead>
                <tbody>
                  <tr v-for="(s, i) in quality.error_samples" :key="i">
                    <td class="mono dim">{{ Object.entries(s).filter(([k]) => !['code', 'reason', 'dispose'].includes(k)).map(([, v]) => v).join(' / ') }}</td>
                    <td class="mono" style="color: var(--warn)">{{ s.code }}</td>
                    <td class="dim">{{ s.reason }}</td>
                    <td class="mono dim">{{ s.dispose }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
          <AppState v-else state="empty" text="质量报告未产生（运行未完成）" />
        </div>
      </div>

      <div class="card">
        <div class="card-title">最近日志 <span class="sub">API-15 recent_logs（服务端脱敏）</span></div>
        <LogViewer :lines="recentLogs" :connected="!logDisconnected" :last-error="lastError" @reconnect="refresh" />
        <div class="form-hint mt-8">实时日志流接口待确认 P-23；此处只展示 API-15 返回的已脱敏最近日志。</div>
      </div>

      <ConfirmDialog
        :open="cancelOpen"
        title="取消运行"
        :message="`确认取消 Run ${selectedId}？取消为终态（OPS-409 后不可再取消）。`"
        confirm-text="确认取消"
        danger
        :submitting="cancelling"
        @confirm="doCancel"
        @cancel="cancelOpen = false"
      />
    </template>
  </div>
</template>
