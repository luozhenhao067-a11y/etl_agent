<script setup>
// 独立审批卡（Spec 6.10）：每张卡对应一个审批单据，按 required_role 展示职责槽。
// 职责分离：两名 Checker 独立决策；申请人按钮禁用并提示“申请人禁止自批”。
// 审批意见仅存服务端并摘要展示（opinion_digest），前端不回显明文意见。
import { ref, computed } from 'vue'
import StatusBadge from './StatusBadge.vue'

const props = defineProps({
  approval: { type: Object, required: true }, // {approval_id, required_role, status, decision, decided_at, opinion_digest}
  applicantId: { type: String, default: '' },
  currentUserId: { type: String, default: '' },
  canDecide: { type: Boolean, default: false },
  deciding: { type: Boolean, default: false },
})

const emit = defineEmits(['decide'])

const roleLabel = (slot) => (slot === 'data_checker' ? '数据审批人（Checker 1）' : slot === 'security_checker' ? '安全审批人（Checker 2）' : slot)

const isSelf = computed(() => Boolean(props.applicantId && props.currentUserId && props.applicantId === props.currentUserId))

const opinion = ref('')

function decide(decision) {
  emit('decide', { approvalId: props.approval.approval_id, decision, opinion: opinion.value })
  opinion.value = ''
}
</script>

<template>
  <div class="approval-card">
    <div class="ac-head">
      <strong>{{ roleLabel(approval.required_role) }}</strong>
      <StatusBadge :status="approval.status" />
      <span class="faint mono">{{ approval.approval_id }}</span>
      <span class="right">
        <button v-if="canDecide && !approval.decision" class="btn sm" :disabled="deciding" @click="decide('approve')">
          {{ deciding ? '提交中…' : '批准' }}
        </button>
        <button v-if="canDecide && !approval.decision" class="btn sm danger" :disabled="deciding" @click="decide('reject')">驳回</button>
      </span>
    </div>

    <div v-if="approval.decision" class="dim">
      决策：{{ approval.decision === 'approve' ? '批准' : '驳回' }} · {{ approval.decided_at }}
      <span v-if="approval.opinion_digest" class="mask-chip">{{ approval.opinion_digest }}</span>
    </div>

    <div v-if="isSelf && !approval.decision" class="tip-bar warn mt-8">申请人禁止自批（职责分离）</div>
    <div v-else-if="!canDecide && !approval.decision" class="disabled-hint">仅对应职责槽审批人可决策</div>

    <div v-if="canDecide && !approval.decision" class="mt-8">
      <div class="form-field">
        <label>审批意见（可选，仅服务端摘要留存，不回显明文）</label>
        <input v-model="opinion" type="text" placeholder="意见仅存服务端" />
      </div>
    </div>
  </div>
</template>
