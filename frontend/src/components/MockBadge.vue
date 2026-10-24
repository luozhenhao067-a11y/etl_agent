<script setup>
// 演示数据徽标：仅 mock 模式显示。合成示例已脱敏，不得视为业务默认值。
const MOCK_ENABLED = import.meta.env.VITE_USE_MOCK !== 'false'
</script>

<template>
  <span v-if="MOCK_ENABLED" class="mock-badge" title="当前数据来自演示 mock（已脱敏合成示例）">演示数据</span>
</template>
