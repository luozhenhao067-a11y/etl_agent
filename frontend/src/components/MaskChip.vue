<script setup>
// 掩码值徽标：仅用于展示已脱敏值（Spec 12.3）。
// 调用方必须先经 utils/mask.js 掩码；本组件不承接明文。
defineProps({
  value: { type: [String, Number], default: '***' },
})
</script>

<template>
  <span class="mask-chip">{{ value }}</span>
</template>
