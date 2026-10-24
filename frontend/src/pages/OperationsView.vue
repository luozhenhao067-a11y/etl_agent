<script setup>
// 本页 API：API-15（查询目标 Run）、API-16（取消运行）、API-17（受管回滚，confirmation=ROLLBACK）。
// 缺失接口 P-20 ops.rerun / ops.cleanup / ops.rollbackPreview / ops.audit：
// 不聚合、不伪造操作历史；只显示“待确认”。Run 列表 P-19 同样待确认，按 Run ID 查询。
// 全部操作仅 Ops（Spec 2.3），原因必填；回滚需输入 ROLLBACK。
import { ref, computed } from 'vue'
import { apiExecutions } from '@/api/executions'
import { usePermission } from '@/composables/usePermission'
import { useNoticeStore } from '@/stores/notice'
import AppState from '@/components/AppState.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import PermissionBar from '@/components/PermissionBar.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import TypedConfirmInput from '@/components/TypedConfirmInput.vue'
import MockBadge from '@/components/MockBadge.vue'
import { formatIso } from '@/utils/time'

const { can } = usePermission()
const notice = useNoticeStore()

const runIdInput = ref('')
const selectedId = ref(null)
const loading = ref(false)
const failed = ref(false)
const forbidden = ref(false)
const error = ref(null)
const run = ref(null)

async function load() {
  if (!selectedId.value) return
  loading.value = true
  failed.value = false
  forbidden.value = false
  error.value = null
  try {
    const res = await apiExecutions.getRun(selectedId.value)
    run.value = res.data
  } catch (e) {
    run.value = null
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

const terminal = computed(() => ['succeeded', 'failed', 'cancelled', 'rolled_back'].includes(run.value?.status))

// ---- API-16 取消 ----
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
    load()
  } catch (e) {
    notice.push({ kind: 'error', text: e.friendly(), errorCode: e.errorCode, correlationId: e.correlationId })
  } finally {
    cancelling.value = false
  }
}

// ---- API-17 回滚 ----
const rollbackOpen = ref(false)
const rolling = ref(false)

async function doRollback({ confirmation, reason }) {
  rolling.value = true
  try {
    const res = await apiExecutions.rollback(selectedId.value, { confirmation, reason })
    notice.push({ kind: 'success', text: `回滚已完成：${res.data.rollback_status}（API-17）` })
    rollbackOpen.value = false
    load()
  } catch (e) {
    notice.push({ kind: 'error', text: e.friendly(), errorCode: e.errorCode, correlationId: e.correlationId })
  } finally {
    rolling.value = false
  }
}
</script>

<template>
  <div>
    <div class="flex items-center gap-8 wrap mb-16">
      <h2 style="margin: 0; font-size: 17px">运维操作</h2>
      <MockBadge />
    </div>

    <PermissionBar action="run.ops" />
    <div class="tip-bar warn">全部运维操作仅 Ops 可执行；服务端二次校验角色（OPS-403）与状态机（OPS-409）。原因仅服务端摘要留存。</div>

    <div class="card">
      <div class="card-title">按 Run ID 查询 <span class="sub">API-15</span></div>
      <div class="tip-bar info">Run 列表接口未定义（Spec P-19）；请输入 Run ID。</div>
      <div class="flex gap-8 wrap items-center">
        <input v-model="runIdInput" type="text" placeholder="如 run_demo_001" style="min-width: 260px" @keyup.enter="openRun" />
        <button class="btn primary" :disabled="!runIdInput.trim() || loading" @click="openRun">{{ loading ? '查询中…' : '查询' }}</button>
        <button v-if="selectedId" class="btn" :disabled="loading" @click="load">刷新</button>
      </div>
    </div>

    <AppState v-if="loading" state="loading" />
    <AppState v-else-if="forbidden" state="forbidden" :error="error" />
    <AppState v-else-if="failed" state="error" :error="error" :retry="load" />
    <AppState v-else-if="!selectedId" state="empty" title="尚未选择 Run" text="Run 列表待确认 P-19；输入 Run ID 后调用 API-15。" />

    <template v-else-if="run">
      <div class="card">
        <div class="card-title">
          Run {{ selectedId }}
          <span class="right"><StatusBadge :status="run.status" /></span>
        </div>
        <div class="fact-list">
          <span class="fk">engine_job_id</span><span class="fv">{{ run.engine_job_id || '—' }}</span>
          <span class="fk">started_at</span><span class="fv">{{ formatIso(run.started_at) }}</span>
          <span class="fk">finished_at</span><span class="fv">{{ formatIso(run.finished_at) }}</span>
        </div>
      </div>

      <div class="grid cols-2">
        <div class="card">
          <div class="card-title">取消运行 <span class="sub">API-16</span></div>
          <p class="dim">请求取消运行中/排队中的 Run；终态 Run 禁止取消（OPS-409）。</p>
          <div class="form-field" style="margin-bottom: 8px">
            <label>取消原因（必填）</label>
            <input v-model="cancelReason" type="text" :disabled="!can('run.ops') || terminal" placeholder="取消原因" />
          </div>
          <button class="btn danger" :disabled="!can('run.ops') || terminal || !cancelReason.trim()" @click="cancelOpen = true">取消运行</button>
        </div>

        <div class="card">
          <div class="card-title">受管回滚 <span class="sub">API-17 · 输入 ROLLBACK</span></div>
          <p class="dim">仅清理本 Run 影子表与临时资源；正式表零变更；错误表保留取证。</p>
          <button class="btn danger" :disabled="!can('run.ops') || run.status !== 'failed'" @click="rollbackOpen = true">执行回滚</button>
          <div class="tip-bar info mt-8">回滚预览接口待确认 P-20；前端不自行生成预览步骤。</div>
        </div>

        <div class="card">
          <div class="card-title">安全重跑 <span class="sub">待确认 P-20</span></div>
          <p class="dim">复用冻结版本，需重新 Prepare / Approve / Commit，禁止绕过审批。</p>
          <button class="btn" disabled>安全重跑（接口待确认）</button>
        </div>

        <div class="card">
          <div class="card-title">资源清理 <span class="sub">待确认 P-20</span></div>
          <p class="dim">清理本 Run 临时资源；按保留策略处置错误表与影子表。</p>
          <button class="btn" disabled>执行清理（接口待确认）</button>
        </div>
      </div>

      <div class="card">
        <div class="card-title">运维操作审计 <span class="sub">待确认 P-20 ops.audit</span></div>
        <AppState state="empty" title="运维操作审计接口待确认" text="ops.audit 未定义（Spec P-20）；不展示合成操作记录。" />
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

      <TypedConfirmInput
        :open="rollbackOpen"
        title="回滚"
        description="回滚仅清理本 Run 影子表与临时资源；正式表与历史分区零变更；错误表保留取证。输入 ROLLBACK 确认。"
        expected-word="ROLLBACK"
        :submitting="rolling"
        @confirm="doRollback"
        @cancel="rollbackOpen = false"
      />
    </template>
  </div>
</template>
