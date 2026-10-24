<script setup>
// 字段级 Diff（Spec 6.7）：相对基线版本的变化。值均来自服务端设计结果。
defineProps({
  baseVersion: { type: String, default: '—' },
  rows: { type: Array, required: true }, // [{field, before, after, change: add|modify|del|same}]
})

const changeLabel = (c) => ({ add: '新增处理', modify: '变更', del: '移除', same: '不变' }[c] || c)
</script>

<template>
  <div>
    <div class="form-hint mb-16">相对基线版本：<span class="mono">{{ baseVersion }}</span></div>
    <div class="table-wrap">
      <table class="diff-table">
        <thead>
          <tr><th>字段</th><th>基线</th><th>当前</th><th>变化</th></tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in rows" :key="i">
            <td class="mono">{{ r.field }}</td>
            <td class="dim">{{ r.before }}</td>
            <td class="mono">{{ r.after }}</td>
            <td :class="`change-${r.change}`">{{ changeLabel(r.change) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
