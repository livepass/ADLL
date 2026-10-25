/** 预览门禁：内容变化必须使旧确认失效（纯逻辑，不触碰 DOM）。 */
import { ref } from 'vue'
import { describe, expect, it } from 'vitest'
import type { PreviewResponse } from '../api'
import { feedbackLines, requestFingerprint, usePreviewGate } from './previewGate'

const PREVIEW: PreviewResponse = {
  receiver: 'mock://local',
  model: 'm',
  testing: true,
  data_types: ['requirement'],
  request_digest: 'a'.repeat(64),
  request_body: {
    content: '{"messages":[{"content":"## Requirement\\n需求"}],"model":"m"}',
    sha256: 'a'.repeat(64),
    bytes: 62,
    canonical: 'json/utf-8, sorted keys, compact separators',
  },
  message: { content: '## Requirement\n需求', sha256: 'b'.repeat(64), bytes: 18 },
  requirement: { sha256: 'c'.repeat(64), chars: 2, bytes: 6, content: '需求' },
  feedback: [],
  source: [],
  snapshot: { digest: 'd'.repeat(64), files: [], excluded: [], warnings: [] },
}

function loadOnce(gate: ReturnType<typeof usePreviewGate>, preview = PREVIEW): boolean {
  return gate.load(preview, gate.begin())
}

describe('previewGate', () => {
  it('splits feedback by line and drops blanks', () => {
    expect(feedbackLines(' a \n\n b\n')).toEqual(['a', 'b'])
    expect(feedbackLines('   ')).toEqual([])
  })

  it('fingerprint changes when the formal requirement content changes', () => {
    // 需求内容属于实际发送正文；变更后旧预览不得继续可确认。
    const base = requestFingerprint({
      taskId: 1,
      authorizationId: 2,
      feedback: [],
      requirement: 'V1 需求',
    })
    expect(
      requestFingerprint({ taskId: 1, authorizationId: 2, feedback: [], requirement: 'V1 需求' }),
    ).toBe(base)
    expect(
      requestFingerprint({ taskId: 1, authorizationId: 2, feedback: [], requirement: 'V2 需求' }),
    ).not.toBe(base)
  })

  it('preview becomes stale after the requirement content changes', () => {
    const input = ref({
      taskId: 1,
      authorizationId: 2,
      feedback: [] as string[],
      requirement: 'V1 需求',
    })
    const gate = usePreviewGate(() => input.value)
    expect(loadOnce(gate)).toBe(true)
    expect(gate.fresh.value).toBe(true)

    input.value = { ...input.value, requirement: 'V2 需求' }
    expect(gate.fresh.value).toBe(false)
    expect(gate.dirty.value).toBe(true)
    expect(gate.digest.value).toBeNull()
    expect(() => gate.consume()).toThrowError('preview_stale')
  })

  it('fingerprint changes with task, authorization or feedback', () => {
    const base = requestFingerprint({ taskId: 1, authorizationId: 2, feedback: [] })
    expect(requestFingerprint({ taskId: 1, authorizationId: 2, feedback: [] })).toBe(base)
    expect(requestFingerprint({ taskId: 9, authorizationId: 2, feedback: [] })).not.toBe(base)
    expect(requestFingerprint({ taskId: 1, authorizationId: 9, feedback: [] })).not.toBe(base)
    expect(requestFingerprint({ taskId: 1, authorizationId: 2, feedback: ['x'] })).not.toBe(base)
  })

  it('requires a fresh preview before consuming a digest', () => {
    const input = ref({ taskId: 1, authorizationId: 2, feedback: [] as string[] })
    const gate = usePreviewGate(() => input.value)

    expect(gate.fresh.value).toBe(false)
    expect(() => gate.consume()).toThrowError('preview_stale')

    expect(loadOnce(gate)).toBe(true)
    expect(gate.fresh.value).toBe(true)
    expect(gate.digest.value).toBe(PREVIEW.request_digest)

    // 修改反馈 → 旧确认失效，摘要不可再用
    input.value = { ...input.value, feedback: ['补充'] }
    expect(gate.fresh.value).toBe(false)
    expect(gate.dirty.value).toBe(true)
    expect(gate.digest.value).toBeNull()
    expect(() => gate.consume()).toThrowError('preview_stale')

    // 重新预览后恢复
    expect(loadOnce(gate)).toBe(true)
    expect(gate.consume()).toEqual({ digest: PREVIEW.request_digest, feedback: ['补充'] })
  })

  it('switching task or authorization also invalidates', () => {
    const input = ref({ taskId: 1, authorizationId: 2, feedback: [] as string[] })
    const gate = usePreviewGate(() => input.value)
    loadOnce(gate)
    expect(gate.fresh.value).toBe(true)

    input.value = { ...input.value, taskId: 3 }
    expect(gate.fresh.value).toBe(false)

    input.value = { taskId: 1, authorizationId: 2, feedback: [] }
    loadOnce(gate)
    input.value = { ...input.value, authorizationId: 5 }
    expect(gate.fresh.value).toBe(false)
  })

  it('a response that lands after the inputs changed is accepted but stale', () => {
    const input = ref({ taskId: 1, authorizationId: 2, feedback: [] as string[] })
    const gate = usePreviewGate(() => input.value)

    const ticket = gate.begin() // 请求发出时：无反馈
    input.value = { ...input.value, feedback: ['迟到的修改'] }
    expect(gate.load(PREVIEW, ticket)).toBe(true)

    // 不能被当成当前预览：发送必须保持禁用
    expect(gate.fresh.value).toBe(false)
    expect(gate.dirty.value).toBe(true)
    expect(() => gate.consume()).toThrowError('preview_stale')
  })

  it('drops superseded responses and anything after reset', () => {
    const input = ref({ taskId: 1, authorizationId: 2, feedback: [] as string[] })
    const gate = usePreviewGate(() => input.value)

    const first = gate.begin()
    const second = gate.begin()
    expect(gate.load(PREVIEW, first)).toBe(false)
    expect(gate.preview.value).toBeNull()

    expect(gate.load(PREVIEW, second)).toBe(true)
    gate.reset()
    expect(gate.load(PREVIEW, second)).toBe(false)
    expect(gate.preview.value).toBeNull()
  })
})
