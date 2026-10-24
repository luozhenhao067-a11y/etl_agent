import { http } from './http'

// API-09 POST /api/v1/versions/{version_id}/generation —— 触发 LangGraph 候选生成
// Maker；Idempotency-Key 必填；同一 thread 并发生成拒绝（GEN-409）
// API-10 POST /api/v1/agent-runs/{run_id}/answers —— 提交澄清回答，恢复状态机
// Maker（运行发起人）；Idempotency-Key 是否强制待确认（契约 2.1，暂不带）
export const apiGeneration = {
  generate(versionId, body) {
    return http.post('API-09', `/api/v1/versions/${versionId}/generation`, body)
  },
  answer(runId, body) {
    return http.post('API-10', `/api/v1/agent-runs/${runId}/answers`, body)
  },
}
