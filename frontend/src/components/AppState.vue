<script setup>
// 页面状态：loading / empty / partial / error / forbidden / stale；列表附加 filtered-empty。
// partial = 部分接口失败（Spec 6.1），其余数据仍可展示。
// 错误一律脱敏展示（不渲染堆栈/主机/密钥），correlation_id 供排障引用。
import { computed } from 'vue'

const props = defineProps({
  state: { type: String, required: true }, // loading|empty|partial|error|forbidden|stale|filtered-empty
  title: { type: String, default: '' },
  text: { type: String, default: '' },
  error: { type: Object, default: null }, // ApiError
  retry: { type: Function, default: null },
})

// 兜底非 ApiError，避免状态组件本身抛错导致整页渲染中止。
const errorText = computed(() =>
  typeof props.error?.friendly === 'function' ? props.error.friendly() : '请求失败',
)
</script>

<template>
  <div class="state-box" :class="{ error: state === 'error', forbidden: state === 'forbidden', stale: state === 'stale' }">
    <div class="state-icon">
      <div v-if="state === 'loading'" class="spinner"></div>
      <template v-else-if="state === 'empty'">📭</template>
      <template v-else-if="state === 'partial'">📦</template>
      <template v-else-if="state === 'error'">⚠</template>
      <template v-else-if="state === 'forbidden'">🔒</template>
      <template v-else-if="state === 'stale'">📡</template>
      <template v-else-if="state === 'filtered-empty'">🔍</template>
    </div>
    <div>
      {{ title || (state === 'loading' ? '加载中…' : state === 'empty' ? '暂无数据' : state === 'partial' ? '部分数据不可用' : state === 'error' ? '加载失败' : state === 'forbidden' ? '无访问权限' : state === 'stale' ? '数据已过期' : '筛选结果为空') }}
    </div>
    <div v-if="text" class="faint">{{ text }}</div>
    <div v-if="error" class="faint">{{ errorText }}</div>
    <div v-if="error && error.correlationId" class="corr-id">correlation_id: {{ error.correlationId }}</div>
    <button v-if="retry" class="btn" @click="retry">重试</button>
  </div>
</template>
