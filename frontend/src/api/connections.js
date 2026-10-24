import { http } from './http'

// API-02 GET /api/v1/projects/{project_id}/connections —— 查询项目数据源连接列表
// API-03 POST /api/v1/connections —— 创建数据源连接（Maker；Idempotency-Key）
// API-04 PUT /api/v1/connections/{id} —— 编辑数据源连接（Maker；Idempotency-Key）
// API-05 POST /api/v1/connections/{id}/tests —— 测试数据源连通性（Maker；无强制幂等键）
export const apiConnections = {
  list(projectId, query) {
    return http.get('API-02', `/api/v1/projects/${projectId}/connections`, { query })
  },
  create(body) {
    return http.post('API-03', '/api/v1/connections', body)
  },
  update(id, body) {
    return http.put('API-04', `/api/v1/connections/${id}`, body)
  },
  test(id, body = {}) {
    return http.post('API-05', `/api/v1/connections/${id}/tests`, body)
  },
}
