import { http } from './http'

// API-08 POST /api/v1/pipelines —— 创建 Pipeline 项目定义（Maker；Idempotency-Key）
export const apiPipelines = {
  create(body) {
    return http.post('API-08', '/api/v1/pipelines', body)
  },
}
