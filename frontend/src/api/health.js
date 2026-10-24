import { http } from './http'

// API-01 GET /health —— 检查系统组件与依赖就绪状态
// 是否公开、组件清单、status 枚举待确认 P-27
export const apiHealth = {
  get() {
    return http.get('API-01', '/health')
  },
}
