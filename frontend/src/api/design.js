import { http } from './http'

// API-11 GET /api/v1/versions/{version_id}/design —— 查询 EtlPlan、HOCON、DAG、质量契约与门禁结果
// 项目成员只读；HOCON 中主机/账号已脱敏
export const apiDesign = {
  get(versionId) {
    return http.get('API-11', `/api/v1/versions/${versionId}/design`)
  },
}
