<script setup>
// 步骤时间线：LangGraph 生成步骤 / 诊断根因链通用渲染。
defineProps({
  items: { type: Array, required: true }, // [{title, status: done|running|failed|interrupted|todo, detail, time}]
})
</script>

<template>
  <div class="timeline">
    <div v-for="(s, i) in items" :key="i" class="t-item" :class="s.status">
      <div class="t-title">
        {{ s.title }}
        <span v-if="s.time" class="t-time">{{ s.time }}</span>
      </div>
      <div v-if="s.detail" class="t-detail">{{ s.detail }}</div>
    </div>
  </div>
</template>
