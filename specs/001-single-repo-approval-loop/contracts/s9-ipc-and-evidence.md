# S9 IPC 与安全证据接口契约草案

**日期**：2026-10-24　**状态**：DRAFT（待审批；不改已批准 contracts/agent-adapter.md）
**上位**：[s9-detailed-plan.md](./s9-detailed-plan.md)、[s9-isolation-architecture-decision.md](./s9-isolation-architecture-decision.md)

本契约定义「FastAPI 宿主 ↔ 受保护启动器/Worker VM」之间的最小接口与安全证据
结构。是 **新增契约**，不覆盖 `contracts/agent-adapter.md`；AgentAdapter 边界语义不变。

## 1. 参与者与信任

- **宿主（FastAPI）**：可信，负责持久化 `SendAuditRecord`（prepared）与核验。
- **Launcher（VM 内）**：受保护启动器，唯一能读取专用账户凭据与派生受限 Worker。
- **Worker**：受限令牌 + 专用 TokenUser，仅执行单次固定出口发送。
- **Egress relay**：网络边界出口，仅接受固定 Messages POST，返回收据。

调用者认证：宿主与 Launcher 互认（证书或共享密钥）；消息签名；`attempt_id` 防重放。

## 2. 授权请求（宿主 → Launcher）

```text
AuthorizationRequest {
  attempt_id: string            # = SendAuditRecord.attempt_id（全局唯一，一次性）
  authorization_id: integer
  receiver: string              # 固定上游端点
  request_digest: string        # 不可变请求体 SHA-256，与审计行一致
  body_ref: bytes-ref           # 内容寻址只读引用；不重编码
  model: string
  timeout_ms: integer
  nonce: string
  policy_version: string        # 隔离方案/策略版本，绑定证据
}
```

约束：
- `request_digest` 由 Launcher 在发送前对最终字节重算，必须与 `body_ref` 及审计行一致；
- 不允许同时篡改 body 与 job 摘要通过；
- 重复 `attempt_id` 或 `nonce` 直接拒绝（重放保护）。

## 3. 发送收据（Launcher → 宿主）

```text
SendReceipt {
  attempt_id: string
  sent: bool                    # 是否真正写出
  http_status: integer | null
  provider_request_id: string | null
  raw_response_sha256: string | null   # 原始响应字节摘要（非解析文本）
  parsed_text_sha256: string | null    # 解析文本摘要
  terminal_phase: "confirmed_sent" | "possibly_sent" | "not_sent"
  policy_version: string
  evidence: EvidenceRef[]
}
```

- `raw_response_sha256` 是服务商原始响应字节摘要；`response_digest`（既有字段）保留为解析文本摘要，二者分开。

## 4. 发送前证据结构（可信采集）

```text
PreSendEvidence {
  worker_token_user_sid: string   # 实际 TokenUser，核对批准 SID
  worker_pid: integer
  worker_created_at: string
  environment_boot_id: string
  program_sha256: string
  job_object_bound: boolean
  restricted_token: boolean
  network_policy_version: string
  egress_cover: { ipv4: bool, ipv6: bool, loopback: bool, proxy: bool, dns: bool }
  denial_observation: DenialRef[]   # 5157 PID/目标/Filter Runtime ID 关联
  collector: { identity, version, collected_at, ttl }
}
```

- 生产拒绝手填布尔值、synthetic 证据；策略变化或进程重建使证据失效。

## 5. 发送后证据结构

```text
PostSendEvidence {
  attempt_id: string
  receipt: SendReceipt
  verification: { status, sufficient, reasons }
  policy_version: string
}
```

## 6. 边界与 fail-closed

- IPC 只交换有界任务与收据；无通用命令/文件系统/shell 通道。
- 任一认证、完整性、重放、身份、覆盖、拒绝观测不满足 → 拒绝发送（not_sent/possibly_sent 如实）。
- 首次发送前不要求首次服务商响应或发送后摘要。
