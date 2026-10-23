/** 错误说明：后端 code → 用户可读文本（仅用于展示，不替代服务端判定）。 */
import { ApiError } from './client'

const MESSAGES: Record<string, string> = {
  network_error: '无法连接后端服务，请确认后端已启动。',
  invalid_credentials: '口令无效。',
  auth_unavailable: '服务端未配置认证凭据（fail-closed），无法登录。',
  csrf_failed: 'CSRF 校验失败，请重新登录后再试。',
  forbidden: '当前会话无权执行此操作。',
  not_found: '目标不存在或已失效。',
  outbound_denied:
    '出站授权不满足（任务、基准、接收方、实际发送范围、授权有效性五项须同时满足），请重新确认授权。',
  outbound_auth_required: '需要重新确认出站授权。',
  baseline_unavailable: '分析基准不可用，无法继续（HTTP 423）。',
  baseline_repo_mismatch: '分析基准不属于该仓库。',
  verification_not_passed: '最新核验未通过或证据不足，不能提交审批。',
  approval_target_stale:
    '目标不是当前有效方案版本（需求或基准已变更），未写入批准；请重新审阅当前版本。',
  approval_exists: '该方案版本已有有效批准（唯一批准约束）。',
  invalid_transition: '当前状态不允许该操作。',
  idempotency_conflict: '同一幂等键对应不同请求，请重新发起。',
  active_execution_exists: '该任务已有运行中的生成。',
  no_requirement: '尚无正式需求版本。',
  ai_disabled: '真实 AI 发送默认关闭（fail-closed）。',
  isolation_unverified: '隔离证据未通过核验，已阻止发送（零发送）。',
  generation_error: '生成过程出现服务端错误。',
  validation_error: '请求参数校验失败。',
  invalid_decision: '工作区决定无效。',
  invalid_receiver: '接收方必填。',
  error: '请求失败。',
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    const base = MESSAGES[error.code]
    if (base) return `${base}（${error.code}）`
    return `${error.message}（${error.code || `HTTP ${error.status}`}）`
  }
  if (error instanceof Error) return error.message
  return String(error)
}