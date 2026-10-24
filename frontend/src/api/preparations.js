import { http } from './http'
import { newIdempotencyKey } from '@/utils/idem'

// API-12 POST /api/v1/versions/{version_id}/prepare —— 生成 Preparation 准备单
// Maker；前置：版本 is_immutable=true、门禁 4/4 通过；Idempotency-Key 必填
// API-13 POST /api/v1/approval-requests/{approval_id}/decisions —— 提交具名审批决策
// 对应职责槽 Checker；required_role 由审批单据读取；Idempotency-Key 必填
// API-14 POST /api/v1/preparations/{preparation_id}/commit —— 校验审批与指纹，签发 Capability 并原子提交执行
// 仅 Ops；响应仅 execution_run_id / status / capability_digest，不返回 Capability 明文
//
// API-13 与 API-14 要求请求体 idempotency_key 与请求头一致，由本适配层生成同一个键。
function keyedPost(apiId, path, body) {
  const idempotencyKey = newIdempotencyKey()
  return http.post(apiId, path, { ...body, idempotency_key: idempotencyKey }, { idempotencyKey })
}

export const apiPreparations = {
  prepare(versionId, body) {
    return http.post('API-12', `/api/v1/versions/${versionId}/prepare`, body)
  },
  decide(approvalId, body) {
    return keyedPost('API-13', `/api/v1/approval-requests/${approvalId}/decisions`, body)
  },
  commit(preparationId, body) {
    return keyedPost('API-14', `/api/v1/preparations/${preparationId}/commit`, body)
  },
}
