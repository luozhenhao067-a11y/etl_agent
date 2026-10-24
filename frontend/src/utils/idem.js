// 链路 ID 与幂等键生成（契约 2.1）。
// X-Correlation-Id 客户端生成；Idempotency-Key 写接口必填（API-05 例外、API-10 待确认）。

function randomHex() {
  if (globalThis.crypto && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID().replace(/-/g, '')
  }
  let s = ''
  for (let i = 0; i < 32; i += 1) s += Math.floor(Math.random() * 16).toString(16)
  return s
}

export function newCorrelationId() {
  return `corr_${randomHex().slice(0, 16)}`
}

export function newIdempotencyKey() {
  return `idem_${randomHex().slice(0, 16)}`
}

export function newThreadId() {
  return `thread_${randomHex().slice(0, 16)}`
}
