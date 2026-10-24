# S9 IPC 与安全证据接口契约草案

**日期**：2026-10-24（R2 定向修订；R3 补 §2.1/§5.1/§6.1；R4 补 §5.1 全字段签名 + §6.2；R5 补 provider_request_id 签名覆盖）　**状态**：DRAFT（待审批；不改已批准 contracts/agent-adapter.md）
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

### 2.1 Launcher 无权读审批 DB：经认证、完整性保护的宿主授权收据确认绑定

Launcher 运行在 Worker VM 内，**无权读取宿主审批数据库**（无 DB 连接、无审批服务
身份、无法查询 `SendAuditRecord` 或 `OutboundAuthorization`）。因此 Launcher 不能自行
核验「prepared 行存在且与本次请求绑定」，也不能**只相信调用方在
`AuthorizationRequest` 里填写的 `request_digest`/`authorization_id`/`attempt_id`**。

宿主在 `AuthorizationRequest` 之外，随请求下发一条**宿主签名授权收据**
（`HostAuthorizationReceipt`，由宿主签名，签名体含以下字段）：

| 字段 | 说明 |
|---|---|
| `attempt_id` | 与 `SendAuditRecord.attempt_id` 一致 |
| `authorization_id` | 已批准授权记录 id |
| `receiver` | 固定上游端点（宿主从授权记录读取） |
| `request_digest` | 宿主对**不可变请求体**算得的 SHA-256 |
| `authorization_status` | 宿主下发时该授权确为 `APPROVED` 且未撤销/未过期 |
| `policy_version` | 宿主认可的出站策略版本 |
| `issued_at` / `expires_at` | 收据有效期（短暂） |
| `signature` / `key_id` | 宿主签名与密钥标识 |

约束（强制）：

- Launcher 只接受**宿主签名、未过期**的 `HostAuthorizationReceipt`；验签失败、过期、
  字段与 `AuthorizationRequest` 不一致 → 拒绝，不启动 Worker。
- Launcher **不得**仅凭 `AuthorizationRequest` 里调用方填写的 `request_digest` 放行；
  它必须以收据中的 `request_digest` 为基准，对实际推送字节重算并比对（§7）。
- 该收据**不替代**宿主侧 `SendAuditRecord` 唯一终态与审计绑定；它只解决「远端无法
  查库、如何可信确认 prepared 绑定」的问题，是宿主授权的**完整性保护凭证**，而非
  Worker/Launcher 的发送授权来源。
- 收据经认证通道下发（与 §1 的宿主↔Launcher 互认同一通道），不通过可被 Worker 篡改
  的 job 文件或环境变量传递。

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

### 5.1 签名收据必须绑定实际请求（不信任调用方填写的 request_digest）

固定出口的签名收据不得只是一句「已转发某 attempt」——它必须由出口**对其真实转发
的字节**与请求上下文一并签名，使收据可被宿主独立复核到「这一次实际请求」。

`SendReceipt` 的**签名覆盖内容（规范化后签名）**必须覆盖**全部影响发送事实及有效性**
的字段（任一缺失或对不上即视为签名不符、不落终态）：

| 字段 | 来源 | 说明 |
|---|---|---|
| `attempt_id` | 宿主 → Launcher → Egress | 随机 UUID，与 prepared 行一致 |
| `authorization_id` | 宿主 → Launcher → Egress | 与 prepared 行一致 |
| `receiver` | 宿主（固定上游端点） | 出口实际连接的上游端点，必须等于 prepared 行 |
| `request_digest` | 宿主对不可变请求体算得 | prepared 行已持久化的 SHA-256 |
| `actual_body_sha256` | Egress 对**实际转发字节**重算 | 出口真实收到的请求体摘要；宿主据此与 `request_digest` 比对 |
| `terminal_phase` | Egress | 终态判定（confirmed_sent / possibly_sent / not_sent），签名必须绑定，防止终态被改写 |
| `http_status` | Egress | 上游 HTTP 状态；影响「是否确实已发送」的事实，必须签名覆盖 |
| `raw_response_sha256` | Egress | 原始响应字节摘要；影响发送事实的证据，必须签名覆盖 |
| `provider_request_id` | Egress | 服务商请求标识；影响发送事实关联与去重，必须签名覆盖 |
| `policy_version` | Egress | 出口生效的转发/校验策略版本 |
| `issuer` | 常量 `"egress"` | 签发者身份 |
| `key_id` | Egress | 本次签名所用密钥标识（支持轮换） |
| `issued_at` | Egress | 签发时间，进入签名体，防止回填 |
| `expires_at` | Egress | 过期时间，进入签名体，防止陈旧收据重放 |

规范化与签名方式：

- 上述字段按**固定键名排序**拼接为规范化字节串（`canonical_payload_bytes` 同源
  算法，UTF-8、`ensure_ascii=False`、`sort_keys=True`），再以 Egress 私钥签名；
  `key_id`、`issued_at`、`expires_at` 一并进入签名体，宿主用对应公钥验签。
- `actual_body_sha256` 是出口对**实际接收字节**独立重算的摘要，不是回显宿主传入的
  `request_digest`；出口禁止把调用方/宿主传来的 `request_digest` 原样写回收据充当
  `actual_body_sha256`。
- 终态、HTTP 状态、原始响应摘要、签发时间、过期时间均为**签名覆盖字段**：任何一项
  被篡改都会导致验签失败；因此「签名的收据」即「可信的发送事实 + 有效期」的原子绑定。

宿主验证方式（收到收据后）：

1. 用 `key_id` 取公钥，验签；验签失败 → 不落终态，记安全事件。
2. 校验 `attempt_id` 命中已持久化的 prepared 行，且 `authorization_id`、`receiver`
   与该行一致；不一致 → 拒绝（视为跨任务替换）。
3. 比对 `actual_body_sha256 == prepared.request_digest`；不等 → 拒绝（字节被改写）。
4. 校验 `issued_at`/`expires_at` 未过期、`policy_version` 受宿主认可。
5. 全部通过才把收据作为本次 attempt 的唯一终态落库；任一失败按 §6 处理，不得生成
   `verified` 方案。

## 6. 重启 / 超时 / 重复请求 / 发送状态未知

| 情形 | 处理 |
|---|---|
| 宿主重启，prepared 无终态 | `reconcile_orphan_attempts` 补 `possibly_sent`（已有）；不补 confirmed/not_sent |
| Launcher 重启，未收到收据 | 与宿主 `attempt_id` 对账；无收据则保持未知，不伪造 |
| 超时 | `possibly_sent`（请求可能已写出）；不凭超时判 confirmed |
| 重复 `attempt_id`/`nonce` | 直接拒绝，返回明确错误 |
| 发送状态未知 | `possibly_sent`，绝不升格 confirmed_sent / 降格 not_sent |

### 6.1 宿主重启后收到迟到收据（追加证据，不改写历史、不自动 verified）

宿主重启后，`reconcile_orphan_attempts` 可能已把该 attempt 保守补记为
`possibly_sent`。此时若又收到一条**有效迟到收据**，处理规则如下：

1. **不违反 0008 唯一终态约束**：迟到收据**不得**再写入一条 `confirmed_sent`/`not_sent`
   终态行（那样会与既有的 `possibly_sent` 终态冲突，触发部分唯一索引）。迟到收据
   只能以**追加证据**方式保留。
2. **不改写历史 SendAuditRecord**：既有 `prepared` 行与 `possibly_sent` 终态行一律
   保持原样（append-only，数据库触发器 + 应用层均不改写）。
3. **有效迟到收据以追加证据保留**：为迟到收据新增一条**非终态**的证据行（phase 保持
   非终态语义，或以独立 `receipt_evidence` 结构挂到 `attempt_id`），记录其完整
   签名、`actual_body_sha256`、`policy_version`、`key_id`、`issued_at`/`expires_at`、
   验签结果。该证据行不计入唯一终态，因此不触碰 0008 约束。
4. **不因收据到达自动生成 verified 方案**：迟到收据只补审计完整性，**不**触发新的
   核验/`verified`/`ProposalVersion` 生成。已因重启判 `failed`/`possibly_sent` 的执行
   终态不回退、不重开。
5. **超时、重放、未知状态保持 fail-closed**：
   - 迟到收据过期（`expires_at` 已过）→ 拒绝，不落任何证据；
   - 签名不符 / `actual_body_sha256` 对不上 → 拒绝，记安全事件；
   - `attempt_id` 重复 / 已有终态 → 只按「已终结」拒绝，不改写、不追加第二次终态；
   - 收到收据但无法确证其与 prepared 行一致 → 保持 `possibly_sent`，绝不升格
     `confirmed_sent`。

### 6.2 过期收据与撤销边界的信任分离

- **过期收据不能成为新发送授权**：`expires_at` 已过的收据（无论签名是否有效）不得
  作为任何新 attempt 的授权来源，也不得据此判 `confirmed_sent`。审计保留与信任判定
  分离——过期收据可以因审计需要保留为证据（若签名有效且 attempt 匹配），但其
  **信任值恒为零**：不落终态、不升格状态、不生成 verified。
- **授权撤销与收据签发之间的生效边界必须可验证**：宿主在 `attempt_id` 落 prepared 时
  记录授权快照（`authorization_status`、`policy_version`、快照时间）。Egress 签发的
  收据必须带 `issued_at` 与 `policy_version`；宿主核验时要求
  `issued_at >= prepared 快照时间` 且 `policy_version` 与快照一致。若授权在 prepared
  之后、`issued_at` 之前被撤销，宿主必须在核验时拒绝（收据虽签名有效，但其签发生效
  边界落在撤销之后）。该判定由宿主依据「撤销时间 vs 收据签发时间」的时序完成，不
  依赖 Egress 自证。

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
