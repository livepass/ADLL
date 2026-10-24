# S9-0 契约定稿修订记录（定向修订）

**日期**：2026-10-24　**基线**：`004f0f9`（= GitHub main）
**范围**：仅定向修订三个未解决问题，不重写已完成的五份规划。

## 1. 变更前后差异

### 1.1 跨 VM 证据来源（s9-detailed-plan.md §8）

| 变更点 | 前 | 后 |
|---|---|---|
| 证据来源 | 只采集宿主 Windows 防火墙规则 | 拆为 host / launcher / egress 三来源，各只提供其能可信证明的事实 |
| Guest 隔离证据 | 未明确（隐含由宿主推断） | 明确由 Guest 内 / 出口侧可信采集器提供，宿主不代填 |
| 可信收集接口 | 无统一结构 | 新增 `EvidenceRecord{source, subject_sid, environment_boot_id, policy_version, collected_at, expires_at, signature, invalidation[], payload}` |
| 失效条件 | 未定义 | 进程重建 / 策略版本变更 / 环境启动标识变化 / 有效期过期任一成立即失效 |

### 1.2 固定出口与凭据归属（s9-detailed-plan.md §7）

| 变更点 | 前 | 后 |
|---|---|---|
| 出口类型 | 未区分 | 裁定为**应用层受控出口**（非透明转发），理由：满足固定 Messages POST 校验 + 摘要复核 + 收据 |
| API Key 位置 | Worker 环境变量注入 | **固定出口持有**，Worker 不接触 Key |
| 与现有契约 | 未指出 | 明确列出与 `contracts/agent-adapter.md` §1「凭据环境变量注入 Agent 进程」的差异，**需人工批准**，不擅自修改 |
| 日志脱敏 | 只提 Worker | 出口 + 宿主对 Key/Authorization 头/正文一律脱敏，只记 SHA-256 与状态码 |

### 1.3 IPC 契约（contracts/s9-ipc-and-evidence.md）

| 变更点 | 前 | 后 |
|---|---|---|
| body_ref | `bytes-ref`（语义模糊） | 明确为「内容寻址 sha256 + 字节推送」，上限请求体 512 KiB / 响应 1 MiB / IPC 消息 1 MiB |
| 防重放 | `attempt_id`/`nonce` 未区分 | 明确 `attempt_id` 随机 UUID、`nonce` 随机一次性；**单调序号不作防重放凭据** |
| 收据 | 无签发/验证/有效期 | 新增 `issuer`/`issued_at`/`expires_at`/`signature`；签发者=Egress，验证者=宿主，审计绑定 prepared 行 |
| 重启/超时/重复/未知 | 未覆盖 | 逐项明确（reconcile → possibly_sent；未知不升格/不降格） |
| SHA-256 对账 | 只提发送前 | 明确 host / launcher / egress 三方对账，任一不一致拒绝 |

## 2. 剩余待人工决定事项

1. 是否批准「API Key 由固定出口持有、Worker 不接触 Key」这一对既有凭据契约的变更。
2. 部署宿主选定（本机升级 / 独立主机 / 云 VM）。
3. body_ref 大小上限（512 KiB / 1 MiB）是否接受，或需实测后再定。
4. 出口软件、虚拟交换机、控制通道、专用账户命名与凭据存储机制的具体选型。

## 3. S9-1 / S9-2 最小代码实现清单

（详见 s9-phased-tasks.md，此处摘要）

**S9-1（身份与进程隔离）**：
- `win32.py`：LogonUserW 主令牌 + TokenUser 验证；CREATE_SUSPENDED；恢复前身份复核；
  job.assign 失败补 terminate；最小环境 + 句柄白名单。
- `sandbox.py`：输入/输出权限分离。

**S9-2（审计绑定）**：
- `GenerationRequest` 加 `attempt_id`/`request_digest`；`_run_body` 直接传入；
  launcher 发送前复核；收据绑定唯一终态；`nonce` 与序号分离。

## 4. 各阶段 PASS / BLOCKED 验收标准

| 阶段 | PASS | BLOCKED |
|---|---|---|
| S9-1 | TokenUser 匹配 + 挂起创建 + Job 纳管 + 进程树回收；离线负向测试全通过 | 任一身份/纳管/回收失败，或负向测试未通过 |
| S9-2 | 摘要篡改/重放/跨任务替换被拒；attempt/authorization/receiver/request_digest 一致 | 任一绑定/重放/对账失败 |
| S9-3 | 非授权目的地拒绝观测；授权通道可达；无任意转发；Key 不落 Worker/日志 | Guest 隔离证据缺失，或有任意转发路径 |
| S9-4 | 缺发送前证据零外发；发送后收据/原始摘要/唯一终态齐全；跨 VM 来源正确 | 任一来源证据缺失/过期/签名不符未拒绝 |
| S9-5 | 实机矩阵全量 + 回滚演练通过 | 任一实机安全边界未通过 |

## 5. 边界

只改文档（3 份：s9-detailed-plan.md、contracts/s9-ipc-and-evidence.md、s9-phased-tasks.md）；
未创建 VM/账户、未改 ACL/防火墙、未装组件、未读 Key、未真实请求、未改 ADLL-Knowledge、
未 Commit/Push。等待人工批准后进入 S9-1/S9-2。
