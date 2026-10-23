/**
 * 预览 → 确认 的两步门禁（纯前端状态，不代替后端校验）。
 *
 * 只有「已取得预览」且「当前请求内容与预览时完全一致」才允许确认发送。
 * 修改反馈、切换任务或授权后，指纹变化 → 旧预览自动失效，必须重新预览。
 * 后端仍会独立核对 request_digest：前端不能凭自动获取的 digest 代替人工确认。
 */
import { computed, ref } from 'vue'
import type { PreviewResponse } from '../api'

export interface GateInput {
  taskId: number
  authorizationId: number
  feedback: string[]
}

/** 反馈输入按行拆分，空行丢弃；与后端发送口径保持一致。 */
export function feedbackLines(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}

/** 参与请求的内容指纹（不含时间，便于测试与比较）。 */
export function requestFingerprint(input: GateInput): string {
  return JSON.stringify({
    taskId: input.taskId,
    authorizationId: input.authorizationId,
    feedback: input.feedback,
  })
}

export function usePreviewGate(input: () => GateInput) {
  const preview = ref<PreviewResponse | null>(null)
  const previewFingerprint = ref<string | null>(null)

  const currentFingerprint = computed(() => requestFingerprint(input()))
  const fresh = computed(
    () => preview.value !== null && previewFingerprint.value === currentFingerprint.value,
  )
  const dirty = computed(() => preview.value !== null && !fresh.value)
  const digest = computed(() => (fresh.value ? preview.value?.request_digest ?? null : null))

  function load(result: PreviewResponse): void {
    preview.value = result
    previewFingerprint.value = currentFingerprint.value
  }

  function reset(): void {
    preview.value = null
    previewFingerprint.value = null
  }

  function consume(): { digest: string; feedback: string[] } {
    if (!fresh.value || !preview.value) throw new Error('preview_stale')
    return { digest: preview.value.request_digest, feedback: [...input().feedback] }
  }

  return { preview, fresh, dirty, digest, load, reset, consume, currentFingerprint }
}
