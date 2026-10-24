<script setup>
// 密钥状态徽标：仅展示状态，绝不展示密钥/密码明文（Spec 12.3、禁止事项）。
defineProps({
  state: { type: String, default: 'unknown' }, // configured|not_configured|unknown
})
</script>

<template>
  <span class="badge" :class="state === 'configured' ? 'ok' : state === 'not_configured' ? 'danger' : 'gray'">
    {{ state === 'configured' ? '已配置' : state === 'not_configured' ? '未配置' : '未知' }}
  </span>
</template>
