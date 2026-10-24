import { http } from './http'

// API-06 POST /api/v1/connections/{id}/profiles —— 发起只读元数据探查与脱敏样本采集
// Maker；readonly 必须为 true；Idempotency-Key 必填
export const apiProfiles = {
  run(id, body) {
    return http.post('API-06', `/api/v1/connections/${id}/profiles`, body)
  },
}
