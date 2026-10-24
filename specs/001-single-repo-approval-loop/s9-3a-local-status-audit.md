# S9-3A 本地状态核查报告（只读）

**日期**：2026-10-24　**性质**：只读核查，未修改代码、未 Commit/Push

## 1. 本地与远端对比

| 项 | 值 |
|---|---|
| 本地 HEAD | `9994dd5eeb78f638b2bd0822e52efecc33ee1ec7` |
| 本地分支 | `main` |
| origin | `https://github.com/livepass/ADLL.git` |
| `origin/main`（本地跟踪） | `9994dd5eeb78f638b2bd0822e52efecc33ee1ec7` |
| 远端 `refs/heads/main`（`git ls-remote`） | `9994dd5eeb78f638b2bd0822e52efecc33ee1ec7` |
| ahead / behind | `0 / 0` |

**结论**：本地与远端 main 指向同一提交。S9-3A 的实现**全部停留在工作区，未 Commit、未 Push**。
因此 GitHub main 仍是 `9994dd5`（S9-1/S9-2 收口版），不含 S9-3A。

## 2. 未提交内容清单

### 2.1 已修改（7 个）

| 文件 | 变更要点 |
|---|---|
| `backend/app/db.py` | 新增 `s9_replay_guard` append-only 触发器（2 条） |
| `backend/app/isolation/win32.py` | `pre_resume_check` 三参数缺失即 fail-closed |
| `backend/app/models/__init__.py` | 导出 `S9ReplayGuard` |
| `backend/app/models/outbound.py` | `SendReceiptEvidence` 增 `receipt_signature` 列 + 部分唯一索引 |
| `backend/app/services/receipts.py` | 严格 host 收据验证；新增 `verify_host_receipt_against_request`；证据并发幂等 |
| `backend/tests/test_s9_receipts.py` | 新增 4 个负向测试 |
| `backend/tests/test_s9_win32.py` | 新增 3 个 fail-closed 负向测试 |

### 2.2 新增（5 个代码/文档 + 1 个目录）

| 文件 | 说明 |
|---|---|
| `backend/app/services/s9_chain.py`（新） | 合成链路：`HostGateway` / `Launcher` / `EgressRelay` / `SyntheticProvider` / `ReplayStore` |
| `backend/app/models/s9_replay.py`（新） | `S9ReplayGuard` 模型 |
| `backend/alembic/versions/0011_receipt_evidence_dedupe.py`（新） | `receipt_signature` 列 + 唯一索引 |
| `backend/alembic/versions/0012_s9_replay_guard.py`（新） | 防重放表 + append-only 触发器 |
| `backend/tests/test_s9_chain.py`（新） | 13 个链路测试 |
| `specs/.../s9-3a-chain-and-s9-3b-deployment.md`（新） | 结果与部署准备文档 |
| `.specify/`（未跟踪） | 宪章与 Spec Kit 目录，历轮保持不纳入 |

## 3. S9-3A 逐项核对

| 核查项 | 实际状态 | 说明 |
|---|---|---|
| **真实 IPC 与独立进程** | **未实现** | `s9_chain.py` 无 `socket` / `multiprocessing` / `Pipe` / `subprocess`；Host/Launcher/Egress/Synthetic Provider 全部是**同一 Python 进程内的同步函数调用**。属于**结构性模拟**，不是跨进程 IPC。 |
| 绑定持久化 prepared 行 | **部分实现** | 构造阶段：`HostGateway.build_request` 只从传入 `prepared` 对象取 `attempt_id`/`authorization_id`/`receiver`/`request_digest`，并校验 `sha256(body) == request_digest`；但**不校验该对象是否为 DB 已持久化行**。落账阶段：`settle → outbound.finish_attempt` 会查 `phase="prepared"` 行，找不到即 `PermissionError`（此处强校验）。 |
| 绑定 request_digest | **已实现** | 三方核对：Host 构造时、Launcher `body_sha256`、Egress 转发前；任一不符即拒绝。 |
| 重放防护 | **已实现** | `S9ReplayGuard(consumer, attempt_id)` 唯一约束（迁移 0012）+ append-only 触发器；Launcher/Egress 各自独立登记，`DbReplayStore` 持久化，重启后仍生效。 |
| 超时 | **已实现** | `SyntheticProvider(fail_mode="timeout")` → 返回 `possibly_sent` 收据；无自动重试分支（测试断言 provider 只被调用 1 次）。 |
| **取消** | **未实现** | `s9_chain.py` 中无任何 `cancel` 逻辑；链路不支持运行中取消，也不记录取消后的发送事实。 |
| 重启后安全恢复 | **部分实现** | 已具备：replay 登记持久化（重启后拒绝重复）、`settle` 对已有终态只追加迟到证据（不写第二终态、不自动 verified）。**缺失**：链路层未提供「重启时扫描未决 attempt」的入口，目前依赖既有的 `generation_service.reconcile_orphan_attempts`（`prepared` → `possibly_sent`）。 |
| 合成验证 vs 真实 AI 调用 | **已明确区分** | 模块 docstring 明确「离线合成，不构成生产验收」；`SyntheticProvider` 仅进程内回显，无网络；测试含 `test_real_transport_remains_disabled_by_default`。 |
| 未配置真实 OS 隔离时零真实外发 | **已保证** | `app/services/s9_chain.py` 无任何 `urllib`/`requests`/`httpx`/`socket` 调用；`Settings.real_ai_enabled=False`、`worker_real_transport=False` 为 dataclass 默认值；真实发送仍需 Key + S9 网络边界 `verified` 双条件。 |

## 4. 测试结果（本轮只读复跑）

| 范围 | 结果 |
|---|---|
| `tests/test_s9_chain.py` + `tests/test_s9_receipts.py` | **32 passed**（13 + 19），本轮复跑确认 |
| 后端全量（上一轮收口后，代码未变） | 325 passed / 0 failed / 0 skipped |
| 前端（上一轮） | 20 passed + build 成功 |
| 迁移（上一轮验证） | 0001→0012 从零通过；0010→0012 既有库通过且保留历史行 |

## 5. S9-3A 完成度判定

**已完成（骨架与证据闭环）**
- Host→Launcher→Egress→Synthetic Provider→签名收据→Host 审计的**逻辑链路**贯通。
- 宿主授权收据 + 出口发送收据的双向签名与字段绑定。
- 三方 `request_digest` 核对、固定 Messages 路径、防重放、超时/断线不重发。
- 唯一终态 + 迟到证据 + append-only 触发器 + 并发唯一索引。

**未完成（与任务二的字面要求有差距）**
1. **真实 IPC 与独立进程**：当前是进程内调用，未实现跨进程传输（任务二写的是「Host → Launcher IPC」）。
2. **取消**：链路无取消路径。
3. **链路层重启恢复入口**：仅依赖既有 reconcile，链路自身未提供未决 attempt 的恢复函数。
4. **prepared 行持久化校验前移**：构造阶段接受 duck-typed 对象，建议改为接收 `(db, attempt_id)` 并在内部查行。

## 6. GO / NO-GO

| 判定 | 结论 | 理由 |
|---|---|---|
| S9-3A「逻辑链路」 | **GO（离线合成）** | 收据/绑定/防重放/超时/固定路径/审计落账全部有测试证据 |
| S9-3A「真实 IPC + 独立进程」 | **NO-GO** | 未实现，当前为进程内模拟 |
| S9-3A「取消语义」 | **NO-GO** | 未实现 |
| 真实百炼调用 | **NO-GO** | 6 项阻断未解（决定 1 未批准、网络边界未 verified、挂起创建未接线、VM 未部署、签名密钥未托管、首次请求未审批） |
| GitHub 同步 | **待人工批准** | 本轮按要求未 Commit/Push |

## 7. 下一步建议（待批准后执行，不扩展架构）

在既有 `s9_chain.py` 内补齐（不新增架构层）：

1. **进程隔离传输**：在现有 `Launcher.dispatch` / `EgressRelay.forward` 之间引入可替换的 `Transport` 接口——默认进程内直调（现有行为，测试用），另提供基于 `multiprocessing.Pipe` 的**同机双进程**实现，消息为现有 `AuthorizationRequest`/`SendReceipt` 的规范化 JSON + 签名。仍不涉及网络、不涉及 VM。
2. **取消**：`ChainOutcome` 增加 `cancelled` 相位；Launcher 在转发前检查取消令牌 → `not_sent`；转发后取消 → `possibly_sent`（不撤回）。
3. **重启恢复入口**：`s9_chain.reconcile_pending(db)` 复用 `reconcile_orphan_attempts` 并把结果写入链路证据。
4. **prepared 绑定前移**：`build_request(db, attempt_id, body, model)` 内部查行，拒绝未持久化 attempt。

以上均为离线可验证，不改变真实发送默认关闭，不触及 Key/VM/网络。

## 8. 边界确认

本轮仅只读检查（`git status`/`rev-parse`/`ls-remote`/源码检索）与一次本地测试复跑；
未修改、未覆盖任何代码，未 Commit/Push，未调用百炼、未读取 Key、未创建 VM、未修改系统网络/ACL。
