<script setup>
// 条形分布列表：手写 CSS 条（图表库选型待确认 P-34）。
// 仅接收服务端聚合结果，不做前端聚合。
import { computed } from 'vue'
import { statusColor } from '@/utils/status'

const props = defineProps({
  items: { type: Array, required: true }, // [{name, count}]
})

const max = computed(() => Math.max(1, ...props.items.map((x) => Number(x.count) || 0)))
</script>

<template>
  <div class="bar-list">
    <div v-for="(x, i) in items" :key="i" class="bar-row">
      <span class="b-label" :title="x.name">{{ x.name }}</span>
      <span class="b-track"><span :style="{ width: `${((Number(x.count) || 0) / max) * 100}%`, background: `var(--${statusColor(x.name) === 'gray' ? ['ok', 'run', 'warn', 'danger'][i % 4] : statusColor(x.name)})` }"></span></span>
      <span class="b-val">{{ x.count }}</span>
    </div>
  </div>
</template>
