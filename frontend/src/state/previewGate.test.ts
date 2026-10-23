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
  message: { content: '## Requirement\n需求', sha256: 'b'.repeat(64), bytes: 18 },
  requirement: { sha256: 'c'.repeat(64), chars: 2, bytes: 6, content: '需求' },
  feedback: [],
  source: [],
  snapshot: { digest: 'd'.repeat(64), files: [], excluded: [], warnings: [] },
}

describe('previewGate', () => {
  it('splits feedback by line and drops blanks', () => {
    expect(feedbackLines(' a \n\n b\n')).toEqual(['a', 'b'])
    expect(feedbackLines('   ')).toEqual([])
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

    gate.load(PREVIEW)
    expect(gate.fresh.value).toBe(true)
    expect(gate.digest.value).toBe(PREVIEW.request_digest)

    // 修改反馈 → 旧确认失效，摘要不可再用
    input.value = { ...input.value, feedback: ['补充'] }
    expect(gate.fresh.value).toBe(false)
    expect(gate.dirty.value).toBe(true)
    expect(gate.digest.value).toBeNull()
    expect(() => gate.consume()).toThrowError('preview_stale')

    // 重新预览后恢复
    gate.load(PREVIEW)
    expect(gate.consume()).toEqual({ digest: PREVIEW.request_digest, feedback: ['补充'] })
  })

  it('switching task or authorization also invalidates', () => {
    const input = ref({ taskId: 1, authorizationId: 2, feedback: [] as string[] })
    const gate = usePreviewGate(() => input.value)
    gate.load(PREVIEW)
    expect(gate.fresh.value).toBe(true)

    input.value = { ...input.value, taskId: 3 }
    expect(gate.fresh.value).toBe(false)

    input.value = { taskId: 1, authorizationId: 2, feedback: [] }
    gate.load(PREVIEW)
    input.value = { ...input.value, authorizationId: 5 }
    expect(gate.fresh.value).toBe(false)
  })
})
