// 统一 HTTP 适配层。HTTP 客户端选型待确认 P-34：当前为原生 fetch 最小实现。
// 契约约束（接口契约.md 2.1）：
//  - 所有请求带 Authorization、X-Correlation-Id；
//  - 写接口带 Idempotency-Key（API-05 例外；API-10 待确认，暂不强制）；
//  - 错误统一解析 {error_code, message, correlation_id, details}；
//  - 401 清除会话（登录页与认证机制待确认 P-26，由布局层显示重新登录门）。
import { useAuthStore } from '@/stores/auth'
import { useNoticeStore } from '@/stores/notice'
import { newCorrelationId, newIdempotencyKey } from '@/utils/idem'
import { ApiError } from '@/utils/errors'
import { resolveMock } from './mock'

const MOCK_ENABLED = import.meta.env.VITE_USE_MOCK !== 'false'
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')

// 写接口幂等豁免（契约 2.1：API-05 不要求；API-10 是否强制待确认）
const IDEMPOTENT_EXEMPT = new Set(['API-05', 'API-10'])

function buildQuery(query) {
  if (!query) return ''
  const q = new URLSearchParams()
  Object.entries(query).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  })
  const s = q.toString()
  return s ? `?${s}` : ''
}

async function handleResponse(res) {
  const text = await res.text()
  let payload = null
  try {
    payload = text ? JSON.parse(text) : null
  } catch {
    // 非 JSON 响应体不解析
  }
  if (res.ok) return payload
  const err = ApiError.fromResponse(res.status, payload)
  if (err.isAuth()) {
    useAuthStore().clearSession()
    useNoticeStore().push({ kind: 'error', text: err.friendly(), errorCode: err.errorCode })
  }
  throw err
}

export async function request({ apiId, method, path, query, body, formData, idempotent = true, idempotencyKey }) {
  if (MOCK_ENABLED) {
    const mock = resolveMock(apiId)
    if (mock) return mock({ apiId, method, path, query, body, formData, idempotencyKey })
  }

  // 绝对地址用于跨源直连（开发环境）；未配置时回退到 Vite 代理的相对路径。
  const url = `${API_BASE_URL}${path}${buildQuery(query)}`
  const headers = new Headers()
  const auth = useAuthStore()
  if (auth.state.token) headers.set('Authorization', auth.state.token)
  headers.set('X-Correlation-Id', newCorrelationId())

  const isWrite = method === 'POST' || method === 'PUT'
  if (isWrite && idempotent && !IDEMPOTENT_EXEMPT.has(apiId)) {
    headers.set('Idempotency-Key', idempotencyKey || newIdempotencyKey())
  }

  let payload
  if (formData) {
    payload = formData
  } else if (body !== undefined) {
    headers.set('Content-Type', 'application/json')
    payload = JSON.stringify(body)
  }

  let res
  try {
    res = await fetch(url, { method, headers, body: payload })
  } catch {
    // Transport failure (offline, DNS, connection reset) has no HTTP response.
    // Represent it as a client-side ApiError so pages can render the stale or
    // error state instead of receiving a raw TypeError. httpStatus 0 is an
    // internal marker only; it is never sent to or received from the API.
    throw new ApiError({
      httpStatus: 0,
      errorCode: null,
      message: 'network request failed',
      correlationId: null,
      details: {},
    })
  }
  const response = await handleResponse(res)
  return response
}

export const http = {
  get: (apiId, path, opts = {}) => request({ apiId, method: 'GET', path, ...opts }),
  post: (apiId, path, body, opts = {}) => request({ apiId, method: 'POST', path, body, ...opts }),
  put: (apiId, path, body, opts = {}) => request({ apiId, method: 'PUT', path, body, ...opts }),
}
