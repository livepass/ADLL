# S9-3A 最终交付与审核（供人工确认）

**日期**：2026-10-24　**基线**：`9994dd5`
**性质**：本轮补齐 S9-3A 缺失项并完成验证；**未 Commit / 未 Push**。

## 1. 本地与 GitHub SHA 对照

| 项 | SHA / 值 |
|---|---|
| 本地 HEAD | `9994dd5eeb78f638b2bd0822e52efecc33ee1ec7` |
| 本地分支 | `main` |
| `origin` | `https://github.com/livepass/ADLL.git` |
| `origin/main`（本地跟踪） | `9994dd5eeb78f638b2bd0822e52efecc33ee1ec7` |
| 远端 `refs/heads/main`（`git ls-remote` 实测） | `9994dd5eeb78f638b2bd0822e52efecc33ee1ec7` |
| ahead / behind | `0 / 0` |
| 未推送提交 | **无**（所有改动仍为工作区未提交状态） |

**结论**：GitHub main 与本地 HEAD 完全一致；S9-3A 全部改动尚未进入版本历史，
因此远端看不到 S9-3A。这是「未提交」，不是「同步失败」。

## 2. S9-3A 已实现功能

| 能力 | 实现位置 | 证据 |
|---|---|---|
| Host → Launcher → Egress → Synthetic Provider → 签名收据 → Host 审计 | `app/services/s9_chain.py` | `test_synthetic_chain_end_to_end_confirmed` |
| **独立进程 IPC**（`multiprocessing.Pipe` + `spawn` 子进程） | `ProcessTransport` / `_egress_process_main` | `test_process_transport_end_to_end`（断言子进程 PID ≠ 父进程） |
| 子进程内独立 DB session 与 replay store | `_egress_process_main` | 同上 + `test_process_transport_replay_rejected` |
| 授权摘要绑定（prepared 行 → request_digest → 实际字节） | `build_request_from_db` / `verify_host_receipt_against_request` | `test_build_request_from_db_*`、`test_launcher_rejects_tampered_body` |
| Launcher 不读审批 DB | 仅持有 `ReplayStore`，收据与实际请求字段比对 | `test_launcher_rejects_cross_task_replacement` |
| 持久化防重放（Launcher / Egress 各自） | `S9ReplayGuard (consumer, attempt_id)` 唯一 + append-only 触发器 | `test_launcher_replay_rejected`、`test_egress_replay_rejected`、`test_process_transport_replay_rejected` |
| 取消语义 | `Launcher.dispatch(cancel_check=...)` | `test_cancel_before_send_is_not_sent`（provider 调用 0 次）、`test_cancel_after_send_marks_cancelled_but_keeps_sent_fact` |
| 超时 / 断线不重发 | `SyntheticProvider(fail_mode=...)` → `possibly_sent` | `test_timeout_reports_possibly_sent_and_no_auto_retry`（provider 只调用 1 次） |
| 重启后安全恢复 | `s9_chain.reconcile_pending(db)` | `test_reconcile_pending_marks_orphan_possibly_sent` |
| 收据完整对应 | `verify_send_receipt` 全字段校验 | `test_bad_egress_signature_does_not_confirm` |
| 固定 Messages 路径、无通用代理 | `_is_fixed_messages_endpoint` | `test_egress_rejects_non_fixed_endpoint`（3 种非法端点） |
| 合成 vs 真实明确区分 | docstring + 无网络调用 + 默认关闭断言 | `test_real_transport_remains_disabled_by_default` |

## 3. S9-3A 仍缺失 / 未达生产级的部分

| 项 | 状态 | 说明 |
|---|---|---|
| 跨 **VM** IPC | **未实现（BLOCKED）** | 当前 IPC 是**同机双进程**（`multiprocessing`），不是 Host↔Worker VM 的跨机传输；跨机需证书互认与专用网段，属 S9-3B 部署范围 |
| Launcher 在独立 OS 主体下运行 | **未实现（BLOCKED）** | 子进程仍是当前用户令牌；独立 TokenUser 需 `LogonUserW` + 专用账户（VM 环境） |
| 真实签名算法 | **占位** | 当前 HMAC-SHA256（共享密钥，由调用方注入）；生产建议 Ed25519 + `key_id` 轮换 |
| 真实 Egress 转发 | **未实现（BLOCKED）** | `SyntheticProvider` 不联网；真实转发需固定出口 + Key 归属批准 |
| 链路写入 `GenerationExecution` 终态 | 未接线 | `settle` 只写 `SendAuditRecord` 终态；与生成编排的接线留待 S9-4 |
| 取消的可中断性 | 有限 | 转发前可阻断；转发中（进程内同步）无法中断，只能事后标记 |
| `ProcessTransport` 超时后的子进程回收 | 已实现但未测 | 代码 `terminate + join`；因难以稳定复现未加自动化用例，列入 VM 实测 |

## 4. 完整测试结果

| 范围 | 结果 |
|---|---|
| 后端全量 `pytest -rs` | **332 passed / 0 failed / 0 skipped**（1043s） |
| `test_s9_chain.py` | **20 passed**（原 13 + 新增 7：IPC 正向/跨进程重放/取消前后/重启恢复/DB 绑定×2） |
| `test_s9_receipts.py` | 19 passed |
| `test_s9_win32.py` | 8 passed |
| 前端 vitest | 20 passed (3 files) |
| 前端 `npm run build` | 成功 |
| Alembic 从零 0001→0012 | 成功；`s9_replay_guard` 表、`receipt_signature` 列、4 个触发器齐备 |
| Alembic 既有库 0010→0012 | 成功；历史证据行保留（`receipt_signature=NULL`） |
| ruff（本轮新增/改动文件） | All checks passed |

## 5. GO / NO-GO

| 判定对象 | 结论 | 依据 |
|---|---|---|
| S9-3A 合成链路（含同机独立进程 IPC） | **GO** | 332 passed；IPC 有 PID 跨进程硬证据；绑定/防重放/超时/取消/重启全部有负向测试 |
| S9-3A 作为生产安全边界 | **NO-GO** | 同机双进程≠跨 VM；无独立 TokenUser；签名为 HMAC 占位；Provider 为合成 |
| 真实百炼调用 | **NO-GO** | 见 §6 六项阻断 |
| GitHub 同步 | **待人工批准** | 本轮禁止 Commit/Push |

## 6. 进入 S9-3B 前必须人工批准的事项

1. **决定 1（凭据归属）**：是否批准「API Key 仅由固定出口持有，Worker 不接触 Key」——
   这是对已批准 `contracts/agent-adapter.md` §1 的实质变更，**未批准不得实施**。
2. **部署宿主与形态**：物理主机 vs 云 Windows VM（S9-3B 文档给出 A/B 对比与核价口径）。
3. **签名算法与密钥托管**：HMAC-SHA256 占位是否接受首版，或改用 Ed25519；
   `key_id` 轮换策略与密钥存储位置（DPAPI / 云密钥库）。
4. **VM 规格与成本**：Worker 2 vCPU/4–8 GiB、Egress 1 vCPU/1 GiB 是否接受；
   按需计费预算上限。
5. **网络方案**：隔离网段/NSG 默认拒绝的具体配置；是否额外封堵云元数据端点
   （169.254.169.254）与云侧代理路径。
6. **专用账户命名与口令托管**：账户名、口令存储位置（仅 Launcher 可读）。
7. **首次真实请求审批**：S9-5 要求首次真实百炼调用单独人工审批（合成业务内容）。
8. **是否接线 `settle` 到 `GenerationExecution` 终态**（S9-4 范围）——若希望 S9-3B 一并验证，
   需明确授权跨越 S9-4 边界。

## 7. Commit/Push 差异（供人工确认，未执行）

### 7.1 已跟踪文件修改（7 个，+359 / −19）

| 文件 | 变更 |
|---|---|
| `backend/app/db.py` | +5：`s9_replay_guard` append-only 触发器 2 条 |
| `backend/app/isolation/win32.py` | +31/−：`pre_resume_check` 缺失参数 fail-closed |
| `backend/app/models/__init__.py` | +2：导出 `S9ReplayGuard` |
| `backend/app/models/outbound.py` | +14：`receipt_signature` 列 + 部分唯一索引 |
| `backend/app/services/receipts.py` | +128/−：严格 host 验证、无库验证、`SendReceipt.from_dict`、幂等 |
| `backend/tests/test_s9_receipts.py` | +126：4 个新负向 |
| `backend/tests/test_s9_win32.py` | +72：3 个 fail-closed 负向 |

### 7.2 新增文件（5 个代码/迁移 + 3 份文档）

| 文件 | 行数 | 用途 |
|---|---|---|
| `backend/app/services/s9_chain.py` | 636 | 合成链路（含 IPC/取消/恢复） |
| `backend/app/models/s9_replay.py` | 27 | 防重放登记模型 |
| `backend/tests/test_s9_chain.py` | 556 | 20 个链路测试 |
| `backend/alembic/versions/0011_receipt_evidence_dedupe.py` | 39 | 收据证据去重列/索引 |
| `backend/alembic/versions/0012_s9_replay_guard.py` | 52 | 防重放表 + 触发器 |
| `specs/.../s9-3a-chain-and-s9-3b-deployment.md` | — | 链路结果与部署准备 |
| `specs/.../s9-3a-local-status-audit.md` | — | 上一轮只读核查记录 |
| `specs/.../s9-3a-final-delivery.md` | — | 本文档 |

### 7.3 不纳入提交

`.specify/`（宪章与 Spec Kit 目录，历轮保持未跟踪）。

### 7.4 建议提交信息（待批准后执行）

```text
feat: S9-3A synthetic chain with process IPC, cancel and replay guard
```

## 8. 边界确认

本轮未 Commit/Push、未读取真实 Key、未调用百炼、未创建 VM 或系统账户、
未修改系统 ACL/防火墙、未改 ADLL-Knowledge、未变更已批准凭据契约。
