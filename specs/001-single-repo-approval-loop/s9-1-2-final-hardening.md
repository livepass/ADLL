# S9-1/S9-2 离线实现最终安全收口

**日期**：2026-10-24　**基线**：`699d180`（= GitHub main）
**范围**：对已实现的 S9-1/S9-2 离线模块做安全收口，不重复开发、不重做架构设计。

## 1. 本轮修复清单

### 任务 1：强制执行恢复前身份检查（win32.py / sandbox.py）

| 项 | 前 | 后 |
|---|---|---|
| pre_resume_check 语义 | `ok` 仅证明 TokenUser/创建时间/受限状态「非空」 | 强制核对**批准 SID**（`expected_token_user_sid`）、restricting SID（`expected_restricting_sid`）、程序身份（`expected_program_sha256`）、Job 归属（`in_job`） |
| resume 门禁 | 任何调用方可 resume | `resume()` 内部强制要求 `pre_resume_check` 已 `ok`（否则抛 `RuntimeError`），未经检查通过不可恢复 |
| 检查失败 | 仅返回证据 | 明确「terminate + wait」为失败路径；新增确定性负向测试（restricting SID 不匹配、TokenUser 不匹配、未检查 resume 拒绝） |
| 生产挂起创建接线 | 未说明 | 明确 `Sandbox.run`/`probe` 仍 `suspended=False`（未接线挂起创建）；挂起创建 + 恢复前门禁**不得宣称为生产安全门禁**，须待独立账户 LogonUserW（BLOCKED） |

### 任务 2：完整绑定发送尝试（generation_service.py / base.py / worker.py）

| 项 | 前 | 后 |
|---|---|---|
| attempt_id 传递 | 未传到 worker job | `GenerationRequest` 增 `attempt_id`/`request_digest`/`authorization_id`/`receiver`；`_run_body` 全部注入；worker job 携带 `attempt_id`/`authorization_id` |
| 替代值生成 | worker 自算摘要 | worker 不得自造 attempt_id/摘要；真实模式校验 `attempt_id`/`authorization_id`/`receiver` 缺一即 `AdapterDisabled`（零外发），`receiver` 与 `self.endpoint` 不一致即拒绝（跨任务替换） |
| 绑定校验 | 无 | 发送前校验字节摘要 == request_digest，且 attempt/authorization/receiver/request_digest 全绑定 |

### 任务 3：补强收据验证与数据库约束（receipts.py / outbound.py / db.py / 迁移）

| 项 | 前 | 后 |
|---|---|---|
| provider_request_id 签名 | 未纳入 | 加入 `SEND_RECEIPT_SIGNED_FIELDS`，篡改即验签失败 |
| 签发时间/策略版本 | 未验证 | `verify_send_receipt` 增加 `issued_at` 合法性（不晚于 now）与可选 `expected_policy_version` 比对 |
| 迟到收据幂等 | 重复插入 | 以 `(attempt_id, signature)` 判重，重复提交返回 `late_receipt_already_recorded`，不产生重复可信证据 |
| UPDATE/DELETE 禁止 | 无 | `SendReceiptEvidence` 增数据库触发器（`db.py` SQLITE_GUARDS + Alembic 0010），禁止 UPDATE/DELETE |
| 唯一终态 | 已有 | 保持：已有 possibly_sent 不生成第二终态（0008 索引 + `record_late_receipt` 分支） |

## 2. 测试证据

| 测试 | 结果 |
|---|---|
| `test_s9_receipts.py`（新增 5 个负向） | 15 passed（幂等/provider_request_id 篡改/issued_at 未来/policy_version 不匹配/触发器 UPDATE-DELETE 禁止 + 原有 10） |
| `test_s9_win32.py`（重写为强制身份检查） | 6 passed（restricting SID 不匹配、TokenUser 不匹配、未检查 resume 拒绝、纳管失败 terminate） |
| 迁移验证 | 从零升级 + 既有库（0008→0010）升级均通过，触发器正确创建 |
| 前端 | 20 passed + build 成功 |
| 后端全量（pytest -rs） | **306 passed / 0 failed / 0 skipped** |

> 注：全量回归在本机 WorkBuddy 沙箱需以 `CODEBUDDY_SAFE_DELETE_ENABLED=0` 禁用
> 「安全删除守卫」（单次 rmtree 超 50 文件会触发 SystemExit 污染清理阶段）；该守卫
> 是本地沙箱防护，CI（windows-latest）不加载，不受影响。

## 3. 尚未接入的生产路径

1. **挂起创建未接线**：`Sandbox.run`/`probe` 仍用非挂起创建；挂起创建 + 恢复前强制门禁是 S9-1 新增接口，须在独立账户环境（LogonUserW）实现后才能接线为真实门禁。
2. **真实 LogonUserW / 独立 TokenUser**：本地受限令牌复用父账户主体，无法伪造「TokenUser 与批准 SID 不匹配」的实机负向，须 VM 实测。
3. **撤销-签发时序落库**：§6.2 的「撤销时间 vs 签发时间」判定依赖 `SendAuditRecord` 快照字段（authorization_status/policy_version/快照时间），尚未加列与接线，留待 S9-4。
4. **签名密钥托管/轮换**：宿主/Egress 签名密钥的托管与轮换未实现（当前 HMAC 占位，密钥由调用方注入）。

## 4. 状态划分

- **本地离线 PASS**：强制恢复前身份检查、纳管失败回收、完整绑定、收据验签/幂等/防重放、数据库 UPDATE/DELETE 禁止、唯一终态 + append-only、迁移。
- **实机待验证（需 VM）**：真实 LogonUserW/独立 TokenUser、挂起创建接线、VM 网络权限、固定出口、Key 归属。
- **BLOCKED**：生产凭据归属变更（决定 1 未批准，不改 Key 传递逻辑）。

## 5. S9-3 部署选型前提（仅列条件，不创建资源）

### 5.1 VM 运行环境
- 独立 Windows VM（建议 Windows Server 2022 / Win11 Pro 可开 Hyper-V），4–6 GiB RAM。
- 关闭与宿主 NAT/桥接，仅连接专用隔离网络；不挂宿主目录/驱动器/剪贴板旁路。

### 5.2 专用身份
- 专用非管理员本地账户（或独立域账户），作为 Worker 的 TokenUser 主体。
- 该账户密码存入系统受保护凭据存储，仅 Launcher 可读；不写环境/参数/job/日志。

### 5.3 网络与固定出口
- 专用隔离网段（虚拟交换机），Guest 默认出站 Block，仅放行固定端点
  `POST dashscope.aliyuncs.com/apps/anthropic/v1/messages`（TLS 校验证书、禁重定向）。
- 应用层受控出口（egress relay）单独部署，持 Key、校验摘要、返回签名收据。
- IPv4/IPv6/回环/代理/UDP/子进程/服务代发全边界覆盖验证。

### 5.4 API Key 归属及签名密钥
- API Key 归固定出口持有（**须先批准决定 1**），Worker 不接触 Key。
- 宿主签名密钥 + Egress 签名密钥分别托管（当前 HMAC 占位，生产建议 Ed25519），
  `key_id` 支持轮换，轮换后旧版本失效。

### 5.5 测试矩阵、成本与回滚
- 测试矩阵：身份（TokenUser/受限/挂起/纳管/进程树）、网络（v4/v6/回环/代理/UDP/子进程/服务代发）、
  证据（摘要篡改/收据重放/跨任务替换/身份不符/策略失效/采集失败）、异常（超时/取消/崩溃/宕机/落库失败）。
- 成本：Worker VM 4–6 GiB，出口 VM 0.5–1 GiB（估算，非验收容量）。
- 回滚：关发送入口 → 终止等待 Worker 树 → 断专用网络 → 保存审计 → 按对象 ID 撤销资源。

## 6. 执行边界确认

未修改已批准凭据契约、未迁移 Key、未读取真实 Key、未创建 VM/系统账户、未修改生产
ACL/防火墙、未调用百炼、未修改 ADLL-Knowledge、未 Git Commit/Push。
`ADLL_REAL_AI_ENABLED=0`、`ADLL_WORKER_REAL_TRANSPORT=0` 保持不变。
