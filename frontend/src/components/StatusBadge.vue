<script setup>
// 状态徽标：成功绿 / 运行中蓝 / 待审批橙 / 失败高风险红 / 禁用灰（Spec 7.x）。
// 状态枚举待确认 P-35；映射见 utils/status.js。
import { statusColor, statusLabel } from '@/utils/status'

const props = defineProps({
  status: { type: [String, null], default: null },
  label: { type: String, default: '' },
})
</script>

<template>
  <span class="badge" :class="statusColor(props.status)">
    {{ label || statusLabel(props.status) }}
  </span>
</template>
