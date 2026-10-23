/**
 * API 客户端：真实 FastAPI 调用。
 *
 * 安全要点（批 7）：
 * - CSRF Token 仅保存在内存（模块变量），不写入 localStorage / sessionStorage / Cookie；
 * - 状态变更请求自动附加 `X-CSRF-Token`；
 * - 错误统一归一化为 ApiError（含 HTTP 状态与后端 code），由页面按 401/403/409/423/503 处理；
 * - 凭据（API Key / Token）不进入前端。
 */
const BASE = '/api'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail: unknown

  constructor(status: number, code: string, message: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
  }
}

let csrfToken = ''
let unauthorizedHandler: (() => void) | null = null

export function setCsrfToken(token: string | null | undefined): void {
  csrfToken = token ?? ''
}

export function getCsrfToken(): string {
  return csrfToken
}

export function clearCsrfToken(): void {
  csrfToken = ''
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

/** 幂等键（仅用于安全重试；每次新操作生成新的 UUID）。 */
export function newIdempotencyKey(): string {
  const cryptoObj = globalThis.crypto as Crypto | undefined
  if (cryptoObj && typeof cryptoObj.randomUUID === 'function') {
    return cryptoObj.randomUUID()
  }
  return `k-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function normalize(data: unknown): { code: string; message: string } {
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>
    const detail = obj.detail
    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      const d = detail as Record<string, unknown>
      const code = typeof d.code === 'string' ? d.code : 'error'
      return { code, message: typeof d.message === 'string' ? d.message : code }
    }
    if (Array.isArray(detail)) {
      return { code: 'validation_error', message: '请求参数校验失败' }
    }
    if (typeof obj.code === 'string') {
      return {
        code: obj.code,
        message: typeof obj.message === 'string' ? obj.message : obj.code,
      }
    }
    if (typeof detail === 'string') {
      return { code: 'error', message: detail }
    }
  }
  return { code: 'error', message: '请求失败' }
}

interface RequestOptions {
  body?: unknown
  idempotencyKey?: string
}

export async function request<T>(
  method: string,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (csrfToken && method !== 'GET' && method !== 'HEAD') {
    headers['X-CSRF-Token'] = csrfToken
  }
  if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey

  let resp: Response
  try {
    resp = await fetch(`${BASE}${path}`, {
      method,
      headers,
      credentials: 'same-origin',
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })
  } catch {
    throw new ApiError(0, 'network_error', '无法连接后端服务')
  }

  const text = await resp.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = null
    }
  }

  if (!resp.ok) {
    const parsed = normalize(data)
    const error = new ApiError(resp.status, parsed.code, parsed.message, data)
    if (resp.status === 401) {
      clearCsrfToken()
      unauthorizedHandler?.()
    }
    throw error
  }
  return data as T
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>('GET', path)
}

export function apiPost<T>(path: string, body?: unknown, idempotencyKey?: string): Promise<T> {
  return request<T>('POST', path, { body, idempotencyKey })
}

export function apiPut<T>(path: string, body?: unknown, idempotencyKey?: string): Promise<T> {
  return request<T>('PUT', path, { body, idempotencyKey })
}