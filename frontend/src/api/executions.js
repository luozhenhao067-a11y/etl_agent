import { http } from './http'
import { newIdempotencyKey } from '@/utils/idem'

// API-15 GET /api/v1/execution-runs/{id} —— 查询执行状态、指标与质量报告（项目成员只读）
// API-16 POST /api/v1/execution-runs/{id}/cancel —— 请求取消运行（仅 Ops；Idempotency-Key 必填）
// API-17 POST /api/v1/execution-runs/{id}/rollback —— 受管影子表回滚（仅 Ops；confirmation=ROLLBACK）
// API-16/17 请求体 idempotency_key 必须与请求头一致。
function keyedPost(apiId, path, body) {
  const idempotencyKey = newIdempotencyKey()
  return http.post(apiId, path, { ...body, idempotency_key: idempotencyKey }, { idempotencyKey })
}

export const apiExecutions = {
  getRun(id) {
    return http.get('API-15', `/api/v1/execution-runs/${id}`)
  },
  cancel(id, body) {
    return keyedPost('API-16', `/api/v1/execution-runs/${id}/cancel`, body)
  },
  rollback(id, body) {
    return keyedPost('API-17', `/api/v1/execution-runs/${id}/rollback`, body)
  },
}
