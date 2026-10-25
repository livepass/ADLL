# S9-3B 前置收口与部署放行准备

**日期**：2026-10-25　**基线**：`5a77cfb`（本地 HEAD = origin/main = 远端 main）
**性质**：本地离线收口；**未 Commit / 未 Push**。

## 1. 前提核对与已有修改审核

| 项 | 值 |
|---|---|
| 本地 HEAD | `5a77cfbe9954b071c020f80fc74acc0554bc9132` |
| `origin/main` / 远端 | `5a77cfbe9954b071c020f80fc74acc0554bc9132` |
| ahead / behind | `0 / 0` |
| 未推送提交 | 无 |

**本地已有未提交的 S9-3A 补缺实现（上轮产出，本轮审核后复用，未覆盖、未重写）**：

| 问题 | 实现位置 | 上轮状态 |
|---|---|---|
| A. 签发前校验真实授权记录 | `HostGateway.build_request_from_db`（prepared 行 → 授权存在 → `inactive_reason` → receiver/task-baseline） | 已实现 |
| B. Egress 独立验双凭证 | `EgressRelay._authenticate_caller` + `_verify_host_grant`，`LauncherAuth` 覆盖 attempt/digest/nonce/有效期 | 已实现 |
| C. nonce 作用域一次性 | `S9ReplayGuard` 的 `(consumer, nonce)` 部分唯一索引（迁移 `0013`） | 已实现 |

**本轮新增（唯一缺口）**：B 项要求的「**授权撤销与实际发送之间的竞态边界**」上轮只在契约
有文字、代码未落地。本轮补齐时序判定 + 证据留痕 + 3 个测试（见 §2）。

## 2. 本轮代码修改与测试证据

### 2.1 撤销竞态边界（契约 §6.2 / §6.2.1 落地）

**代码**（`app/services/s9_chain.py`）：

- `_revocation_race(auth, receipt)`：按「`revoked_at` vs `receipt.issued_at`」返回
  `revoked_before_issue` / `revoked_after_issue` / `None` / `authorization_missing` / `issued_at_invalid`。
- `HostGateway.settle`：
  - `revoked_before_issue` → **不升格** `confirmed_sent`，落 `possibly_sent` +
    `error_code=revoked_before_issue`，并追加 `revocation_race` 证据；
  - `revoked_after_issue` → 收据有效（`confirmed_sent`），追加 `revocation_after_issue` 证据；
  - 无撤销 → 不产生竞态证据。
- `_record_evidence`：证据写入按唯一索引幂等（重复 settle 不产生重复证据）。

**契约**（`contracts/s9-ipc-and-evidence.md` R6 新增 §6.2.1）：

- 明确**窗口上界 = 收据 `expires_at`**：窗口内的撤销不阻断已签发发送，属已知残余风险；
- 窗口外撤销由 `build_request_from_db` 活跃性校验拦住；
- 事后判定**归属宿主**（不依赖 Egress 自证）；
- 短 TTL 是缩小窗口的唯一手段，生产取值须与撤销传播延迟一并确定。

### 2.2 测试证据（新增 3 个确定性用例）

| 测试 | 断言 |
|---|---|
| `test_settle_rejects_confirmation_when_revoked_before_issue` | 撤销早于签发 → `verification.code == "revoked_before_issue"`；终态唯一且为 `possibly_sent`；`revocation_race` 证据 1 条 |
| `test_settle_records_when_revoked_after_issue` | 撤销晚于签发 → `confirmed_sent` + `revocation_after_issue` 证据 1 条 |
| `test_settle_no_revocation_evidence_when_authorization_active` | 无撤销 → 正常 confirmed 且**无**竞态证据 |

`test_s9_chain.py` 合计 **34 passed**（上轮 31 + 本轮 3）。

## 3. 生产隔离边界审查（如实标注）

| 维度 | Host（宿主） | Launcher | Egress | 是否可用于生产 |
|---|---|---|---|---|
| **运行身份** | 当前登录用户（服务账户待定） | **同进程**，无独立主体 | 子进程，**继承当前用户令牌** | **否（BLOCKED）**：无独立 TokenUser，S9-1 挂起门禁未接线到生产路径 |
| **IPC 认证** | 签发 `HostAuthorizationReceipt`（HMAC 覆盖 attempt/authz/receiver/digest/status/policy/有效期） | 验宿主收据 + 签发 `LauncherAuth` 给 Egress | 验 `LauncherAuth`（调用者）+ 独立验宿主收据（双凭证） | **凭证层 PASS / 传输层 BLOCKED**：Host→Launcher 为同进程方法调用，无跨进程 IPC；`ProcessTransport` 只覆盖 Launcher→Egress |
| **数据库访问权限** | 审批库（读写） | **合成链路复用宿主 session**（`DbReplayStore(db)`）；生产应为 VM 本地 replay 库 | **独立 replay 库**（`egress_replay_url`），子进程只建 replay 表；测试断言 `last_child_tables` 不含 `send_audit_records`/`outbound_authorizations` | **Egress PASS（结构性）/ Launcher BLOCKED**：Launcher 与宿主共库，未做到最小权限 |
| **签名密钥** | 宿主签名密钥（HMAC 占位） | 调用者密钥（`launcher_key`） | 出口签名密钥（`egress_signing_key`） | **BLOCKED**：全部由调用方注入，无托管、无 `key_id` 轮换、无非对称算法 |
| **API Key** | 不持有 | 不持有 | **当前也不持有**（Synthetic Provider 无凭据） | **BLOCKED**：真实 Key 归属未批准（决定 1），Egress 持 Key 的机制未实现 |
| **进程隔离** | — | 同进程 | 同机子进程（`spawn`），PID 可证 | **部分 PASS**：可证明「另一个进程」；不能证明「另一安全主体」 |
| **网络隔离** | 有（宿主网络） | 无隔离（同进程） | **无**：无 NSG/防火墙/固定出口 | **BLOCKED**：需 VM + 默认拒绝出站 |

**结论（不粉饰）**：S9-3A 是**凭证与证据层面的合成验证**，不是生产隔离实现。
同机子进程 + 共享审批库 + 调用方注入密钥，都不满足 S9-1/S9-3 的隔离要求。

## 4. S9-3B GO / NO-GO

| 判定对象 | 结论 | 依据 |
|---|---|---|
| 进入 S9-3B **部署准备**（选型、审批、脚本） | **GO** | 代码前置（A/B/C + 竞态）已闭合，测试 346 passed（见 §5） |
| 在**当前本机**执行真实百炼调用 | **NO-GO** | 无独立主体、无网络隔离、无 Key 归属批准 |
| 宣告 S9-3A 为「生产隔离已验收」 | **NO-GO** | 见 §3，不得用同机子进程冒充跨主体隔离 |
| 冻结 S9-3A 代码 | **建议 GO** | 除 §6 所列阻断外无新增功能需求；后续仅随 S9-3B 实测修缺陷 |

## 5. 部署操作审批清单（S9-3B）

按执行顺序，**每一项均需单独批准**：

| # | 操作 | 关键参数 | 批准人 |
|---|---|---|---|
| 1 | 选部署宿主 | A 物理 Windows 主机 / B 云 Windows VM | 待定 |
| 2 | 创建隔离虚拟网络 | 内部交换机或 VNet+子网；**默认拒绝出站** | 待定 |
| 3 | 创建 Worker VM | 2 vCPU / 4–8 GiB / 60 GiB；仅接隔离网络 | 待定 |
| 4 | 创建 Egress VM | 1 vCPU / 1 GiB / 30 GiB；仅接隔离网络 | 待定 |
| 5 | 创建专用本地账户 | 非管理员；口令入受保护凭据（仅 Launcher 可读） | 待定 |
| 6 | 部署 Launcher | `/program` 只读、授权输入只读、审计收据可写、独立 replay 库 | 待定 |
| 7 | 部署 Egress | 固定 `POST https://dashscope.aliyuncs.com/apps/anthropic/v1/messages`；TLS 校验、禁重定向、不重编码、不重试 | 待定 |
| 8 | **迁移 API Key** | 仅 Egress 可读；Worker/Launcher 不可读（**决定 1**） | 待定 |
| 9 | 生成签名密钥 | 算法（HMAC 首版 / Ed25519）、`key_id`、存放位置、轮换周期 | 待定 |
| 10 | 配置固定出口规则 | 仅放行 1 条出站；封堵 169.254.169.254 与云侧代理路径 | 待定 |
| 11 | 执行验收矩阵 | 身份 / 网络 / 证据 / 异常四类（见部署文档 §5.5） | 待定 |
| 12 | 回滚演练 | 关入口→终止进程树→断网→导出审计→撤资源 | 待定 |
| 13 | 首次真实请求 | 合成业务内容，单独审批 | 待定 |

费用口径：按 vCPU+内存小时价 + 磁盘 GB·月 + 出站流量逐项核价；**不写成已核实报价**，
需以供应商当期价格确认。建议按「按需 + 用后释放」计，避免预留承诺。

## 6. 距首次真实百炼 E2E 的剩余阻断

| # | 阻断项 | 类型 | 解除条件 |
|---|---|---|---|
| 1 | **决定 1：API Key 归属** | 审批 | 人工批准「出口持 Key、Worker 不接触」，并修订已批准凭据契约 |
| 2 | S9 网络边界未 `verified` | 环境 | VM 内 `collect_boundary_evidence` 返回 `verified` |
| 3 | 挂起创建未接线 | 代码 | `Sandbox.run` 改用 `suspended=True` + `pre_resume_check`（需独立 TokenUser） |
| 4 | Host→Launcher 无 IPC | 代码 | 跨进程传输 + 主体隔离（同机双进程或跨 VM） |
| 5 | Launcher 与宿主共库 | 代码 | Launcher 使用 VM 本地 replay 库 |
| 6 | 签名密钥未托管 | 代码/运维 | 密钥库 + `key_id` 轮换 + 非对称签名 |
| 7 | VM / 专用账户 / 隔离网络不存在 | 资源 | 按 §5 清单创建并验收 |
| 8 | 首次真实请求未审批 | 审批 | S9-5 单独批准（合成业务内容） |

## 7. 测试与验证结果

| 范围 | 结果 |
|---|---|
| 后端全量 `pytest -rs`（本地） | **346 passed / 0 failed / 0 skipped** |
| `test_s9_chain.py` | 34 passed（31 + 3 竞态） |
| `test_s9_receipts.py` | 19 passed |
| 前端 vitest | 20 passed (3 files) |
| 前端 `npm run build` | 成功 |
| Alembic 从零 0001→0013 | 通过 |
| Alembic 既有库 0012→0013（含数据） | 通过，历史行保留 |
| ruff（本轮改动文件） | All checks passed |

> CI 侧预期：341 passed / 3 skipped / 0 failed（本地多 3 个因本机存在被 gitignore 的
> `staging-account-ast-20261023` 与 `C:\ProgramData\ADLL-Account-Staging`，见上轮说明）。

## 8. 执行边界确认

未创建 VM/系统账户、未修改生产网络/ACL/防火墙、未读取或使用真实 API Key、
未调用百炼、未修改 ADLL-Knowledge、未 Commit/Push。
