// 展示层脱敏（Spec 12.3）。原值不得进入前端；脱敏失败时整块不展示。
// 手机号 138****6621 / 邮箱 z***@example.com / 姓名 首字+* / 证件号 ****（P0 禁止采样）
// 主机 10.20.*.* / Secret 引用 vault://*** 样式 / 摘要截断。

export function maskPhone(v) {
  if (v === null || v === undefined || v === '') return ''
  const s = String(v)
  if (s.length < 7) return '***'
  return `${s.slice(0, 3)}****${s.slice(-4)}`
}

export function maskEmail(v) {
  if (v === null || v === undefined || v === '') return ''
  const s = String(v)
  const i = s.indexOf('@')
  if (i <= 0) return '***'
  return `${s.slice(0, 1)}***@${s.slice(i + 1)}`
}

export function maskName(v) {
  if (v === null || v === undefined || v === '') return ''
  const s = String(v)
  if (s.length <= 1) return '*'
  return `${s.slice(0, 1)}**`
}

export function maskIdCard() {
  return '****'
}

export function maskHost(v) {
  if (v === null || v === undefined || v === '') return ''
  const s = String(v)
  const parts = s.split('.')
  if (parts.length === 4 && parts.every((p) => /^\d+$/.test(p))) {
    return `${parts[0]}.${parts[1]}.*.*`
  }
  return `${s.slice(0, 3)}***`
}

export function maskJdbcUrl(v) {
  if (v === null || v === undefined || v === '') return ''
  const s = String(v)
  const scheme = s.indexOf('://')
  if (scheme > -1) {
    const at = s.indexOf('@', scheme)
    if (at > -1) {
      return `${s.slice(0, scheme + 3)}***@${s.slice(at + 1)}`
    }
  }
  return maskHost(s)
}

export function maskSecretRef(v) {
  if (v === null || v === undefined || v === '') return ''
  const s = String(v)
  const last = s.lastIndexOf('/')
  if (last > -1) return `${s.slice(0, last + 1)}***`
  return '***'
}

// 摘要只展示首尾片段（指纹/令牌摘要/哈希均为不可逆值，可短展示）
export function shortDigest(v, head = 10) {
  if (v === null || v === undefined || v === '') return ''
  const s = String(v)
  if (s.length <= head + 8) return s
  return `${s.slice(0, head)}…${s.slice(-6)}`
}

// 错误表样本 / 文件头样本：只允许脱敏值，未知类别整块拒绝展示
export function maskCell(value, kind) {
  switch (kind) {
    case 'phone':
      return maskPhone(value)
    case 'email':
      return maskEmail(value)
    case 'name':
      return maskName(value)
    case 'id_card':
      return maskIdCard()
    case 'host':
      return maskHost(value)
    case 'jdbc_url':
      return maskJdbcUrl(value)
    case 'secret_ref':
      return maskSecretRef(value)
    default:
      return '***'
  }
}
