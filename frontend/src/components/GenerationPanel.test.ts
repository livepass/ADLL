// @vitest-environment jsdom
/**
 * 生成面板交互：预览与确认必须是两个独立动作，内容变化后旧确认失效。
 * API 全部 mock，不触网。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Authorization, GenerationDetail, PreviewResponse } from '../api'
import { ApiError } from '../api/client'
import { runtime } from '../state/session'
import GenerationPanel from './GenerationPanel.vue'

const mocks = vi.hoisted(() => ({
  previewGeneration: vi.fn(),
  startGeneration: vi.fn(),
  getGeneration: vi.fn(),
  cancelGeneration: vi.fn(),
  sendAudit: vi.fn(),
}))

vi.mock('../api', () => ({ api: mocks }))

const AUTH: Authorization = {
  id: 7,
  task_id: 1,
  baseline_id: 3,
  receiver: 'mock://local',
  data_types: ['requirement', 'source'],
  send_scope: { paths: ['a.txt'] },
  status: 'approved',
  revoked_at: null,
  expires_at: null,
}

const PREVIEW: PreviewResponse = {
  receiver: 'mock://local',
  model: 'qwen-test',
  testing: true,
  data_types: ['requirement', 'source'],
  request_digest: 'a'.repeat(64),
  request_body: {
    content:
      '{"max_tokens":256,"messages":[{"content":"## Requirement\\n需求\\n## Source\\n### a.txt\\nalpha-beta","role":"user"}],"model":"qwen-test","stream":false,"thinking":{"type":"disabled"}}',
    sha256: 'a'.repeat(64),
    bytes: 179,
    canonical: 'json/utf-8, sorted keys, compact separators',
  },
  message: {
    content: '## Requirement\n需求\n## Source\n### a.txt\nalpha-beta',
    sha256: 'b'.repeat(64),
    bytes: 48,
  },
  requirement: { sha256: 'c'.repeat(64), chars: 2, bytes: 6, content: '需求' },
  feedback: [],
  source: [
    { path: 'a.txt', sha256: 'd'.repeat(64), chars: 10, bytes: 10, content: 'alpha-beta' },
  ],
  snapshot: { digest: 'e'.repeat(64), files: ['a.txt'], excluded: [], warnings: [] },
}

const DETAIL: GenerationDetail = {
  execution: {
    id: 9,
    task_id: 1,
    baseline_id: 3,
    status: 'completed',
    provider: 'mock',
    cancel_requested: false,
    cancel_outcome: null,
    failure_reason: null,
    usage: { input_tokens: 1, output_tokens: 1 },
    usage_basis: 'actual',
    cost: { amount: null, currency: null, basis: 'actual' },
  },
  verification: {
    id: 1,
    status: 'verified',
    evidence_sufficiency: { sufficient: true },
    coverage_note: 'verified',
  },
  proposal: null,
}

function mountPanel() {
  return mount(GenerationPanel, {
    props: {
      taskId: 1,
      authorizations: [AUTH],
      requirementContent: '需求',
    },
  })
}

async function previewOnce(wrapper: ReturnType<typeof mountPanel>) {
  await wrapper.get('[data-test="preview"]').trigger('click')
  await flushPromises()
}

describe('GenerationPanel preview/confirm gate', () => {
  beforeEach(() => {
    runtime.testing = true
    runtime.realAiEnabled = false
    mocks.previewGeneration.mockReset().mockResolvedValue(PREVIEW)
    mocks.startGeneration.mockReset().mockResolvedValue({
      execution_id: 9,
      status: 'running',
      snapshot: {
        digest: 'e'.repeat(64),
        authorized_paths: ['a.txt'],
        files: ['a.txt'],
        excluded: [],
        warnings: [],
        lfs_pointers: [],
      },
    })
    mocks.getGeneration.mockReset().mockResolvedValue(DETAIL)
    mocks.cancelGeneration.mockReset()
    mocks.sendAudit.mockReset().mockResolvedValue({ audits: [] })
  })

  afterEach(() => {
    vi.clearAllTimers()
  })

  it('does not send until the operator confirms after preview', async () => {
    const wrapper = mountPanel()
    const send = wrapper.get('[data-test="send"]')
    expect(send.attributes('disabled')).toBeDefined()

    await previewOnce(wrapper)

    // 预览只调用预览接口，绝不自动发送
    expect(mocks.previewGeneration).toHaveBeenCalledWith(1, 7, [])
    expect(mocks.startGeneration).not.toHaveBeenCalled()
    expect(wrapper.get('[data-test="send"]').attributes('disabled')).toBeUndefined()

    // 完整内容可见（不是只给哈希）：正文、完整请求体、模型
    expect(wrapper.text()).toContain('alpha-beta')
    expect(wrapper.text()).toContain('## Requirement')
    expect(wrapper.text()).toContain('qwen-test')
    expect(wrapper.text()).toContain('max_tokens')
    expect(wrapper.text()).toContain('messages[0].content')

    await wrapper.get('[data-test="send"]').trigger('click')
    await flushPromises()

    expect(mocks.startGeneration).toHaveBeenCalledTimes(1)
    expect(mocks.startGeneration).toHaveBeenCalledWith(1, 7, [], PREVIEW.request_digest)
    wrapper.unmount()
  })

  it('invalidates the confirmation when feedback changes', async () => {
    const wrapper = mountPanel()
    await previewOnce(wrapper)
    expect(wrapper.get('[data-test="send"]').attributes('disabled')).toBeUndefined()

    await wrapper.get('[data-test="feedback"]').setValue('补充说明')
    await flushPromises()

    expect(wrapper.get('[data-test="send"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('原预览确认已失效')

    await wrapper.get('[data-test="send"]').trigger('click')
    await flushPromises()
    expect(mocks.startGeneration).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('invalidates the confirmation when the task changes', async () => {
    const wrapper = mountPanel()
    await previewOnce(wrapper)
    await wrapper.setProps({ taskId: 2 })
    expect(wrapper.get('[data-test="send"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('drops the preview when the server reports a digest mismatch', async () => {
    mocks.startGeneration.mockRejectedValue(
      new ApiError(409, 'preview_digest_mismatch', 'preview_digest_mismatch'),
    )
    const wrapper = mountPanel()
    await previewOnce(wrapper)

    await wrapper.get('[data-test="send"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('待发送内容已变化')
    // 旧确认作废：必须重新预览
    expect(wrapper.get('[data-test="send"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('needs a fresh preview after a successful send', async () => {
    const wrapper = mountPanel()
    await previewOnce(wrapper)
    await wrapper.get('[data-test="send"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="send"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
})


function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('GenerationPanel stale preview', () => {
  beforeEach(() => {
    runtime.testing = true
    runtime.realAiEnabled = false
    mocks.startGeneration.mockReset()
    mocks.getGeneration.mockReset().mockResolvedValue(DETAIL)
  })

  it('does not treat a late preview response as current after feedback changes', async () => {
    const pending = deferred<PreviewResponse>()
    mocks.previewGeneration.mockReset().mockReturnValue(pending.promise)
    const wrapper = mountPanel()

    const clicking = wrapper.get('[data-test="preview"]').trigger('click')
    // 请求在途时修改反馈
    await wrapper.get('[data-test="feedback"]').setValue('补充说明')
    pending.resolve(PREVIEW)
    await clicking
    await flushPromises()

    expect(wrapper.get('[data-test="send"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('原预览确认已失效')
    await wrapper.get('[data-test="send"]').trigger('click')
    await flushPromises()
    expect(mocks.startGeneration).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
