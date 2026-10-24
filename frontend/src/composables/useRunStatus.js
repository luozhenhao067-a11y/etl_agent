import { onBeforeUnmount, ref } from 'vue'
import { apiExecutions } from '@/api/executions'

// 执行状态刷新适配层（Spec P-16 待确认：轮询 vs 订阅未定稿）。
// 当前默认实现为轮询占位（间隔 3s，仅演示用，最终方案待确认）。
// 页面只依赖 start / stop / reconnect 与回调；确认订阅方案后
// 替换 createRunStatusAdapter 的返回值即可，页面无需改动。

const DEFAULT_INTERVAL_MS = 3000
const STALE_AFTER_FAILURES = 2

export function createRunStatusAdapter() {
  // 轮询适配器（默认占位实现）
  return {
    subscribe(runId, { onUpdate, intervalMs = DEFAULT_INTERVAL_MS }) {
      let timer = null
      let stopped = false
      let failures = 0
      let lastSnapshot = null

      async function tick() {
        if (stopped) return
        try {
          const res = await apiExecutions.getRun(runId)
          failures = 0
          lastSnapshot = res.data
          onUpdate({ snapshot: res.data, stale: false, logDisconnected: false, correlationId: res.correlation_id })
        } catch (err) {
          failures += 1
          const stale = failures >= STALE_AFTER_FAILURES
          // 连续失败视为连接中断：保留最后位置，停止轮询，等待手动重连
          onUpdate({ snapshot: lastSnapshot, stale, logDisconnected: stale, error: err })
          if (stale) return
        }
        timer = setTimeout(tick, intervalMs)
      }

      tick()
      return {
        stop() {
          stopped = true
          if (timer) clearTimeout(timer)
        },
        reconnect() {
          failures = 0
          tick()
        },
      }
    },
  }
}

export function useRunStatus(runId, options = {}) {
  const adapter = createRunStatusAdapter()
  const snapshot = ref(null)
  const stale = ref(false)
  const logDisconnected = ref(false)
  const lastError = ref(null)
  let handle = null
  let currentId = null

  // runId 可为 ref 或字符串；start 可显式传 id 覆盖
  function resolveId(id) {
    if (id !== undefined && id !== null) return id
    return runId && typeof runId === 'object' && 'value' in runId ? runId.value : runId
  }

  function start(id) {
    stop()
    const rid = resolveId(id)
    if (!rid) return
    // Switching to another Run must drop the previous snapshot. Otherwise a
    // failed lookup of the new id would keep showing the old run as if it had
    // succeeded. Refreshing the same run keeps the snapshot so the stale state
    // can still show the last known data.
    if (rid !== currentId) {
      currentId = rid
      snapshot.value = null
    }
    stale.value = false
    logDisconnected.value = false
    lastError.value = null
    handle = adapter.subscribe(rid, {
      intervalMs: options.intervalMs,
      onUpdate({ snapshot: snap, stale: s, logDisconnected: ld, error }) {
        if (snap) snapshot.value = snap
        stale.value = s
        logDisconnected.value = ld
        lastError.value = error || null
      },
    })
  }

  function stop() {
    if (handle) {
      handle.stop()
      handle = null
    }
  }

  function reconnect() {
    start()
  }

  onBeforeUnmount(stop)

  return { snapshot, stale, logDisconnected, lastError, start, stop, reconnect }
}
