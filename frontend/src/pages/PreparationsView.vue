<script setup>
// 本页 API：API-13（审批决策）、API-14（Ops Commit）。
// 缺失接口 P-19 preparations.list / preparations.detail / approvals.list：
// 前端不聚合、不伪造准备单列表；只在空态中标注“待确认”，并提供按单号直接操作的入口。
// API-13/14 请求体 idempotency_key 与请求头一致，由 API 适配层生成。
// 审批按服务端职责槽校验；申请人自批返回 APR-403，Commit 仅 Ops。
import { ref, computed } from 'vue'
import { apiPreparations } from '@/api/preparations'
import { usePermission } from '@/composables/usePermission'
import { useNoticeStore } from '@/stores/notice'
import AppState from '@/components/AppState.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import PermissionBar from '@/components/PermissionBar.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import MockBadge from '@/components/MockBadge.vue'

const { can } = usePermission()
const notice = useNoticeStore()

const canApprove = computed(() => can('approval.data') || can('approval.security'))
const approvalAction = computed(() => (can('approval.data') ? 'approval.data' : 'approval.security'))

// ---- API-13 审批决策 ----
const decisionForm = ref({ approvalId: '', decision: 'approve', opinion: '' })
const deciding = ref(false)
const decisionError = ref(null)
const decisionResult = ref(null)

async function submitDecision() {
  deciding.value = true
  decisionError.value = null
  decisionResult.value = null
  try {
    const res = await apiPreparations.decide(decisionForm.value.approvalId.trim(), {
      decision: decisionForm.value.decision,
      opinion: decisionForm.value.opinion || undefined,
    })
    decisionResult.value = res.data
    notice.push({ kind: 'success', text: `审批决策已记录：${res.data.status}（API-13）` })
  } catch (e) {
    decisionError.value = e
    notice.push({ kind: 'error', text: e.friendly(), errorCode: e.errorCode, correlationId: e.correlationId })
  } finally {
    deciding.value = false
  }
}

// ---- API-14 Commit（仅 Ops，二次确认） ----
const commitForm = ref({ preparationId: '' })
const commitConfirmOpen = ref(false)
const committing = ref(false)
const commitError = ref(null)
const commitResult = ref(null)

async function doCommit() {
  committing.value = true
  commitError.value = null
  commitResult.value = null
  try {
    const res = await apiPreparations.commit(commitForm.value.preparationId.trim(), {})
    commitResult.value = res.data
    commitConfirmOpen.value = false
    notice.push({ kind: 'success', text: `已提交执行：${res.data.execution_run_id}（API-14）` })
  } catch (e) {
    commitError.value = e
    notice.push({ kind: 'error', text: e.friendly(), errorCode: e.errorCode, correlationId: e.correlationId })
  } finally {
    committing.value = false
  }
}
</script>

<template>
  <div>
    <div class="flex items-center gap-8 wrap mb-16">
      <h2 style="margin: 0; font-size: 17px">变更准备</h2>
      <MockBadge />
    </div>

    <div class="card">
      <div class="card-title">准备单列表 <span class="sub">待确认 P-19</span></div>
      <AppState
        state="empty"
        title="准备单列表 / 详情接口待确认"
        text="缺少 preparations.list、preparations.detail、approvals.list（Spec P-19）；前端不聚合、不展示合成准备单。可在下方按单号直接发起 API-13 / API-14。"
      />
    </div>

    <div class="grid cols-2">
      <div class="card">
        <div class="card-title">审批决策 <span class="sub">API-13</span></div>
        <PermissionBar :action="approvalAction" />
        <div class="tip-bar warn">
          服务端按审批单 required_role 与职责槽校验；申请人自批返回 APR-403，同一人占用多个职责槽返回 APR-409。
        </div>
        <div class="form-grid">
          <div class="form-field">
            <label>审批单号 <span class="req">*</span></label>
            <input v-model="decisionForm.approvalId" type="text" placeholder="如 apr_demo_001" :disabled="!canApprove || deciding" />
          </div>
          <div class="form-field">
            <label>决策</label>
            <select v-model="decisionForm.decision" :disabled="!canApprove || deciding">
              <option value="approve">approve</option>
              <option value="reject">reject</option>
            </select>
          </div>
          <div class="form-field">
            <label>意见</label>
            <textarea v-model="decisionForm.opinion" :disabled="!canApprove || deciding" placeholder="审批意见（仅服务端摘要留存）"></textarea>
          </div>
        </div>
        <div v-if="decisionError" class="field-err mt-8">
          {{ decisionError.friendly() }}（{{ decisionError.errorCode }}）
          <template v-if="decisionError.correlationId"> · {{ decisionError.correlationId }}</template>
        </div>
        <div v-if="decisionResult" class="fact-list mt-8">
          <span class="fk">approval_id</span><span class="fv">{{ decisionResult.approval_id }}</span>
          <span class="fk">status</span><span class="fv"><StatusBadge :status="decisionResult.status" /></span>
          <span class="fk">next_slot_status</span><span class="fv">{{ decisionResult.next_slot_status }}</span>
          <span class="fk">decided_at</span><span class="fv">{{ decisionResult.decided_at }}</span>
        </div>
        <div class="btn-row mt-8">
          <button v-if="canApprove" class="btn primary" :disabled="deciding || !decisionForm.approvalId.trim()" @click="submitDecision">
            {{ deciding ? '提交中…' : '提交决策' }}
          </button>
        </div>
      </div>

      <div class="card">
        <div class="card-title">提交执行 <span class="sub">API-14 · 仅 Ops</span></div>
        <PermissionBar action="run.commit" />
        <div class="tip-bar warn">
          服务端校验审批 2/2、职责分离与冻结指纹；Capability 明文不返回、不展示。依赖未就绪时返回 503。
        </div>
        <div class="form-grid">
          <div class="form-field">
            <label>准备单号 <span class="req">*</span></label>
            <input v-model="commitForm.preparationId" type="text" placeholder="如 prep_demo_005" :disabled="!can('run.commit') || committing" />
          </div>
        </div>
        <div v-if="commitError" class="field-err mt-8">
          {{ commitError.friendly() }}（{{ commitError.errorCode }}）
          <template v-if="commitError.correlationId"> · {{ commitError.correlationId }}</template>
        </div>
        <div v-if="commitResult" class="fact-list mt-8">
          <span class="fk">execution_run_id</span><span class="fv">{{ commitResult.execution_run_id }}</span>
          <span class="fk">status</span><span class="fv">{{ commitResult.status }}</span>
          <span class="fk">capability_digest</span><span class="fv">{{ commitResult.capability_digest }}</span>
          <span class="fk">committed_at</span><span class="fv">{{ commitResult.committed_at }}</span>
        </div>
        <div class="btn-row mt-8">
          <button v-if="can('run.commit')" class="btn primary" :disabled="committing || !commitForm.preparationId.trim()" @click="commitConfirmOpen = true">提交执行（二次确认）</button>
        </div>
      </div>
    </div>

    <ConfirmDialog
      :open="commitConfirmOpen"
      title="提交执行"
      :message="`将校验准备单 ${commitForm.preparationId} 的审批 2/2 与冻结指纹，签发 Capability 并派发执行。确认提交？`"
      confirm-text="确认提交"
      :submitting="committing"
      @confirm="doCommit"
      @cancel="commitConfirmOpen = false"
    />
  </div>
</template>
