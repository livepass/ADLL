# S9-0 契约定稿修订记录（定向修订 + 最终验收）

**日期**：2026-10-24　**基线**：`c2cc181`（= GitHub main）
**范围**：仅定向修订三个未解决问题，不重写已完成的五份规划。
**本轮动作**：契约收口（§2.1 / §5.1 / §6.1）+ S9-1/S9-2 实施准备 + 人工待批准项梳理。
未做任何部署、未创建 VM/账户、未改 ACL/防火墙、未读 Key、未真实百炼调用、未 Commit/Push。

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

### 1.4 本轮三项契约收口（contracts/s9-ipc-and-evidence.md）

| 编号 | 收口项 | 新增小节 | 要点 |
|---|---|---|---|
| A | 固定出口签名收据绑定实际请求 | §5.1 | 签名体必含 `attempt_id`/`authorization_id`/`receiver`/`request_digest`/`actual_body_sha256`/`policy_version`/`issuer`/`key_id`；`actual_body_sha256` 由出口对实际转发字节重算，禁止回显调用方填写的 `request_digest`；宿主用 `key_id` 验签并比对 `actual_body_sha256 == prepared.request_digest` |
| B | 宿主重启后收到迟到收据 | §6.1 | 不违反 0008 唯一终态（不写第二终态）、不改写历史行、有效迟到收据以追加证据保留、不自动生成 verified 方案、超时/重放/未知保持 fail-closed |
| C | Launcher 无权读审批 DB | §2.1 | 新增宿主签名 `HostAuthorizationReceipt`（含 attempt_id/authorization_id/receiver/request_digest/authorization_status/policy_version/有效期/签名/key_id），Launcher 验签后以其 `request_digest` 为基准复核，不信任调用方填写的 `request_digest` |

## 2. 剩余待人工决定事项（本轮仍需用户签署）

1. **（必须签署）** 是否批准「API Key 由固定出口持有、Worker 不接触 Key」这一对既有
   凭据契约 `contracts/agent-adapter.md` §1 的变更。**该决定涉及已批准的凭据契约，
   未经批准不得视为已获批准，也不得进入真实发送实现。**
2. 部署宿主选定（本机升级 / 独立主机 / 云 VM）。
3. body_ref 大小上限（512 KiB / 1 MiB）是否接受，或需实测后再定。
4. 出口软件、虚拟交换机、控制通道、专用账户命名与凭据存储机制的具体选型。
5. `HostAuthorizationReceipt` 的宿主签名密钥（`key_id`）托管与轮换机制。

## 3. S9-1 / S9-2 精确代码修改清单

「本地可验证」= 可在开发机用离线/合成数据跑测试验证；
「必须 VM 实测」= 依赖真实独立 Worker VM / 专用网络 / 真实 OS 身份，本地无法证明。

### 3.1 S9-1：身份与进程隔离改造

| # | 文件 | 修改 | 本地可验证 / 必须 VM 实测 |
|---|---|---|---|
| 1.1 | `backend/app/isolation/win32.py` | 新增 `LogonUserW(LOGON32_LOGON_BATCH)` 获取专用非管理员账户主令牌，验证 `TokenUser.SID == ADLL_WORKER_PRINCIPAL_SID`（新函数 `logon_worker_token`） | 必须 VM 实测（依赖专用账户 + 真实域/本机账户） |
| 1.2 | `backend/app/isolation/win32.py` | `CreateProcessAsUserW` 增加 `CREATE_SUSPENDED`（`spawn_restricted` 增加 `suspended` 参数）；显式可执行路径 + 最小环境 + 句柄白名单 | 必须 VM 实测（挂起/恢复为真实 Win32 语义） |
| 1.3 | `backend/app/isolation/win32.py` | 恢复前复核子进程真实 TokenUser / PID / 创建时间 / 程序摘要 / 受限状态；新增 `resume` 前检查分支，不符即 terminate | 必须 VM 实测（真实令牌信息查询） |
| 1.4 | `backend/app/isolation/win32.py` | `job.assign` 失败分支补 `terminate + wait`（当前 `spawn_restricted` 第 498-503 行已 `job.close()` 但未先 terminate，需补 terminate 后再 close） | 本地可验证（合成 job 句柄失败路径单元测试）；VM 实测兜底 |
| 1.5 | `backend/app/isolation/sandbox.py` | 输入（脚本/授权子集/请求体）只读、输出（work_dir/result）独立可写：确认 `_allow_restricted_read` 只对 root/subset/scripts 授 ReadAndExecute，work_dir 授 Modify（现状已具备，补显式断言与测试） | 本地可验证（合成 ACL 测试） |
| 1.6 | `backend/app/isolation/sandbox.py` | 完整进程树回收：`cancel`/`close` 走 `job.terminate()` + `wait`，确认无遗留未纳管子进程（补 kill-on-close 语义测试） | 本地可验证（合成 job）；VM 实测进程树 |

### 3.2 S9-2：审计与请求体直接绑定

| # | 文件 | 修改 | 本地可验证 / 必须 VM 实测 |
|---|---|---|---|
| 2.1 | `backend/app/agents/base.py` | `GenerationRequest` 增加 `attempt_id: str | None`、`request_digest: str | None` 字段 | 本地可验证 |
| 2.2 | `backend/app/services/generation_service.py` | `_run_body` 在 `_record_attempt` 返回 `attempt_id` 后，把 `attempt_id` 与 `prepared.request_digest` 传入 `GenerationRequest`（现第 195-202 行构造处补两字段） | 本地可验证 |
| 2.3 | `backend/app/agents/worker.py` | `generate()` 不再自行 `hashlib.sha256(body_bytes)` 重算（现第 155-157 行），改用 `request.request_digest` 传入 job；发送前由 worker 对不可变字节复核（`worker_main.body_digest_error` 已具备） | 本地可验证（合成正反例） |
| 2.4 | `backend/app/agents/worker.py` | 直接绑定持久化 prepared 审计记录：`request.attempt_id` 与 `SendAuditRecord.attempt_id` 一致才允许进入真实发送分支 | 本地可验证 |
| 2.5 | `backend/app/agents/worker.py` | 签名收据验证：宿主验签 + `actual_body_sha256 == request_digest` 比对 + 持久化防重放（`attempt_id` 一次性集合）+ 迟到证据追加（§6.1），新增 `verify_receipt()` / `record_late_receipt_evidence()` | 本地可验证（合成收据正反例） |
| 2.6 | `backend/app/services/outbound.py` | `finish_attempt` 保持唯一终态（已具备）；新增「迟到收据追加证据」路径，不写第二终态 | 本地可验证 |
| 2.7 | `backend/app/services/outbound.py` | 发送前对不可变字节**重新计算 SHA-256 核对**，不自行生成新的授权摘要（`request_digest` 一律取自 prepared 行） | 本地可验证 |

### 3.3 明确划分结论

- **本地可验证**：1.4 / 1.5 / 1.6（合成 job/ACL/进程树测试）、2.1–2.7（合成数据正反例、
  收据验签、重放、迟到证据、摘要篡改）。
- **必须独立 Worker VM 实测**：1.1 / 1.2 / 1.3（真实专用账户 `LogonUserW`、
  `CREATE_SUSPENDED`、真实 TokenUser 复核），以及 S9-3 的固定出口、网络默认拒绝、
  Key 归属（依赖决定 1 批准）。

## 4. 离线测试矩阵（合成数据，正反例）

| 阶段 | 用例 | 正向预期 | 负向预期 |
|---|---|---|---|
| S9-1 | TokenUser 匹配 | 批准 SID 匹配 → 放行 | 不匹配 → 拒绝且不启动 |
| S9-1 | 挂起创建 + 身份复核 | 挂起后复核通过 → 恢复 | 复核不符 → terminate |
| S9-1 | Job 纳管失败回收 | — | `job.assign` 失败 → terminate + wait，无遗留进程 |
| S9-1 | 输入只读 / 输出可写 | work_dir 可写结果 | subset/scripts/body 写被拒 |
| S9-1 | 进程树回收 | cancel/close 全树终止 | 子进程逃逸（breakaway）→ 仍被回收 |
| S9-2 | attempt_id/request_digest 绑定 | 与 prepared 行一致 → 放行 | 不一致 / 跨任务替换 → 拒绝 |
| S9-2 | 摘要篡改 | 字节未改 → 复核通过 | 字节改写 → `body_digest_mismatch` 拒绝 |
| S9-2 | 收据重放 | 首次收据落唯一终态 | 重复 `attempt_id` → 拒绝，不写第二终态 |
| S9-2 | 迟到收据（宿主重启后） | 追加证据，不改历史 | 过期/签名不符 → 拒绝；不自动 verified |
| S9-2 | 收据签名 | 有效签名 → 终态 | 签名不符 / `actual_body_sha256` 对不上 → 拒绝 |

## 5. 各阶段 PASS / BLOCKED 验收标准

| 阶段 | PASS | BLOCKED |
|---|---|---|
| S9-1 | TokenUser 匹配 + 挂起创建 + Job 纳管 + 进程树回收；离线负向测试全通过 | 任一身份/纳管/回收失败，或负向测试未通过 |
| S9-2 | 摘要篡改/重放/跨任务替换被拒；attempt/authorization/receiver/request_digest 一致 | 任一绑定/重放/对账失败 |
| S9-3 | 非授权目的地拒绝观测；授权通道可达；无任意转发；Key 不落 Worker/日志 | Guest 隔离证据缺失，或有任意转发路径 |
| S9-4 | 缺发送前证据零外发；发送后收据/原始摘要/唯一终态齐全；跨 VM 来源正确 | 任一来源证据缺失/过期/签名不符未拒绝 |
| S9-5 | 实机矩阵全量 + 回滚演练通过 | 任一实机安全边界未通过 |

## 6. GitHub Actions 验收（run 40062693232）

**URL**：https://github.com/livepass/ADLL/actions/runs/40062693232　**基线**：`c2cc181`（push 到 main）

| job | 平台 | 结论 | passed | failed | skipped | 说明 |
|---|---|---|---|---|---|---|
| backend | windows-latest | success | 285 | 0 | 0 | `pytest -q` 全绿（数量取自本地基线；CI 步骤 `Test` 为 success，无失败） |
| frontend | ubuntu-latest | success | 20 | 0 | 0 | `npm test`（vitest）20 passed / 20，`npm run build` 成功 |

- 后端 `pytest -q` 无 `-x` 亦无失败即整体 success；本地历史基线为 285 passed，skipped 0。
- 前端 3 个测试文件（GenerationPanel 6、client 8、previewGate 6）共 20 passed，build 成功。
- 仅 1 条非阻断 warning：actions/checkout、actions/setup-node 在 Node.js 20 已弃用、
  被强制以 Node 24 运行（不影响结论）。

## 7. GO / NO-GO 结论

**本轮 GO 项**（已完成，可离线验证）：
- 契约三项收口（§2.1 / §5.1 / §6.1）落稿，未改已批准契约。
- S9-1/S9-2 精确代码修改清单与离线测试矩阵产出，实现路径清晰。
- 本地基线测试全绿（后端 285 passed、前端 20 passed + build OK）。

**本轮 NO-GO / 阻塞项**（需人工批准后方可继续）：
- **决定 1（凭据归属变更）未批准** → S9-2「Key 由出口持有」及 S9-3 全部阻塞，
  禁止进入真实发送实现。
- S9-1 的 1.1/1.2/1.3 依赖独立 Worker VM，本地无法验证，需部署宿主确定后实测。

**结论**：S9-0 契约收口完成，S9-1/S9-2 已具备实施准备；**在决定 1 获人工批准前，
不进入任何真实发送实现，不创建 VM/账户、不改 ACL/防火墙、不读 Key、不做真实调用。**

## 8. 边界

只改文档（s9-detailed-plan.md、contracts/s9-ipc-and-evidence.md、s9-phased-tasks.md
+ 本修订记录）；未创建 VM/账户、未改 ACL/防火墙、未装组件、未读 Key、未真实请求、
未改 ADLL-Knowledge、未 Commit/Push。等待人工批准后进入 S9-1/S9-2。
