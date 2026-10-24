import { http } from './http'
import { newIdempotencyKey } from '@/utils/idem'

// API-18 POST /api/v1/benchmarks/run —— 触发自动化安全与准确率 Benchmark 评测
// 仅 Checker 2；Idempotency-Key 必填；同套件同层并发拒绝（BENCH-409）
// 请求体 idempotency_key 必须与请求头一致。
export const apiBenchmarks = {
  run(body) {
    const idempotencyKey = newIdempotencyKey()
    return http.post(
      'API-18',
      '/api/v1/benchmarks/run',
      { ...body, idempotency_key: idempotencyKey },
      { idempotencyKey },
    )
  },
}
