<script setup>
// 环形分布图：手写 SVG（图表库选型待确认 P-34）。
// 仅接收服务端返回的分布数据（如连接类型覆盖），不做前端聚合。
import { computed } from 'vue'
import { statusColor } from '@/utils/status'

const props = defineProps({
  items: { type: Array, required: true }, // [{name, count}]
  size: { type: Number, default: 150 },
  stroke: { type: Number, default: 22 },
})

const total = computed(() => props.items.reduce((a, x) => a + (Number(x.count) || 0), 0))
const r = computed(() => (props.size - props.stroke) / 2)
const c = computed(() => 2 * Math.PI * r.value)

const segments = computed(() => {
  if (!total.value) return []
  let acc = 0
  return props.items.map((x, i) => {
    const frac = (Number(x.count) || 0) / total.value
    const seg = {
      ...x,
      dash: `${frac * c.value} ${c.value}`,
      offset: -acc * c.value,
      color: `var(--${['ok', 'run', 'warn', 'danger', 'gray'][i % 5]})`,
    }
    acc += frac
    return seg
  })
})

const centerLabel = computed(() => {
  const { items } = props
  if (!items.length) return { big: '0', small: '无数据' }
  return { big: String(total.value), small: '总计' }
})

const half = computed(() => props.size / 2)
const rotate = computed(() => `rotate(-90 ${half.value} ${half.value})`)
</script>

<template>
  <div class="donut-row">
    <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`">
      <circle :cx="half" :cy="half" :r="r" fill="none" stroke="var(--line)" :stroke-width="stroke" />
      <circle
        v-for="(s, i) in segments"
        :key="i"
        :cx="half"
        :cy="half"
        :r="r"
        fill="none"
        :stroke="s.color"
        :stroke-width="stroke"
        :stroke-dasharray="s.dash"
        :stroke-dashoffset="s.offset"
        :transform="rotate"
      />
      <text :x="half" :y="half - 4" text-anchor="middle" fill="var(--text)" font-size="20" font-weight="600">{{ centerLabel.big }}</text>
      <text :x="half" :y="half + 16" text-anchor="middle" fill="var(--text-faint)" font-size="11">{{ centerLabel.small }}</text>
    </svg>
    <div class="donut-legend">
      <div v-for="(s, i) in items" :key="i" class="lg">
        <span class="sw" :style="{ background: `var(--${['ok', 'run', 'warn', 'danger', 'gray'][i % 5]})` }"></span>
        {{ s.name }}：{{ s.count }}
      </div>
    </div>
  </div>
</template>
