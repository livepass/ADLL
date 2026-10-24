# S9 IPC 与安全证据接口契约草案

**日期**：2026-10-24（R2 定向修订）　**状态**：DRAFT（待审批；不改已批准 contracts/agent-adapter.md）
**上位**：[s9-detailed-plan.md](./s9-detailed-plan.md)、[s9-isolation-architecture-decision.md](./s9-isolation-architecture-decision.md)

本契约定义「FastAPI 宿主 ↔ 受保护启动器/Worker VM ↔ 固定出口」之间的最小接口与
可信证据结构。是 **新增契约**，不覆盖 `contracts/agent-adapter.md`；AgentAdapter 边界语义不变。

## 1. 参与者与信任

| 角色 | 位置 | 提供的可信证据 | 提供的可信证据（不提供的） |
|---|---|---|---|
| 宿主 FastAPI | 宿主 | prepared 审计行、attempt_id、request_digest、authorization_id、receiver | 不提供 Worker 身份/网络/传输事实 |
| Launcher | Worker VM | 主令牌 TokenUser、挂起创建、受限令牌、Job 归属、进程 PID/创建时间/程序摘要、环境启动标识 | 不提供网络出口事实 |
| Worker | Worker VM | 实际发送字节摘要、`sent.marker`（可能发送判定） | 不提供服务商响应确认 |
| Egress relay | 专用网络边界 | 出口策略版本、单次转发事实、HTTP 状态、原始响应字节摘要、服务商请求标识 | 不提供 Worker 身份/目录隔离 |

调用者认证：宿主与 Launcher、Launcher 与 Egress 分别互认（证书或共享密钥）；
消息签名；`attempt_id` 防重放。

## 2. 授权请求（宿主 → Launcher）

```text
AuthorizationRequest {
  attempt_id: string            # = SendAuditRecord.attempt_id（随机 UUID，全局唯一，一次性）
  authorization_id: integer
  receiver: string              # 固定上游端点
  request_digest: string        # 不可变请求体 SHA-256，与审计行一致
  body_ref: BodyRef             # 见 §3
  model: string
  timeout_ms: integer
  nonce: string                 # 随机一次性，仅防重放；见 §4 与序号的区分
  policy_version: string
}
```

约束：
- `request_digest` 由 Launcher 在发送前对最终字节重算，必须与 `body_ref` 及审计行一致；
- 不允许同时篡改 body 与 job 摘要通过。

## 3. body_ref：跨 VM 字节传输方式与大小限制

`body_ref` 不是「句柄引用」（跨 VM 无共享文件句柄），而是以下二者之一：

- `sha256`：请求体字节的 SHA-256（内容寻址，唯一寻址方式）；
- 传输：宿主将**不可变请求体字节**经专用 IPC 通道一次性推送（不落地到 Worker
  可写目录；仅 Launcher 读入受保护内存/只读文件，Worker 只读）。

大小限制（待部署实测后终定，当前为约束上限）：

| 项 | 上限 | 说明 |
|---|---|---|
| 请求体 | 512 KiB | 超过即拒绝，不静默截断；合成业务内容远小于此 |
| 响应体 | 1 MiB | 与既有 `MAX_RESPONSE_BYTES` 一致；超过记 `response_too_large` |
| 单条 IPC 消息 | 1 MiB | 分片需带序号与尾部摘要 |

- 字节一经推送即不可变：Launcher 与 Egress 均以 `sha256` 复核，任何重编码/改写都使
  `request_digest` 不匹配而拒绝。

## 4. 防重放：随机唯一标识 vs 单调序号（不混淆）

- `attempt_id`：**随机 UUID**（不可预测），全局唯一，一次发送一条收据；重复即拒绝。
- `nonce`：**随机一次性值**，仅用于单条 IPC 消息防重放；重复即拒绝。
- **不使用单调递增序号作为防重放凭据**：单调序号只用于审计排序/展示，可预测、
  可被重放攻击利用，不作为授权凭据。二者职责分离，禁止混用。

持久化：宿主在 prepared 审计行持久化 `attempt_id`；Launcher/Egress 各自持久化已见
`attempt_id`（一次性集合）用于重复检测；重启后从持久化集合恢复，不依赖内存。

## 5. 发送收据：签发者 / 验证者 / 有效期 / 审计绑定

```text
SendReceipt {
  attempt_id: string
  sent: bool
  http_status: integer | null
  provider_request_id: string | null
  raw_response_sha256: string | null   # 原始响应字节摘要（非解析文本）
  parsed_text_sha256: string | null
  terminal_phase: "confirmed_sent" | "possibly_sent" | "not_sent"
  policy_version: string
  issuer: "egress"                     # 签发者
  issued_at: string
  expires_at: string                   # 有效期（短暂，防止陈旧收据重放）
  signature: string                    # 签发者签名
  evidence: EvidenceRef[]
}
```

- **签发者**：Egress relay（唯一签发 `confirmed_sent`/`possibly_sent`）。
- **验证者**：宿主核验 `signature`、`issuer`、`issued_at`、`expires_at`、`attempt_id`
  与 prepared 行一致，且未过期。
- **审计绑定**：收据的 `attempt_id` 必须命中已持久化的 prepared 行；收据写入即生成
  唯一终态行（既有 0008 部分唯一索引兜底）。过期/签名不符的收据不落终态。

## 6. 重启 / 超时 / 重复请求 / 发送状态未知

| 情形 | 处理 |
|---|---|
| 宿主重启，prepared 无终态 | `reconcile_orphan_attempts` 补 `possibly_sent`（已有）；不补 confirmed/not_sent |
| Launcher 重启，未收到收据 | 与宿主 `attempt_id` 对账；无收据则保持未知，不伪造 |
| 超时 | `possibly_sent`（请求可能已写出）；不凭超时判 confirmed |
| 重复 `attempt_id`/`nonce` | 直接拒绝，返回明确错误 |
| 发送状态未知 | `possibly_sent`，绝不升格 confirmed_sent / 降格 not_sent |

## 7. 固定请求体 vs 实际发送字节 SHA-256 对账

- 宿主：对不可变请求体算 `request_digest`，写入 prepared 行。
- Launcher：发送前重算，与 `body_ref`/审计行一致才放行。
- Egress：对实际转发字节重算，与 `request_digest` 一致才转发，否则拒绝并记事件。
- 三者任一不一致 → 拒绝，且不回退为「未知但仍发送」。

## 8. 可信证据收集接口（跨 VM，见 detailed-plan §8）

证据记录统一结构，**生产拒绝手填布尔值、synthetic 证据**：

```text
EvidenceRecord {
  source: "host" | "launcher" | "egress"     # 证据来源
  subject_sid: string                        # 主体（身份证据）或 null
  environment_boot_id: string                # 环境标识
  policy_version: string                     # 策略版本
  collected_at: string
  expires_at: string                         # 有效期
  signature: string                          # 采集器/签发者签名
  invalidation: string[]                     # 失效条件（进程重建/策略变更/超时）
  payload: object                            # 该来源可提供的原始证据
}
```

失效条件明确：Worker 进程重建、网络策略版本变更、环境启动标识变化、有效期过期
任一成立即失效，不得沿用。

## 9. 边界与 fail-closed

- IPC 只交换有界任务与收据；无通用命令/文件系统/shell 通道。
- 任一认证、完整性、重放、身份、覆盖、拒绝观测不满足 → 拒绝发送（not_sent/possibly_sent 如实）。
- 首次发送前不要求首次服务商响应或发送后摘要。
