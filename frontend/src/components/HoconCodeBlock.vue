<script setup>
// HOCON 语法高亮：手写分词（高亮库选型待确认 P-34）。
// 输入先整体 HTML 转义，再按 注释/字符串/键/数字 顺序着色，杜绝注入。
import { computed } from 'vue'

const props = defineProps({
  code: { type: String, default: '' },
})

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

const TOKEN_RE = /(\/\/.*$)|(#.*$)|("(?:[^"\\]|\\.)*")|(^[ \t]*[A-Za-z0-9_.-]+(?=[ \t]*[:=]))|(\b\d+(?:\.\d+)?\b)/gm

const highlighted = computed(() =>
  escapeHtml(props.code).replace(TOKEN_RE, (m, comment, hashComment, str, key, num) => {
    if (comment !== undefined || hashComment !== undefined) return `<span class="hc">${m}</span>`
    if (str !== undefined) return `<span class="hs">${m}</span>`
    if (key !== undefined) return `<span class="hk">${m}</span>`
    return `<span class="hn">${m}</span>`
  })
)
</script>

<template>
  <pre class="hocon" v-html="highlighted"></pre>
</template>
