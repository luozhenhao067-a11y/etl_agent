<script setup>
// 确定性门禁 4 项清单（Spec 6.8）：语法 / 结构映射 / 脱敏 / 预算。
// 4/4 通过才可冻结版本。结果来自服务端 gate_result，前端不自行判定。
import { computed } from 'vue'

const props = defineProps({
  items: { type: Array, required: true }, // [{key, name, status: passed|failed|todo, note}]
})

const passedCount = computed(() => props.items.filter((x) => x.status === 'passed').length)
const allPassed = computed(() => props.items.length > 0 && passedCount.value === props.items.length)

const nameOf = (key) => ({ syntax: 'HOCON 语法校验', schema: '结构映射校验', masking: '脱敏规则校验', budget: '预算监督校验' }[key] || key)
</script>

<template>
  <div>
    <ul class="gate-checklist">
      <li v-for="(g, i) in items" :key="i">
        <span class="g-state">{{ g.status === 'passed' ? '✅' : g.status === 'failed' ? '❌' : '⏳' }}</span>
        <span class="g-name">{{ nameOf(g.key) || g.name }}</span>
        <span class="g-note">{{ g.note || (g.status === 'passed' ? '通过' : g.status === 'failed' ? '未通过' : '未执行') }}</span>
      </li>
    </ul>
    <div class="mt-8">
      <span class="badge" :class="allPassed ? 'ok' : 'pending'">门禁 {{ passedCount }}/{{ items.length }}</span>
      <span class="faint" style="margin-left: 8px; font-size: 12px">4/4 通过方可冻结版本</span>
    </div>
  </div>
</template>
