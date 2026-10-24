<script setup>
// 日志查看器（P-23 实时日志流占位）：轮询断开 2 次连续失败进入 log-disconnected，
// 显示重连按钮（useRunStatus 适配层 P-16）。日志均已脱敏，禁止渲染密钥。
import { ref, watch, nextTick } from 'vue'

const props = defineProps({
  lines: { type: Array, default: () => [] }, // string[]
  connected: { type: Boolean, default: true },
  lastError: { type: Object, default: null },
})

defineEmits(['reconnect'])

const box = ref(null)

watch(
  () => props.lines.length,
  async () => {
    await nextTick()
    if (box.value) box.value.scrollTop = box.value.scrollHeight
  }
)

function lineClass(line) {
  if (/error|failed|breach/i.test(line)) return 'err'
  if (/warn/i.test(line)) return 'warn'
  return ''
}
</script>

<template>
  <div>
    <div v-if="!connected" class="log-offline-banner">
      <span>日志连接已断开（连续失败）</span>
      <span class="faint" v-if="lastError">{{ lastError.friendly() }}</span>
      <button class="btn sm" @click="$emit('reconnect')">重新连接</button>
    </div>
    <div ref="box" class="log-viewer">
      <div v-if="!lines.length" class="dim">暂无日志</div>
      <div v-for="(l, i) in lines" :key="i" class="log-line" :class="lineClass(l)">{{ l }}</div>
    </div>
  </div>
</template>
