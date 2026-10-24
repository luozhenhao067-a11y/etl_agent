<script setup>
// DAG 容器：手写 SVG 渲染（图形库选型待确认 P-34）。
// 只渲染服务端返回的节点/边；不做前端图计算。
import { computed } from 'vue'

const props = defineProps({
  nodes: { type: Array, required: true }, // [label]
  edges: { type: Array, default: () => [] }, // [{from: idx, to: idx}]
})

const NODE_W = 150
const NODE_H = 44
const GAP_X = 40
const GAP_Y = 70
const PAD = 20

const layout = computed(() =>
  props.nodes.map((label, i) => ({
    label,
    x: PAD + i * (NODE_W + GAP_X),
    y: PAD + (i % 2) * (NODE_H + GAP_Y),
  }))
)

const width = computed(() => PAD * 2 + props.nodes.length * (NODE_W + GAP_X) - GAP_X)
const height = computed(() => PAD * 2 + (props.nodes.length > 1 ? 2 * NODE_H + GAP_Y : NODE_H))

function edgePoints(e) {
  const a = layout.value[e.from]
  const b = layout.value[e.to]
  if (!a || !b) return null
  const x1 = a.x + NODE_W
  const y1 = a.y + NODE_H / 2
  const x2 = b.x
  const y2 = b.y + NODE_H / 2
  const mx = (x1 + x2) / 2
  return `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`
}
</script>

<template>
  <svg :width="width" :height="height" :viewBox="`0 0 ${width} ${height}`" style="max-width: 100%; height: auto">
    <defs>
      <marker id="dag-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--text-dim)" />
      </marker>
    </defs>
    <path
      v-for="(e, i) in edges"
      :key="i"
      :d="edgePoints(e)"
      fill="none"
      stroke="var(--text-dim)"
      stroke-width="1.5"
      marker-end="url(#dag-arrow)"
    />
    <g v-for="(n, i) in layout" :key="i">
      <rect :x="n.x" :y="n.y" :width="NODE_W" :height="NODE_H" rx="8" fill="var(--card-2)" stroke="var(--accent)" stroke-width="1" />
      <text :x="n.x + NODE_W / 2" :y="n.y + NODE_H / 2 + 4" text-anchor="middle" fill="var(--text)" font-size="12">{{ n.label }}</text>
    </g>
  </svg>
</template>
