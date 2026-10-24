<script setup>
// 强二次确认：回滚需输入 ROLLBACK 且原因必填（Spec 6.12）。
// 服务端校验 confirmation 与 reason（OPS-422），前端仅做引导性校验。
import { ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, required: true },
  description: { type: String, default: '' },
  expectedWord: { type: String, default: 'ROLLBACK' },
  submitting: { type: Boolean, default: false },
})

const emit = defineEmits(['confirm', 'cancel'])

const typed = ref('')
const reason = ref('')

watch(
  () => props.open,
  (v) => {
    if (v) {
      typed.value = ''
      reason.value = ''
    }
  }
)

function submit() {
  emit('confirm', { confirmation: typed.value, reason: reason.value })
}
</script>

<template>
  <div v-if="open" class="modal-mask" @click.self="emit('cancel')">
    <div class="modal">
      <h3 class="d-title">{{ title }}</h3>
      <p v-if="description" class="dim">{{ description }}</p>
      <div class="form-grid">
        <div class="form-field">
          <label>输入 <span class="mono">{{ expectedWord }}</span> 以确认（区分大小写）<span class="req">*</span></label>
          <input v-model="typed" type="text" :placeholder="expectedWord" />
        </div>
        <div class="form-field">
          <label>操作原因（必填，仅服务端摘要留存）<span class="req">*</span></label>
          <textarea v-model="reason" placeholder="回滚原因"></textarea>
        </div>
      </div>
      <div class="btn-row" style="justify-content: flex-end">
        <button class="btn" :disabled="submitting" @click="emit('cancel')">取消</button>
        <button
          class="btn danger"
          :disabled="submitting || typed !== expectedWord || !reason.trim()"
          @click="submit"
        >
          {{ submitting ? '提交中…' : `确认${title}` }}
        </button>
      </div>
      <div v-if="typed && typed !== expectedWord" class="field-err">输入与 {{ expectedWord }} 不一致</div>
    </div>
  </div>
</template>
