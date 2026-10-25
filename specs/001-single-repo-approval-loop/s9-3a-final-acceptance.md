# S9-3A 最终验收补缺与 S9-3B 部署审批材料

**日期**：2026-10-25　**基线**：`5a77cfb`
**性质**：本地离线补缺与验证；**未 Commit / 未 Push**。

## 1. CI 核实与本地差异

### 1.1 CI run 40101251561（`5a77cfb`）

| job | 结论 | 后端计数 |
|---|---|---|
| backend | success | **329 passed / 3 skipped / 0 failed** |
| frontend | success | 20 passed + build |

### 1.2 三个 skipped 的确切原因（已在本地逐条定位）

均来自 `backend/tests/test_account_script_ast_guard.py`（PowerShell 账户脚本的**静态**
守卫：只解析脚本，不执行、不建账户、不碰 ACL），与 S9 隔离无关：

| 测试 | skip 条件 | 原因 |
|---|---|---|
| `test_candidate_staging_matches_its_manifest` | `backend/staging-account-ast-20261023/manifest.json` 不存在 | 该目录被 `.gitignore:27` 忽略（`backend/staging-*/`），CI 干净检出没有它 |
| `test_installer_pins_the_candidate_bytes` | 同上 | 同上 |
| `test_installer_pins_match_the_installed_staging_state` | `C:\ProgramData\ADLL-Account-Staging\manifest.json` 不存在 | 该本机安装状态不在版本库内，CI 无此路径 |

**本地为何不 skip**：本机同时存在 `backend/staging-account-ast-20261023/`（未跟踪）与
`C:\ProgramData\ADLL-Account-Staging\manifest.json`，故这 3 个测试实际执行并通过。

### 1.3 三类「隔离」必须区分

| 类型 | 含义 | 本轮状态 |
|---|---|---|
| 本地测试 | 本机 Windows 真实受限令牌 + Job Object | 通过（这是 OS 级机制，但主体仍是当前登录用户） |
| CI 测试 | GitHub `windows-latest` 干净检出 | 通过；3 skipped 为上述本地 staging 依赖，非功能缺失 |
| **真正的 OS 隔离验收** | 独立 TokenUser + 专用账户 + 跨 VM 网络边界 | **未做（BLOCKED）**，需 VM 与专用账户 |

## 2. 四个问题的修复

### A. 宿主签发授权收据前必须确认授权仍有效

**最小修改**：`HostGateway.build_request_from_db` 由「只查 prepared 行」扩展为三重校验：
prepared 行存在 → `OutboundAuthorization` 存在 → `outbound.inactive_reason()` 为 None
（复用既有撤销/未批准/过期判定）+ receiver 一致 + task/baseline 可核验。

**错误码**：`authorization_missing` / `authorization_revoked` / `authorization_not_approved` /
`authorization_expired` / `authorization_receiver_mismatch` / `authorization_unverifiable`

**确定性负向测试**：`test_build_request_rejects_{revoked,expired,pending}_authorization`、
`test_build_request_rejects_receiver_mismatch_authorization`

**验收标准**：撤销/过期/未批准/不匹配四种状态均在签发前抛 `ChainDenied`，无任何收据产生。

### B. Egress 不得只凭 receiver/digest/policy 放行

**最小修改**：新增 `LauncherAuth`（`receipts.py`）与 `EgressRelay` 双凭证校验：

1. **调用者认证**：`launcher_auth` 用 `launcher_keys[key_id]` 验签，覆盖
   `attempt_id + request_digest + nonce + issued_at + expires_at`；
   未配置密钥 → `egress_caller_auth_not_configured`（fail-closed）。
2. **宿主授权凭证**：Egress 用 `host_public_key` 独立验 `host_receipt`
   （不依赖 Launcher 的结论），要求 `approved`、未过期、绑定一致。

**错误码**：`launcher_auth_missing` / `launcher_key_unknown` / `launcher_auth_signature_invalid` /
`launcher_auth_expired` / `egress_caller_auth_not_configured` /
`egress_host_key_not_configured` / `egress_host_receipt_missing` /
`egress_host_receipt_*`

**确定性负向测试**：`test_egress_rejects_missing_caller_auth`、
`test_egress_rejects_unknown_caller_key_id`、`test_egress_rejects_bad_caller_signature`、
`test_egress_fail_closed_without_caller_keys`、`test_egress_rejects_forged_host_receipt`、
`test_egress_fail_closed_without_host_key`

**验收标准**：缺少任一凭证即拒绝；错误密钥/未知 key_id 即拒绝；未配置即拒绝（不降级）。

### C. nonce 防重放（不同 attempt 复用同一 nonce）

**最小修改**：`S9ReplayGuard` 增加 `(consumer, nonce)` **部分唯一索引**
（`nonce IS NOT NULL`），迁移 `0013`；`DbReplayStore.register` 已捕获 `IntegrityError` → 返回 False。

**确定性负向测试**：`test_nonce_reuse_across_attempts_rejected`（attempt A 用 nonce N 成功，
attempt B 复用 N → `launcher_replayed_attempt`）

**验收标准**：同一消费方内 nonce 只能用一次，跨 attempt 复用同样被数据库拒绝；
历史 NULL nonce 行不受影响。

### D. 进程与数据库权限边界（如实标注）

| 项 | 实际状态 | 判定 |
|---|---|---|
| Egress 在独立子进程执行 | `multiprocessing.Pipe` + spawn；PID ≠ 父进程（测试断言） | **PASS（同机双进程）** |
| Egress 不访问审批数据库 | 子进程只连**独立** `egress_replay_url`，只建 replay 表；`last_child_tables` 断言不含 `send_audit_records` / `outbound_authorizations` | **PASS（结构性隔离）** |
| Host → Launcher 是 IPC | **否**：同一进程内直接方法调用 | **BLOCKED** |
| OS 级主体隔离（Egress 用独立 TokenUser/ACL） | **否**：子进程继承当前用户令牌 | **BLOCKED** |

**结论**：不得把「同机双进程 + 独立 replay 库」表述为「跨进程安全边界已验收」。
真正的 Host↔Launcher↔Egress 三进程隔离、独立 TokenUser、跨 VM 传输，均需 S9-3B 环境实测。

## 3. S9-3A 最终 PASS / BLOCKED 矩阵

| # | 验收项 | 判定 | 证据 |
|---|---|---|---|
| 1 | 合成 Host → Launcher → Egress → Synthetic Provider → 收据 → Host 审计正确 | **PASS** | `test_synthetic_chain_end_to_end_confirmed` |
| 2 | 发送授权、实际请求字节、收据三者完全匹配 | **PASS** | 三方 `request_digest` 核对 + `actual_body_sha256` 比对；`test_launcher_rejects_tampered_body` |
| 3 | 撤销授权被拒绝 | **PASS** | `test_build_request_rejects_revoked_authorization` |
| 4 | 重放被拒绝（同 attempt / 同 nonce） | **PASS** | `test_launcher_replay_rejected`、`test_egress_replay_rejected`、`test_nonce_reuse_across_attempts_rejected` |
| 5 | 身份不符被拒绝 | **PASS（离线）** / **BLOCKED（OS 主体）** | 凭证身份：`test_egress_rejects_bad_caller_signature`；OS 主体：未实现 |
| 6 | 签名错误被拒绝 | **PASS** | `test_bad_egress_signature_does_not_confirm`、`test_egress_rejects_forged_host_receipt` |
| 7 | 超时不自动重发 | **PASS** | `test_timeout_reports_possibly_sent_and_no_auto_retry`（provider 仅调用 1 次） |
| 8 | 取消不误判 | **PASS** | `test_cancel_before_send_is_not_sent`、`test_cancel_after_send_...` |
| 9 | 断线不自动重发 | **PASS** | `test_connection_reset_reports_possibly_sent` |
| 10 | 重启不重复发送 | **PASS** | `test_reconcile_pending_marks_orphan_possibly_sent`、`test_restart_duplicate_receipt_appends_evidence_only` |
| 11 | 合成结果不冒充真实 AI | **PASS** | docstring + 无网络调用 + `test_real_transport_remains_disabled_by_default` |
| 12 | 真实发送默认关闭 | **PASS** | `real_ai_enabled=False`、`worker_real_transport=False` |
| 13 | Egress 独立进程执行 | **PASS（同机）** | `test_process_transport_end_to_end`（PID 断言） |
| 14 | Egress 不读审批库 | **PASS（结构性）** | `last_child_tables` 断言 |
| 15 | Host → Launcher IPC | **BLOCKED** | 同进程调用 |
| 16 | 独立 TokenUser / OS ACL | **BLOCKED** | 未实现，需 VM |
| 17 | 跨 VM 传输 | **BLOCKED** | 未实现 |

**S9-3A 结论**：合成链路与凭证/防重放/异常语义 **PASS**；进程与 OS 级隔离 **部分 BLOCKED**。
不冻结前需人工确认：是否接受「同机双进程 + 凭证级隔离」作为 V1.1 首版边界。

## 4. 代码与测试修改清单（本轮，未提交）

| 文件 | 变更 |
|---|---|
| `app/services/s9_chain.py` | A：`build_request_from_db` 三重授权校验；B：`EgressRelay` 双凭证（`_authenticate_caller`/`_verify_host_grant`）+ `Launcher.launcher_key` 签发；D：`ProcessTransport` 改用独立 `egress_replay_url` + `last_child_tables` 证据 |
| `app/services/receipts.py` | 新增 `LauncherAuth`、`issue_launcher_auth`、`verify_launcher_auth`、`LAUNCHER_AUTH_SIGNED_FIELDS` |
| `app/models/s9_replay.py` | C：`(consumer, nonce)` 部分唯一索引 |
| `alembic/versions/0013_s9_replay_nonce_unique.py`（新） | C：迁移 |
| `tests/test_s9_chain.py` | 新增 11 个（A×4、B×6、C×1）+ 适配认证/独立 replay 库 |

### 4.1 本轮测试结果

| 范围 | 结果 |
|---|---|
| 后端全量 `pytest -rs`（本地） | **343 passed / 0 failed / 0 skipped**（1416s） |
| `test_s9_chain.py` | **31 passed**（原 20 + 新增 11） |
| `test_s9_receipts.py` | 19 passed |
| 前端 vitest | 20 passed (3 files) |
| 前端 `npm run build` | 成功 |
| Alembic 从零 0001→0013 | 通过；`ux_s9_replay_consumer_nonce` 索引存在 |
| Alembic 既有库 0012→0013（含数据） | 通过；历史 `(attempt_id='legacy-a', nonce='n1')` 行保留 |
| ruff（本轮改动文件） | All checks passed |

> 本地 0 skipped 与 CI 3 skipped 的差异，原因见 §1.2（本地存在被 gitignore 的 staging 目录）。
> 预测 CI 计数：**340 passed / 3 skipped / 0 failed**（旧 329 + 11 新增）。

## 5. S9-3B 可执行部署审批清单

| # | 决策项 | 选项 | 需人工批准 |
|---|---|---|---|
| 1 | 部署宿主 | A 独立 Windows 物理主机 / B 云 Windows VM | 是 |
| 2 | 资源规格 | Worker 2 vCPU/4–8 GiB；Egress 1 vCPU/1 GiB；磁盘见部署文档 | 是 |
| 3 | 系统许可 | 自带许可（物理）/ 云镜像含许可（VM） | 是 |
| 4 | 网络拓扑 | 隔离虚拟交换机或 VNet + 子网；NSG 默认拒绝出站 | 是 |
| 5 | 固定出口 | 仅 `POST https://dashscope.aliyuncs.com/apps/anthropic/v1/messages`；禁重定向/代理 | 是 |
| 6 | 专用账户 | 非管理员本地账户名 + 口令托管位置（仅 Launcher 可读） | 是 |
| 7 | 受保护凭据 | DPAPI / 云密钥库；Worker 不持 Key | 是（决定 1） |
| 8 | 签名密钥 | HMAC 首版 or Ed25519；`key_id` 轮换周期与旧密钥失效策略 | 是 |
| 9 | 验收矩阵 | 身份/网络/证据/异常四类（见部署文档 §5.5） | 是 |
| 10 | 回滚与释放 | 关入口→终止进程树→断网→导出审计→撤资源 | 是 |
| 11 | 首次真实请求 | 单独审批，合成业务内容 | 是 |

成本口径：按 vCPU+内存小时价 + 磁盘 GB·月 + 出站流量逐项核价；
**不将估算写成已核实报价**，需按供应商当期价格确认。

## 6. 首次真实百炼调用前的剩余阻断条件

1. **决定 1 未批准**：API Key 归属（出口持有、Worker 不接触）——是对已批准凭据契约的实质变更。
2. **S9 网络边界未 `verified`**：`network_boundary.evaluate` 当前必然 `not_configured`。
3. **挂起创建未接线**：生产 `Sandbox.run` 仍 `suspended=False`，S9-1 门禁未生效于真实路径。
4. **VM / 专用账户 / 隔离网络不存在**。
5. **签名密钥未托管**：当前 HMAC 由调用方注入，无 `key_id` 轮换机制。
6. **Host→Launcher IPC 与跨 VM 传输未实现**。
7. **首次真实请求未人工审批**。

## 7. 边界确认

本轮未创建 VM/系统账户、未修改生产 ACL/防火墙/网络、未读取或迁移真实 Key、
未开启真实百炼请求、未修改 ADLL-Knowledge、未 Commit/Push。
