import { http } from './http'

// API-07 POST /api/v1/file-assets —— 上传并解析异构文件数据源
// multipart/form-data；Maker；Idempotency-Key 必填；文件大小上限待确认 P-15
export const apiFiles = {
  upload(formData) {
    return http.post('API-07', '/api/v1/file-assets', undefined, { formData })
  },
}
