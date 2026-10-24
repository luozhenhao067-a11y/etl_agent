<script setup>
// 二次确认弹窗：Ops 高危操作（取消/清理/重跑）统一入口。
defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, required: true },
  message: { type: String, default: '' },
  confirmText: { type: String, default: '确认' },
  danger: { type: Boolean, default: false },
  submitting: { type: Boolean, default: false },
})

const emit = defineEmits(['confirm', 'cancel'])
</script>

<template>
  <div v-if="open" class="modal-mask" @click.self="emit('cancel')">
    <div class="modal">
      <h3 class="d-title">{{ title }}</h3>
      <p v-if="message" class="dim">{{ message }}</p>
      <div class="btn-row" style="justify-content: flex-end">
        <button class="btn" :disabled="submitting" @click="emit('cancel')">取消</button>
        <button class="btn" :class="danger ? 'danger' : 'primary'" :disabled="submitting" @click="emit('confirm')">
          {{ submitting ? '提交中…' : confirmText }}
        </button>
      </div>
    </div>
  </div>
</template>
