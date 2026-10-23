/** ADLL V1.1 API 封装（与 contracts/api-endpoints.md 对齐）。 */
import { apiGet, apiPost, apiPut } from './client'

export interface Repository {
  id: number
  path: string
  repo_identity: string
  object_format: 'sha1' | 'sha256' | string
  branch: string | null
  active: boolean
  created_at: string
}

export interface Baseline {
  id: number
  repository_id: number
  commit_sha: string
  object_format: string
  workspace_decision: string
  snapshot_digest: string | null
  available: boolean
  unavailable_reason: string | null
  inventory_summary: Record<string, unknown> | null
  created_at: string
}

export interface WorkspaceStatus {
  clean: boolean
  staged: number
  modified: number
  untracked: number
  entries: string[]
}

export interface RequirementVersion {
  id: number
  task_id: number
  seq: number
  content: string
  content_hash: string
  created_at: string
}

export interface Task {
  id: number
  repository_id: number
  baseline_id: number
  title: string
  description: string | null
  status: string
  current_approval_id: number | null
  created_at: string
  current_requirement_version: RequirementVersion | null
}

export interface Proposal {
  id: number
  task_id: number
  seq: number
  requirement_version_id: number
  baseline_id: number
  execution_id: number
  content: string
  content_hash: string
  created_at: string
  has_approved_event: boolean
  approval_effective: boolean
}

export interface ApprovalEvent {
  id: number
  task_id: number
  proposal_version_id: number
  requirement_version_id: number
  repo_identity: string
  commit_sha: string
  proposal_content_hash: string
  decision: string
  reason: string | null
  actor_role: string
  created_at: string
  effective: boolean
}

export interface Feedback {
  id: number
  task_id: number
  proposal_version_id: number
  content: string
  created_at: string
}

export interface Regeneration {
  required: boolean
  available: boolean
  reason?: string
}

export interface Authorization {
  id: number
  task_id: number
  baseline_id: number
  receiver: string
  data_types: string[]
  send_scope: { paths?: string[]; [key: string]: unknown }
  status: string
  revoked_at: string | null
  expires_at: string | null
}

export interface Cost {
  amount: number | null
  currency: string | null
  basis: 'actual' | 'estimated' | 'unknown' | string
  method?: string | null
}

export interface Execution {
  id: number
  task_id: number
  baseline_id: number
  status: string
  provider: string | null
  cancel_requested: boolean
  cancel_outcome: string | null
  failure_reason: string | null
  usage: Record<string, number> | null
  usage_basis: string | null
  cost: Cost | null
}

export interface Verification {
  id: number
  execution_id?: number
  status: string
  evidence_sufficiency: { sufficient?: boolean; [key: string]: unknown } | null
  coverage_note?: string | null
}

export interface GenerationDetail {
  execution: Execution
  verification: Verification | null
  proposal: Proposal | null
  /** completed 但缺少核验记录（历史异常数据）：成功状态不可信。 */
  verification_missing?: boolean
}

export interface SnapshotSummary {
  digest: string
  authorized_paths: string[]
  snapshot_files?: string[]
  files: string[]
  excluded: { path: string; reason: string }[]
  warnings: string[]
  lfs_pointers: string[]
}

export interface OutboundReceiver {
  receiver: string
  model: string
  testing: boolean
}

export interface PreviewTextPart {
  sha256: string
  chars: number
  bytes: number
  /** 实际发送的原文（逐字确认用），不是哈希占位。 */
  content: string
}

export interface PreviewSourcePart extends PreviewTextPart {
  path: string
}

export interface PreviewResponse {
  receiver: string
  model: string
  testing: boolean
  data_types: string[]
  request_digest: string
  /** 完整规范化请求体（键排序、紧凑分隔符、UTF-8）；sha256 应等于 request_digest。 */
  request_body: { content: string; sha256: string; bytes: number; canonical: string }
  /** 请求体中 messages[0].content 的同一条文本（不是完整 body）。 */
  message: { content: string; sha256: string; bytes: number }
  requirement: PreviewTextPart
  feedback: PreviewTextPart[]
  source: PreviewSourcePart[]
  snapshot: {
    digest: string
    files: string[]
    excluded: { path: string; reason: string }[]
    warnings: string[]
  }
}

export interface StartGenerationResponse {
  execution_id: number
  status: string
  snapshot: SnapshotSummary
}

export interface CancelResponse {
  outcome: 'cancel_requested' | 'cancelled' | 'not_cancelled' | 'already_finished'
  status: string
  cancel_outcome: string | null
  note: string
}

export interface SendAudit {
  id: number
  authorization_id: number | null
  attempt_id?: string | null
  phase?: string
  receiver?: string | null
  request_digest?: string | null
  error_code?: string | null
  payload_manifest: {
    requirement?: string[]
    feedback?: string[]
    source?: { path: string; sha256: string }[]
    tool_return?: unknown[]
    [key: string]: unknown
  }
  content_digest: string
  payload_digest?: string | null
}

export interface Health {
  status: string
  app: string
  testing: boolean
  real_ai_enabled: boolean
}

export const api = {
  health: () => apiGet<Health>('/health'),
  login: (password: string) =>
    apiPost<{ role: string; csrf_token: string }>('/auth/login', { password }),
  me: () => apiGet<{ role: string; expires_at: string; csrf_token: string }>('/auth/me'),
  logout: () => apiPost<{ ok: boolean }>('/auth/logout'),

  linkRepository: (path: string) =>
    apiPost<{
      repository: Repository
      baseline: Baseline | null
      workspace_status: WorkspaceStatus
      needs_decision: boolean
    }>('/repositories/link', { path }),
  activeRepository: () =>
    apiGet<{ repository: Repository | null; baseline: Baseline | null }>('/repositories/active'),
  workspaceDecision: (repoId: number, decision: 'clean' | 'accept_uncommitted') =>
    apiPost<{ baseline: Baseline }>(`/repositories/${repoId}/workspace-decision`, { decision }),

  listTasks: () => apiGet<{ tasks: Task[] }>('/tasks'),
  getTask: (taskId: number) => apiGet<{ task: Task }>(`/tasks/${taskId}`),
  createTask: (body: { repository_id: number; baseline_id: number; title: string; description?: string }) =>
    apiPost<{ task: Task }>('/tasks', body),
  saveRequirement: (taskId: number, content: string) =>
    apiPut<{ requirement_version: RequirementVersion }>(`/tasks/${taskId}/requirement`, { content }),

  listProposals: (taskId: number) => apiGet<{ proposals: Proposal[] }>(`/tasks/${taskId}/proposals`),
  listApprovals: (taskId: number) => apiGet<{ approvals: ApprovalEvent[] }>(`/tasks/${taskId}/approvals`),
  approve: (taskId: number, version: number, reason?: string) =>
    apiPost<{ approval: ApprovalEvent }>(`/tasks/${taskId}/proposals/${version}/approve`, { reason }),
  reject: (taskId: number, version: number, reason: string) =>
    apiPost<{ approval: ApprovalEvent }>(`/tasks/${taskId}/proposals/${version}/reject`, { reason }),
  feedback: (taskId: number, version: number, content: string) =>
    apiPost<{ feedback: Feedback; regeneration: Regeneration }>(
      `/tasks/${taskId}/proposals/${version}/feedback`,
      { content },
    ),

  listAuthorizations: (taskId: number) =>
    apiGet<{ authorizations: Authorization[] }>(`/tasks/${taskId}/outbound-authorizations`),
  outboundReceiver: () => apiGet<OutboundReceiver>('/outbound/receiver'),
  createAuthorization: (
    taskId: number,
    body: { receiver: string; data_types: string[]; send_scope: Record<string, unknown> },
  ) => apiPost<{ authorization: Authorization }>(`/tasks/${taskId}/outbound-authorizations`, body),
  revokeAuthorization: (authorizationId: number) =>
    apiPost<{ authorization: Authorization }>(`/outbound-authorizations/${authorizationId}/revoke`),

  previewGeneration: (taskId: number, authorizationId: number, feedback: string[] = []) =>
    apiPost<PreviewResponse>(`/tasks/${taskId}/generations/preview`, {
      authorization_id: authorizationId,
      feedback,
    }),
  startGeneration: (
    taskId: number,
    authorizationId: number,
    feedback: string[],
    previewDigest?: string,
  ) =>
    apiPost<StartGenerationResponse>(`/tasks/${taskId}/generations`, {
      authorization_id: authorizationId,
      feedback,
      preview_digest: previewDigest,
    }),
  getGeneration: (executionId: number) => apiGet<GenerationDetail>(`/generations/${executionId}`),
  cancelGeneration: (executionId: number) =>
    apiPost<CancelResponse>(`/generations/${executionId}/cancel`),
  sendAudit: (executionId: number) =>
    apiGet<{ audits: SendAudit[] }>(`/generations/${executionId}/send-audit`),
}