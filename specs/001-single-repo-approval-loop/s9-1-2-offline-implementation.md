# S9-1 / S9-2 离线实现记录

**日期**：2026-10-24　**基线**：`2912856`（= GitHub main）
**范围**：只实现无需真实独立账户/VM 即可开发与离线验证的部分；真实
LogonUserW / 独立 TokenUser / VM 网络权限须在专用环境另行验收。

## 1. 实施前检查

| 项 | 结果 |
|---|---|
| 本地 Git 工作区 | 干净（仅 `.specify/` 未跟踪，保持不纳入），HEAD = `29128564f4a935b11dab3696afe4727a4400c77b` |
| RATIFIED 宪章 | `.specify/memory/constitution.md` v1.2.0，Status=RATIFIED，Ratified=2026-10-17 |
| Spec Kit 审批流程 | 宪章 Governance：修订草案 → 人工审批 → 更新并递增版本；Agent 不得自批 |
| 契约差异 | 新 S9 契约 `s9-ipc-and-evidence.md` 为 DRAFT，**不覆盖**已批准 `agent-adapter.md` §1 凭据契约 |
| 执行边界 | 未改 `real_ai_enabled`（默认 False）/`worker_real_transport`（默认 False）；未改 Key 传递逻辑 |

## 2. 最小契约修正（contracts/s9-ipc-and-evidence.md，R4）

- §5.1：签名覆盖字段补全为**全部影响发送事实及有效性**的字段，新增
  `terminal_phase`、`http_status`、`raw_response_sha256`、`issued_at`、`expires_at`。
- §6.2（新增）：过期收据不能成为新发送授权（审计保留与信任判定分离）；
  授权撤销与收据签发之间的生效边界必须可验证（宿主依「撤销时间 vs 签发时间」时序判定）。

## 3. 代码修改清单

### S9-1（身份与进程隔离，离线部分）

| 文件 | 修改 |
|---|---|
| `app/isolation/win32.py` | 新增 `CREATE_SUSPENDED` 常量；`spawn_restricted` 增加 `suspended` 参数，挂起创建 + 保留主线程句柄；新增 `get_process_token_user` / `get_process_creation_time` / `pre_resume_check` / `PreResumeCheck`；`RestrictedProcess` 增加 `thread_handle` 与 `resume()`；`job.assign` 失败补 `TerminateProcess + WaitForSingleObject + 释放句柄` |

### S9-2（审计绑定与收据，离线部分）

| 文件 | 修改 |
|---|---|
| `app/agents/base.py` | `GenerationRequest` 增加 `attempt_id` / `request_digest` 字段 |
| `app/services/generation_service.py` | `_run_body` 把 `attempt_id` 与 `prepared.request_digest` 传入 `GenerationRequest` |
| `app/agents/worker.py` | `generate()` 不再自行 `hashlib.sha256` 重算，改用 `request.request_digest`；真实模式重算仅为比对，不一致即 `request_digest_mismatch` 拒绝 |
| `app/models/outbound.py` | 新增 `SendReceiptEvidence`（append-only 证据表，独立于唯一终态索引） |
| `app/models/__init__.py` | 导出 `SendReceiptEvidence` |
| `alembic/versions/0009_send_receipt_evidence.py` | 新建迁移 |
| `app/services/receipts.py`（新） | 宿主授权收据 + 出口发送收据数据结构、HMAC 签名/验签、防重放、迟到证据追加 |

## 4. 测试证据

| 测试文件 | 结果 | 说明 |
|---|---|---|
| `tests/test_s9_receipts.py`（新） | 10 passed | 摘要篡改/跨任务替换/签名错误/过期/迟到证据/唯一终态/append-only |
| `tests/test_s9_win32.py`（新） | 4 passed | 挂起创建+恢复前复核+resume、纳管失败 terminate、无隐式恢复 |
| 既有 `test_s9_gate` / `test_network_boundary` / `test_outbound` / `test_outbound_pipeline` | 48 passed | 无回归 |
| 既有 `test_worker_adapter` / `test_worker_isolation` | 20 passed | 无回归（含进程树回收、breakaway 拒绝） |
| 既有 `test_generation` / `test_generation_consistency` | 23 passed | 无回归 |
| 前端 vitest | 20 passed (20) | 3 文件 |
| 前端 build | 成功 | vue-tsc + vite |
| **后端全量回归（pytest -rs）** | **299 passed / 0 failed / 0 skipped** | 全部测试实际执行（Windows 环境，无 skip 条件触发） |

> 注：全量回归在本地 WorkBuddy 沙箱首次运行因安全删除守卫（`SAFE_DELETE_BULK_CONFIRM_REQUIRED`，
> 单次 `rmtree` 超过 50 文件触发 `SystemExit`）污染了测试清理阶段；以
> `CODEBUDDY_SAFE_DELETE_ENABLED=0` 禁用该守卫后得到干净结果 299 passed。该守卫是
> 本地沙箱环境的防护机制，CI（GitHub Actions windows-latest）不加载此 shim，不受影响。

## 5. 本地离线 PASS / 需 VM 实测 / BLOCKED

| 项目 | 状态 |
|---|---|
| CREATE_SUSPENDED 挂起创建 + 恢复前检查接口 | 本地离线 PASS（合成受限令牌） |
| job.assign 失败 terminate + wait | 本地离线 PASS（monkeypatch 强制失败） |
| 输入只读、输出独立可写断言 | 本地离线 PASS（既有 probe/run 测试覆盖） |
| 超时/取消/异常完整进程树回收 | 本地离线 PASS（既有 test_job_object_kills_worker_child_tree 等） |
| 身份不匹配/句柄异常/纳管失败确定性负向 | 本地离线 PASS（s9_win32 负向 + 既有负向） |
| GenerationRequest 绑定 attempt_id/request_digest | 本地离线 PASS |
| 授权摘要来自 prepared 行（不自算替代值） | 本地离线 PASS |
| 不可变请求字节与摘要比对 | 本地离线 PASS（worker 复核 + receipts actual_body_sha256） |
| 宿主授权收据 + 出口收据验签 | 本地离线 PASS |
| 持久化防重放 + 迟到证据追加 | 本地离线 PASS |
| 唯一终态 + append-only | 本地离线 PASS |
| 真实 LogonUserW / 独立 TokenUser | **需 VM 实测**（本地受限令牌无法伪造 TokenUser 不匹配） |
| VM 网络权限 / 固定出口 / Key 归属 | **需 VM 实测 + 决定 1 批准** |
| 生产凭据归属变更 | **BLOCKED**（未经人工批准，不改 Key 传递逻辑） |

## 6. 剩余风险与下一批部署前提

- **剩余风险**：
  1. 收据签名当前用 HMAC-SHA256（共享密钥）占位；生产若需非对称签名（Ed25519），
     须替换 `sign`/`verify` 内部实现，字段契约不变。
  2. 宿主签名密钥、Egress 私钥的托管与轮换机制未实现（依赖决定 5）。
  3. 撤销-签发时序判定（§6.2）的宿主侧落库尚未接线（本轮只固化契约语义与收据
     数据结构），需在 S9-4 门禁接线时实现。
- **下一批部署前提**：决定 1（Key 归属）人工批准 → 确定部署宿主 → S9-3 VM/网络部署。

## 7. 执行边界确认

未创建系统账户/VM、未改生产 ACL/防火墙、未读取真实 API Key、未调用百炼、未修改
ADLL-Knowledge、未 Git Commit/Push。`ADLL_REAL_AI_ENABLED=0`、`ADLL_WORKER_REAL_TRANSPORT=0` 保持不变。
