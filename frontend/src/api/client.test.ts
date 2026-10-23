/**
 * API 客户端单元测试（不触网）：CSRF 内存令牌、幂等键、错误归一化与 401 处理。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  apiGet,
  apiPost,
  clearCsrfToken,
  getCsrfToken,
  newIdempotencyKey,
  setCsrfToken,
  setUnauthorizedHandler,
} from './client'
import { describeError } from './errors'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('api client', () => {
  beforeEach(() => {
    clearCsrfToken()
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('attaches CSRF and idempotency headers to state-changing requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    setCsrfToken('csrf-abc')

    await apiPost('/tasks/1/requirement', { content: 'x' }, 'idem-1')

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/tasks/1/requirement')
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('same-origin')
    const headers = init.headers as Record<string, string>
    expect(headers['X-CSRF-Token']).toBe('csrf-abc')
    expect(headers['Idempotency-Key']).toBe('idem-1')
    expect(init.body).toBe(JSON.stringify({ content: 'x' }))
  })

  it('does not attach CSRF to GET and keeps the token only in memory', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { tasks: [] }))
    vi.stubGlobal('fetch', fetchMock)
    setCsrfToken('csrf-abc')

    await apiGet('/tasks')

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBeUndefined()
    expect(getCsrfToken()).toBe('csrf-abc')
  })

  it('normalizes FastAPI detail errors (409 approval_target_stale)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(409, {
          detail: { code: 'approval_target_stale', message: '目标不是当前方案版本' },
        }),
      ),
    )

    await expect(apiPost('/tasks/1/proposals/1/approve', {})).rejects.toMatchObject({
      status: 409,
      code: 'approval_target_stale',
    })
  })

  it('normalizes baseline_unavailable (423) and ai_disabled (503)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce(jsonResponse(423, { detail: { code: 'baseline_unavailable' } })),
    )
    await expect(apiPost('/x', {})).rejects.toMatchObject({
      status: 423,
      code: 'baseline_unavailable',
    })

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce(
        jsonResponse(503, { code: 'ai_disabled', message: '真实 AI 发送默认关闭' }),
      ),
    )
    await expect(apiPost('/y', {})).rejects.toMatchObject({
      status: 503,
      code: 'ai_disabled',
    })
  })

  it('clears CSRF and invokes unauthorized handler on 401', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    setCsrfToken('csrf-abc')
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(401, { detail: { code: 'unauthorized' } })),
    )

    await expect(apiGet('/auth/me')).rejects.toBeInstanceOf(ApiError)
    expect(getCsrfToken()).toBe('')
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('maps validation arrays and non-JSON bodies safely', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce(jsonResponse(422, { detail: [{ loc: ['body'] }] })),
    )
    await expect(apiPost('/x', {})).rejects.toMatchObject({ code: 'validation_error' })

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce(new Response('not-json', { status: 500 })),
    )
    await expect(apiPost('/y', {})).rejects.toMatchObject({ status: 500, code: 'error' })
  })

  it('produces distinct idempotency keys', () => {
    expect(newIdempotencyKey()).not.toBe(newIdempotencyKey())
  })

  it('explains known codes without inventing amounts or status', () => {
    expect(describeError(new ApiError(423, 'baseline_unavailable', 'x'))).toContain('423')
    expect(describeError(new ApiError(409, 'verification_not_passed', 'x'))).toContain(
      '最新核验未通过',
    )
    expect(describeError(new ApiError(0, 'network_error', 'x'))).toContain('无法连接')
  })
})