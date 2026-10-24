<script setup>
// 预算/进度条：>=90% 预警橙，>=100% 越线红。
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [Number, String], default: 0 }, // 百分比数值 0-100+
  valueText: { type: String, default: '' },
})

const pct = computed(() => Math.min(100, Math.max(0, Number(props.value) || 0)))
const tone = computed(() => (Number(props.value) >= 100 ? 'danger' : Number(props.value) >= 90 ? 'warn' : ''))
</script>

<template>
  <div class="progress-row">
    <span class="p-label">{{ label }}</span>
    <div class="progress" :class="tone"><span :style="{ width: `${pct}%` }"></span></div>
    <span class="p-val">{{ valueText || `${value}%` }}</span>
  </div>
</template>
