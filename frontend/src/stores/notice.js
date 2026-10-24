import { reactive } from 'vue'

// 全局轻量提示。状态管理库选型待确认 P-34：当前为最小 reactive 实现。

const state = reactive({ items: [] })
let seq = 0

export function useNoticeStore() {
  function push(item) {
    const id = ++seq
    state.items.push({
      id,
      kind: item.kind || 'info',
      text: item.text,
      errorCode: item.errorCode || null,
      correlationId: item.correlationId || null,
      retry: item.retry || null,
    })
    setTimeout(() => dismiss(id), 8000)
    return id
  }

  function dismiss(id) {
    const i = state.items.findIndex((x) => x.id === id)
    if (i > -1) state.items.splice(i, 1)
  }

  return { state, push, dismiss }
}
