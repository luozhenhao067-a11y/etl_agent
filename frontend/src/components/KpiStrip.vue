<script setup>
// KPI 指标条：label/value/unit/note。数值均为服务端聚合结果（或 mock 聚合），
// 前端页面不得自行聚合海量数据（Spec P-19）。
defineProps({
  items: { type: Array, required: true }, // [{label, value, unit, note}]
})
</script>

<template>
  <div class="kpi-strip">
    <div v-for="(k, i) in items" :key="i" class="kpi">
      <div class="kpi-label">{{ k.label }}</div>
      <div class="kpi-value">{{ k.value }}<small v-if="k.unit">{{ k.unit }}</small></div>
      <div v-if="k.note" class="kpi-note">{{ k.note }}</div>
    </div>
  </div>
</template>
