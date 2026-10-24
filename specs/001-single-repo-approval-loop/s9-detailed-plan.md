# S9 详细技术规划草案（独立 Windows Worker VM）

**日期**：2026-10-24　**基线**：`5c4aa56`
**状态**：DRAFT（规划草案，待人工审批；不进入编码/部署）
**上位依据**：[s9-isolation-architecture-decision.md](./s9-isolation-architecture-decision.md)（已批准路线）
**宪章**：v1.2.0 RATIFIED

本草案只规划，不修改已批准 spec/plan/tasks/contracts，不删除历史记录。
部署位置待定（见 [s9-deployment-feasibility.md](./s9-deployment-feasibility.md)）。

## 1. 部署边界：FastAPI 宿主 vs Windows Worker VM

| 组件 | 位置 | 职责 | 禁止 |
|---|---|---|---|
| FastAPI 后端（模块化单体） | 宿主（现本机或独立宿主） | 任务/审批/授权/审计/核验/编排；保存 prepared 审计行；发起 IPC | 不持 Worker 凭据明文；不直接联网发送；不提升权限 |
| 受保护启动器（launcher） | Worker VM 内，独立进程 | 用专用账户主令牌派生受限 Worker，挂起创建、身份核验、Job 纳管 | 不暴露通用命令/转发 |
| Worker 进程 | Worker VM 内，受限令牌 + 专用 TokenUser | 读取不可变请求体，单次 POST 到固定出口 | 不读宿主仓库/DB/用户目录/凭据存储；不通用 DNS |
| 固定出口（egress relay） | 专用网络边界 | 仅接受固定 Messages POST，校验摘要，转发到上游，返回收据 | 不做通用 CONNECT/SOCKS/URL 代理；不转任意 IP |

关键：**IPC 只交换有界任务与收据，不提供通用命令、文件系统或 shell 通道**。

## 2. 最小 IPC 协议（宿主 → VM）

- 传输：仅回环专用通道或专用网段（依部署位置），**不暴露到宿主默认网络**。
- 认证：调用者（FastAPI）与 launcher 互相认证（证书或共享密钥），
  消息签名防篡改，`attempt_id` 单调且全局唯一防重放。
- 消息结构（示意，最终入 contracts）：

```text
AuthorizationRequest {
  attempt_id: string        # 与 SendAuditRecord.attempt_id 一一绑定
  authorization_id: int
  receiver: string          # 固定上游端点
  request_digest: string    # 不可变请求体的 SHA-256，与审计行一致
  body_ref: handle/ref      # 不可变请求体（只读，不重编码）
  model: string
  timeout_ms: int
  nonce: string             # 重放保护
}
```

- 完整性：`request_digest` 由 launcher 在发送前对字节重算，必须与持久化
  审计行一致；不允许同时篡改 body 与 job 摘要通过。
- 重放保护：`attempt_id` 全局唯一 + 一次性收据；重复 `attempt_id` 直接拒绝。

## 3. 独立 TokenUser、受限令牌、挂起创建、Job 纳管、异常回收

（修复架构决策 §2 指出的三个缺口）

1. **独立 TokenUser**：launcher 用 `LogonUserW(LOGON32_LOGON_BATCH)` 获得专用
   非管理员账户主令牌，验证其 TokenUser SID == 批准的 `ADLL_WORKER_PRINCIPAL_SID`。
2. **受限令牌**：从该主令牌派生 `CreateRestrictedToken`（restricting SIDs 保持）。
3. **挂起创建**：`CreateProcessAsUserW(..., CREATE_SUSPENDED)`；显式可执行路径、
   最小环境、允许继承句柄白名单。
4. **身份复核**：恢复前经子进程句柄查询真实 TokenUser、PID+创建时间、程序摘要、
   受限状态；核对批准 SID 与受保护环境。
5. **Job 纳管**：`CREATE_SUSPENDED` 下先加入禁止 breakaway、kill-on-close 的 Job，
   全部成立后 `ResumeThread`；失败则 terminate 并等待，**不能只关闭未纳管进程句柄**
   （修 `job.assign` 失败分支缺 terminate）。
6. **异常回收**：超时/取消/launcher 退出 → 终止完整进程树，等待退出后再清理。

## 4. 任务/授权/attempt/request_digest/不可变请求体直接绑定

（修复 `GenerationRequest` 缺 `attempt_id`/`request_digest` 的缺口）

- `GenerationRequest` 增加 `attempt_id: str`、`request_digest: str` 字段，
  由 `_run_body` 在 `_record_attempt` 后直接传入，adapter 不再自行重算。
- 不可变请求体以内容寻址（SHA-256）引用，launcher 发送前对最终字节复核
  `request_digest`，与 `SendAuditRecord.request_digest` 强一致。
- 一次 attempt 唯一终态（已有 0008 部分唯一索引），收据绑定同一 `attempt_id`。

## 5. 固定目标出口（协议 / 证书 / 非通用代理 / 单次 / 收据）

- 上游固定域名+方法+路径（`POST dashscope.aliyuncs.com/apps/anthropic/v1/messages`），
  TLS 校验证书，禁重定向，不重编码已审核 JSON，不自动重试。
- 出口只接受固定 Messages POST，不提供通用 CONNECT/SOCKS/URL 代理，不转任意 IP。
- 单次请求；返回**收据**：真实传输回执、HTTP 状态、服务商请求标识（如有）、
  **原始响应字节摘要**（非解析文本摘要）、解析文本摘要。
- 首次发送前不要求首次服务商响应或发送后摘要；出口健康检查与业务载荷分离。

## 6. VM 网络默认拒绝边界

- Worker VM 仅连接专用隔离网络，不接宿主 NAT/桥接，无额外网卡。
- Guest 所有 Profile 默认出站 Block；仅允许指定主体/程序到固定出口地址端口。
- 边界覆盖：IPv4 + IPv6（或禁用并验证）、DNS（Worker 无通用 DNS 通道，
  可信解析器仅解析批准域名）、回环、代理、UDP、子进程、系统服务代发。
- 禁宿主目录/驱动器共享、剪贴板旁路；宿主默认出站策略不变。

## 7. 凭据存储 / 注入 / 轮换 / 清理 / 脱敏

- 专用账户密码存系统受保护凭据存储，仅 launcher 可读；不写环境/参数/job/日志。
- API Key 仅注入 Worker 环境，永不进聊天/日志/DB/evidence；调用后清除。
- 轮换：密码与 Key 分别轮换，轮换后旧证据失效（策略/身份版本递增）。

## 8. 发送前可信证据 vs 发送后实际结果（分别核验）

**发送前（全部成立才放行）**：实际 Worker TokenUser、PID+创建时间、环境启动标识、
镜像/程序摘要、Job 归属；生效网络策略/Profile/路由/接口/IPv4/IPv6/出口覆盖证明；
同身份/环境非授权目标拒绝观测（5157 PID/目标/Filter Runtime ID 关联）；prepared
审计行已提交且 attempt/authorization/receiver/request_digest 单次收据一致；采集器
身份/版本/时间/原始证据引用可复核。生产拒绝手填布尔值、synthetic 证据。

**发送后**：真实传输回执、HTTP 状态、服务商请求标识、原始响应字节摘要、解析文本
摘要、唯一终态、核验记录、隔离方案版本/策略摘要、满足验收时生成 ProposalVersion。

- 发送前拒绝 → `not_sent`；进入发送但证据不完整 → `possibly_sent`；
  充分响应证据 → `confirmed_sent`。取消不撤回已发。结果落库失败保留发送事实并阻断完成。

## 9. 实机测试矩阵、异常恢复、资源成本、精确回滚

| 类别 | 项目 |
|---|---|
| 身份 | TokenUser 匹配、受限令牌、挂起创建、Job 纳管、进程树回收、目录拒绝 |
| 网络 | v4/v6、回环、代理、UDP、子进程、服务代发均不能绕过出口 |
| 证据 | 摘要篡改、收据重放/跨任务替换、身份不符、策略失效、采集失败 |
| 异常 | 超时、取消、launcher 崩溃、出口宕机、结果落库失败 |
| 资源 | Worker VM 4–6 GiB；独立出口 VM 0.5–1 GiB（估算，非验收容量） |
| 回滚 | 先关发送入口 → 终止等待 Worker 树 → 断专用网络 → 保存审计 → 按对象 ID 撤销 |

## 10. 最小实施顺序与验收标准

见 [s9-phased-tasks.md](./s9-phased-tasks.md)。不复用 NO-GO 的 host block_all + allow_dashscope。
