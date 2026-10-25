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
  /**
   * 当前正式需求内容。需求属于实际发送内容（payload 的 requirement 字段），
   * 缺失它会让「需求已变更但旧预览仍可确认」的漏洞成立。
   */
  requirement?: string
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
    requirement: input.requirement ?? '',
  })
}

export interface PreviewTicket {
  /** 发起请求时的输入指纹（不是响应到达时的）。 */
  fingerprint: string
  ticket: number
}

export function usePreviewGate(input: () => GateInput) {
  const preview = ref<PreviewResponse | null>(null)
  const previewFingerprint = ref<string | null>(null)
  // 递增序号：后发请求优先，旧响应即使晚到也不能覆盖或伪装成当前预览。
  let latestTicket = 0

  const currentFingerprint = computed(() => requestFingerprint(input()))
  const fresh = computed(
    () => preview.value !== null && previewFingerprint.value === currentFingerprint.value,
  )
  const dirty = computed(() => preview.value !== null && !fresh.value)
  const digest = computed(() => (fresh.value ? preview.value?.request_digest ?? null : null))

  function begin(): PreviewTicket {
    latestTicket += 1
    return { fingerprint: currentFingerprint.value, ticket: latestTicket }
  }

  function isCurrent(ticket: PreviewTicket): boolean {
    return ticket.ticket === latestTicket
  }

  /**
   * 接受预览结果。返回 false 表示该响应已被更新的请求或 reset() 作废。
   * 记录的指纹是**请求发出时**的输入：等待期间用户改了反馈/任务/授权，
   * 结果会立刻是 dirty，而不会被误标为当前预览。
   */
  function load(result: PreviewResponse, ticket: PreviewTicket): boolean {
    if (!isCurrent(ticket)) return false
    preview.value = result
    previewFingerprint.value = ticket.fingerprint
    return true
  }

  function reset(): void {
    // 使在途响应一并作废（旧确认不再有资格落地）。
    latestTicket += 1
    preview.value = null
    previewFingerprint.value = null
  }

  function consume(): { digest: string; feedback: string[] } {
    if (!fresh.value || !preview.value) throw new Error('preview_stale')
    return { digest: preview.value.request_digest, feedback: [...input().feedback] }
  }

  return {
    preview,
    fresh,
    dirty,
    digest,
    begin,
    isCurrent,
    load,
    reset,
    consume,
    currentFingerprint,
  }
}
