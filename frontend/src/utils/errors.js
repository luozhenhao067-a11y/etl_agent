// 统一错误解析（契约 2.4）：错误结构 {error_code, message, correlation_id, details}
// 展示层只给出脱敏提示；不展示堆栈、主机、Secret、令牌、原始敏感值。

// 客户端占位码，仅用于标识“契约缺失接口”，不是服务端 API 错误码。
export const CONTRACT_PENDING_CODE = 'CLIENT-CONTRACT-PENDING'

export class ApiError extends Error {
  constructor({ httpStatus, errorCode, message, correlationId, details }) {
    super(message || 'request failed')
    this.name = 'ApiError'
    this.httpStatus = httpStatus
    this.errorCode = errorCode
    this.correlationId = correlationId
    this.details = details || {}
  }

  static fromResponse(status, payload) {
    const p = payload || {}
    return new ApiError({
      httpStatus: status,
      errorCode: p.error_code || `API-${status}`,
      message: p.message || 'request failed',
      correlationId: p.correlation_id,
      details: p.details || {},
    })
  }

  isAuth() {
    return this.httpStatus === 401
  }

  isForbidden() {
    return this.httpStatus === 403
  }

  isDependencyUnavailable() {
    return this.httpStatus === 503
  }

  isContractPending() {
    return this.errorCode === CONTRACT_PENDING_CODE
  }

  // 仅 503/504 且标注可重试的码允许客户端退避重试（契约 4.3）
  isRetryable() {
    return this.httpStatus === 503 || this.httpStatus === 504
  }

  // 传输层失败（无 HTTP 响应）。httpStatus 0 仅为客户端内部标记。
  isNetworkError() {
    return this.httpStatus === 0
  }

  // 按契约 2.5 状态码映射的脱敏提示
  friendly() {
    switch (this.httpStatus) {
      case 0:
        return '网络连接失败，请检查网络后重试'
      case 400:
        return '请求参数错误'
      case 401:
        return '未认证或认证已失效，请重新登录'
      case 403:
        return '无权限执行该操作'
      case 404:
        return '资源不存在或不属于当前项目'
      case 409:
        return '状态冲突或资源已存在，请刷新后重试'
      case 410:
        return '凭证或租约已过期，请重新发起流程'
      case 413:
        return '文件超过大小上限（上限待确认 P-15）'
      case 422:
        return '字段校验未通过，请检查输入'
      case 424:
        return '工具依赖失败'
      case 429:
        return '请求过于频繁，请稍后重试'
      case 500:
        return '服务端内部错误'
      case 503:
        return '依赖未就绪'
      case 504:
        return '依赖服务超时，可稍后重试'
      default:
        return this.isContractPending() ? '接口待确认' : '请求失败'
    }
  }

  // 422 时给出字段定位（契约 details.field 为脱敏结构化字段）
  fieldError() {
    if (this.httpStatus === 422 && this.details && typeof this.details.field === 'string') {
      return this.details.field
    }
    return null
  }
}
