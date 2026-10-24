<script setup>
// PDP 风险等级徽标：P0/P1 红、P2 橙、P3 灰（高风险红，Spec 7.x）。
const props = defineProps({
  level: { type: String, required: true }, // P0|P1|P2|P3
})
const label = (l) => ({ P0: 'P0 高危', P1: 'P1 高风险', P2: 'P2 中风险', P3: 'P3 低风险' }[l] || l)
</script>

<template>
  <span class="badge" :class="`risk-${String(props.level).toLowerCase()}`">{{ label(props.level) }}</span>
</template>
