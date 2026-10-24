// mock 注册与响应工具。仅演示用：VITE_USE_MOCK !== 'false' 时接管请求，
// 模拟真实服务端语义（含错误码、状态机、审批约束）。真实联调时设为 false。
import { handlers } from './mockApi'
import { correlationId } from './db'

// 模拟网络与服务端处理时延（演示值，非业务配置）
const LATENCY_MIN_MS = 120
const LATENCY_MAX_MS = 420

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

export function latency() {
  const ms = LATENCY_MIN_MS + Math.floor(Math.random() * (LATENCY_MAX_MS - LATENCY_MIN_MS))
  return sleep(ms)
}

// 成功响应：契约统一信封 { data, correlation_id }
export function ok(data, cid = correlationId()) {
  return { data, correlation_id: cid }
}

// 失败响应：契约错误体 { error_code, message, correlation_id, details }
export function fail(status, errorCode, message, details = undefined) {
  const body = { error_code: errorCode, message, correlation_id: correlationId() }
  if (details !== undefined) body.details = details
  const err = new Error(message)
  err.status = status
  err.payload = body
  return err
}

// 按 apiId 解析 mock 处理器（API-01 ~ API-18 已定义接口）。
// 返回 async 包装：模拟网络时延，同步抛出的 fail() 转为 rejected promise。
export function resolveMock(apiId) {
  const h = handlers[apiId]
  if (!h) return null
  return async (ctx) => {
    await latency()
    const result = h(ctx)
    if (result === null || result === undefined) {
      throw fail(404, 'API-404', `mock 未匹配路径：${ctx.path}`)
    }
    return result
  }
}

// 契约分页结果包装（返回 { data, correlation_id } 内 data 形如 { items, page, page_size, total }）
export function paginate(all, page, pageSize) {
  const start = (page - 1) * pageSize
  return {
    items: all.slice(start, start + pageSize),
    page,
    page_size: pageSize,
    total: all.length,
  }
}

export function nextId(prefix) {
  return `${prefix}_${Date.now().toString(36)}${Math.floor(Math.random() * 46656).toString(36)}`
}
