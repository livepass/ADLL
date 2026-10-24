# S9-3A 合成链路结果与 S9-3B 部署准备

**日期**：2026-10-24　**基线**：`9994dd5`
**范围**：合成链路联调（离线）+ 部署选型比较。未创建 VM/账户、未改网络规则、未读 Key、未调用百炼。

## 1. 任务一：S9-1/S9-2 最终核对

### 1.1 CI 结果（run 40079679155，基线 `9994dd5`）

| job | 平台 | 结论 | 关键步骤 |
|---|---|---|---|
| backend | windows-latest | success | `Migrate from zero` / `Compile check` / `Test` 全 success |
| frontend | ubuntu-latest | success | `npm test` / `npm run build` 全 success |

- CI 的 passed 数量不对外暴露（job 日志需登录）；本地同基线全量为 **306 passed / 0 failed / 0 skipped**（上一轮收口后）。
- **本轮修复后本地全量（最终代码）：325 passed / 0 failed / 0 skipped**（120 个测试文件批次，1928s）。

### 1.3 本次测试证据汇总

| 测试 | 数量 | 说明 |
|---|---|---|
| 后端全量 `pytest -rs` | **325 passed / 0 failed / 0 skipped** | 含本轮新增 19 个 |
| `test_s9_chain.py`（新） | 13 passed | 链路正向 1 + 负向 12 |
| `test_s9_receipts.py` | 19 passed | 新增 4（approved/future issued_at/policy 白名单/并发唯一索引） |
| `test_s9_win32.py` | 8 passed | 新增 3（缺失参数 fail-closed/错误程序摘要/未检查 resume） |
| 前端 vitest | 20 passed (20) | 3 文件 |
| 前端 `npm run build` | 成功 | vue-tsc + vite |
| Alembic 从零 | 0001→0012 成功 | `s9_replay_guard` + `receipt_signature` + 唯一索引 + 触发器齐备 |
| Alembic 既有库 | 0010→0012 成功 | 历史证据行保留，`receipt_signature` 为 NULL（部分唯一索引允许） |

### 1.2 四个必查点的实际结论与修复

| 检查点 | 修复前 | 结论 | 修复 |
|---|---|---|---|
| `pre_resume_check` 缺少批准 SID / restricting SID / 可信程序身份 | **不 fail-closed**：三参数为 `None` 时直接跳过核对（`if x is not None and ...`） | **阻断项，已修** | 三参数缺失分别产生 `expected_token_user_sid_missing` / `expected_restricting_sid_missing` / `expected_program_sha256_missing`，`ok=False`；新增 3 个确定性负向测试 |
| `verify_host_receipt` 严格验证 approved / issued_at / expires_at / policy_version | **不严格**：未校验 `authorization_status`、未校验 `issued_at`、无 policy 白名单 | **阻断项，已修** | 增加 `authorization_not_approved`、`issued_at_invalid`（未来时间戳拒绝）、`policy_version_not_accepted`；新增 3 个负向测试 |
| 生产 `Sandbox.run` 是否使用挂起创建 | **未使用**（`suspended=False`） | **不得报告为生产已验收** | 在 `sandbox.run` 顶部写明接线状态；本文档与验收表均标注「挂起创建未接线」 |
| 重复收据并发提交是否产生重复可信证据 | **可能**：应用层「先查后插」并发下双双通过 | **阻断项，已修** | 新增 `receipt_signature` 列 + 部分唯一索引 `ux_receipt_evidence_signature`（迁移 0011）；`append_receipt_evidence` 写该列；`record_late_receipt` 捕获 `IntegrityError` 视为已记录 |

## 2. 任务二：S9-3A 合成链路

### 2.1 链路构成（`backend/app/services/s9_chain.py`）

```text
HostGateway.build_request_from_db(db, attempt_id)   # 必须命中 DB 已持久化 prepared 行
  → AuthorizationRequest{attempt_id, authorization_id, receiver,
                         request_digest, body, model, timeout_ms, nonce,
                         policy_version, host_receipt}
  → Launcher.dispatch(request, transport, cancel_check)  # 无审批 DB，仅验签 + 字段比对
  → ChainTransport
      ├─ InProcessTransport（默认，进程内直调）
      └─ ProcessTransport（multiprocessing.Pipe → 独立子进程 Egress）
  → EgressRelay.forward                 # 固定 Messages 路径，无通用代理
  → SyntheticProvider.send(body)        # 进程内确定性，不联网（仅合成）
  → SendReceipt（签名覆盖全字段，跨进程回传）
  → HostGateway.settle(db, outcome)     # 验签 → 唯一终态 / 迟到证据
```

> **合成 vs 生产**：`SyntheticProvider` 是进程内确定性实现，仅用于验证链路结构与
> 证据传递。真实传输路径（Worker VM + 固定出口 + 百炼）仍默认关闭且未接线。

### 2.2 与契约逐项对应

| 契约要求 | 实现 |
|---|---|
| Host 从真实持久化 prepared 构造授权请求 | `build_request_from_db(db, attempt_id)` 查 `phase='prepared'` 行，缺失即 `prepared_row_missing`；`build_request` 核对 `sha256(body) == request_digest` |
| Launcher 不读审批 DB，验证可信宿主授权凭证 | `verify_host_receipt_against_request`：无 `SendAuditRecord` 入参，改与实际请求字段逐一比对；Launcher 只持有自己的 `ReplayStore` |
| **Host → Launcher → Egress 独立进程 IPC** | `ProcessTransport`：`multiprocessing.Pipe` + `spawn` 子进程；子进程内重建 `EgressRelay`（独立 DB session / replay）；回传子进程 PID 作为跨进程证据（测试断言 PID ≠ 父进程） |
| 取消语义 | `Launcher.dispatch(cancel_check=...)`：转发前取消 → `not_sent`（provider 未被调用）；转发后取消 → 保留已发送事实并标 `cancelled_after_send` |
| 重启后安全恢复 | `s9_chain.reconcile_pending(db)` 复用 `reconcile_orphan_attempts`：孤儿 prepared → `possibly_sent`，不补 confirmed/not_sent |
| 请求体不可变字节，三方核对 request_digest | Host（build 时）→ Launcher（`body_sha256`）→ Egress（转发前重算）三处核对 |
| 持久化单次防重放 | `S9ReplayGuard` 表 `(consumer, attempt_id)` 唯一约束；Launcher/Egress 各自独立登记，重启后仍生效；表本身 append-only（触发器禁止 UPDATE/DELETE，否则删登记即可绕过） |
| 跨任务替换必须拒绝 | `verify_host_receipt_against_request` 比对 attempt/authorization/receiver；测试覆盖篡改 authorization_id |
| Egress 仅接受固定 Messages 路径 | `_is_fixed_messages_endpoint` 严格要求 `https://dashscope.aliyuncs.com` + `/apps/anthropic/v1/messages`，其他一律 `egress_endpoint_not_allowed` |
| 结构化收据验证签名/实际字节/尝试/策略/终态 | `verify_send_receipt`：签名、attempt/authorization/receiver、`actual_body_sha256 == request_digest`、`issued_at`、`expires_at`、`policy_version`、`issuer` |
| 断线/超时/重启/重复不得自动重发 | 出口仅在 provider 调用前有一个发送点；`timeout`/`connection_reset` 返回 `possibly_sent` 收据；无任何重试分支；测试用计数 Provider 断言只调用 1 次 |
| 签名/密钥/生产权限不得由 Mock 冒充 | 签名使用 HMAC-SHA256（密钥由调用方注入，不硬编码、不入库）；文档明确合成链路不构成生产验收 |

### 2.3 合成链路测试（`tests/test_s9_chain.py`，20 passed）

正向：全链路 `confirmed_sent` 贯通，收据字段与 prepared 完全对应；**独立子进程 IPC** 贯通（PID 断言跨进程）。
负向：无宿主收据、跨任务替换、字节篡改、Launcher 重放、Egress 重放、非固定端点（3 种）、
超时（断言只调用 1 次）、连接重置、重启后重复收据只追加证据、错误 egress 签名不 confirm、
prepared 摘要不符、prepared 行缺失、跨进程重放、取消（前/后）、重启恢复、真实发送默认关闭。

## 3. 任务三：S9-3B 部署实施准备（不创建资源）

### 3.1 两种宿主方案对比

| 维度 | 方案 A：独立 Windows 物理主机 | 方案 B：云端 Windows VM |
|---|---|---|
| 最小规格 | 4 vCPU / 8 GiB RAM / 80 GiB SSD（宿主）+ 同一物理机的隔离 Worker 环境 | Worker VM 2 vCPU / 4 GiB / 60 GiB；Egress VM 1 vCPU / 1 GiB / 30 GiB |
| 系统许可 | Windows 11 Pro/Enterprise 或 Server 2022（需 Hyper-V 或等效隔离）；已有许可可复用 | 云镜像自带许可（Windows Server 按小时计费含许可） |
| 虚拟网络 | Hyper-V 内部交换机（Internal）+ 静态隔离网段，无 NAT/桥接 | 专用 VNet + 独立子网 + NSG 默认拒绝出站 |
| 固定出口 | 同机独立 VM 作应用层出口，仅放行固定 Messages POST | 独立 Egress VM 或 NAT 网关 + 应用层出口 |
| 专用账户 | 本机专用非管理员账户（需本机/域策略支持 `LogonUserW` BATCH） | VM 内专用本地账户（云侧不代管，需自定义脚本创建） |
| 受保护凭据 | DPAPI/凭据管理器，仅 Launcher 可读 | VM 密钥库（如 Azure Key Vault）或 DPAPI；仍须仅出口可读 |
| 成本口径 | 一次性硬件/电费 + Windows 许可；无小时费 | 按小时计费（vCPU+内存+磁盘+出站流量），可停机释放 |
| 网络可控性 | 强（物理隔离，无云平台旁路） | 中（云平台元数据/代理路径需额外封堵） |
| 回滚 | 关发送 → 终止 Worker 树 → 断内部交换机 → 保存审计 → 撤 ACL | 关发送 → 终止 → 删 NSG 规则 → 快照/关机 → 释放资源 |
| 适用判断 | 已有硬件且要求最强隔离 | 需要快速搭建/可销毁，接受云平台旁路风险 |

**建议**：首版优先方案 B（云 VM），因为可快速销毁、成本按小时可控；但必须额外封堵
云元数据端点（169.254.169.254）与云侧代理路径，并把「云平台旁路」列入实测矩阵。

### 3.2 部署前置清单（按顺序，均需人工批准后执行）

1. 确定宿主方案（A/B）与资源配额。
2. 创建隔离虚拟网络（默认拒绝出站），记录网段与路由。
3. 创建 Worker VM 与 Egress VM，仅接隔离网络。
4. 在 Worker VM 创建专用非管理员账户；密码入受保护凭据存储。
5. 部署 Launcher（只读程序/授权输入/审计收据，输出独立可写）。
6. 部署 Egress（固定 Messages POST、TLS 校验、禁重定向、不重编码、不重试、日志脱敏）。
7. **批准决定 1 后**：把 API Key 迁入 Egress 凭据存储（Worker 不接触）。
8. 生成宿主/出口签名密钥对，登记 `key_id` 与轮换策略。
9. 执行 S9-5 实机矩阵 + 回滚演练。
10. 首次真实请求单独审批（合成业务内容）。

### 3.3 成本口径（可核价，不写死金额）

金额随区域/系列/付费方式波动，**不在此写死**；按下列维度逐项核价即可：

| 计费项 | 方案 A（物理主机） | 方案 B（云 VM） |
|---|---|---|
| 计算 | 硬件折旧（一次性） | Worker VM（2 vCPU/4–8 GiB）× 常驻小时 |
| 许可 | Windows Pro/Server 许可（一次性或订阅） | 云镜像已含 Windows 许可，计入小时单价 |
| 存储 | SSD 折旧 | 系统盘 + 数据盘（按 GB·月） |
| 网络 | 无 | 出站流量（仅出口→上游，量极小） |
| 出口 VM | 复用同机 VM | 1 vCPU/1 GiB 常驻 |
| 停机策略 | 不适用 | 验收完成后可关机/释放，仅保留镜像与审计导出 |

核价步骤（方案 B）：选定区域 → 选 Windows Server 2022 镜像 → 取 2 vCPU/8 GiB 档 →
记录按需小时价 × 预估运行小时 + 磁盘 GB·月 + 出站 GB 单价；再把出口 VM 同法相加。
**验收期建议按「按需 + 用后释放」核价**，避免预留承诺。

### 3.4 回滚清单（按序执行，任一步失败即中止并告警）

| 序 | 动作 | 验证点 |
|---|---|---|
| 1 | 关闭发送入口（`real_ai_enabled=0`、`worker_real_transport=0`） | 新请求被 S9 门禁拒绝 |
| 2 | 终止 Worker 进程树并等待退出 | 无残留进程（`is_process_alive` 全假） |
| 3 | 断开隔离网络（禁用内部交换机/NSG 全拒绝） | 出口不可达 |
| 4 | 导出审计与证据（`send_audit_records`、`send_receipt_evidence`、`s9_replay_guard`） | 行数与校验和留存 |
| 5 | 按对象 ID 撤销 VM/账户/凭据/密钥 | 清单逐项勾销 |
| 6 | 恢复原有 ACL/防火墙策略（若有变更） | SDDL 与基线一致 |

## 4. 任务四：真实环境放行门禁

| # | 问题 | 结论 |
|---|---|---|
| 1 | 合成链路是否真正贯通 | **是（离线合成）**：Host→Launcher→Egress→Synthetic Provider→收据→审计 全链路 13 个测试通过，`confirmed_sent` 正确落唯一终态 |
| 2 | 宿主授权与发送收据是否完整对应 | **是**：宿主收据绑定 attempt/authorization/receiver/request_digest/status/policy/有效期；出口收据额外绑定 actual_body_sha256/terminal_phase/http_status/raw_response_sha256/provider_request_id；宿主侧双向比对 |
| 3 | 未配置真实 OS 隔离时是否保证零真实外发 | **是**：`real_ai_enabled=False` 与 `worker_real_transport=False` 默认；真实模式需同时具备 Key + S9 网络边界证据；合成链路无任何网络调用（Synthetic Provider 进程内） |
| 4 | 哪些已离线通过 / 哪些必须 VM 实测 | 见 §5 |
| 5 | 首次真实百炼调用还剩哪些阻断 | 见 §6 |

## 5. 状态划分（离线 PASS / 需 VM / BLOCKED）

**离线 PASS**
- S9-1：`pre_resume_check` fail-closed（含缺失参数）、resume 门禁、纳管失败 terminate、进程树回收、输入只读/输出可写。
- S9-2：attempt/authorization/receiver/request_digest 完整绑定、收据验签（含 approved/issued_at/policy）、
  幂等与并发唯一索引、迟到证据、唯一终态、append-only（触发器）。
- S9-3A：合成链路全链路、**独立子进程 IPC（multiprocessing.Pipe）**、防重放（launcher/egress 各自持久化）、
  固定路径、超时/断线不重发、取消语义、重启恢复入口。
- 迁移：0001→0012 从零升级 + 有数据既有库（0010→0012）升级。

**需 VM 实测**
- 真实 `LogonUserW` 与独立 TokenUser（本地受限令牌无法伪造 TokenUser 不匹配）。
- 挂起创建接入生产 `Sandbox.run`（当前未接线）。
- Guest 网络默认拒绝、固定出口实际连通、`5157` 拒绝观测。
- 云平台元数据端点（169.254.169.254）与云侧代理路径封堵。

**BLOCKED**
- API Key 归属变更（决定 1 未批准）→ 出口持 Key、Worker 不持 Key 无法落地。
- 真实百炼调用（需 Key + 网络边界 + 首次请求单独审批）。

## 6. 首次真实百炼调用剩余阻断条件

1. **决定 1 未批准**：API Key 是否由固定出口持有（涉及已批准 `agent-adapter.md` §1）。
2. **S9 网络边界证据缺失**：`network_boundary.evaluate` 需 `verified`（当前必然 `not_configured`）。
3. **挂起创建未接线**：生产 `Sandbox.run` 仍非挂起创建，S9-1 门禁未生效于真实路径。
4. **VM 未部署**：Worker/Egress VM、隔离网络、专用账户均不存在。
5. **签名密钥未托管**：宿主/出口 `key_id` 与轮换机制未落地（当前 HMAC 由调用方注入）。
6. **首次请求未审批**：S9-5 要求首次真实请求单独人工审批（合成业务内容）。

## 7. 代码修改清单

| 文件 | 变更 |
|---|---|
| `app/isolation/win32.py` | `pre_resume_check` 三参数缺失即 fail-closed（`expected_*_missing`） |
| `app/services/receipts.py` | `verify_host_receipt` 增 approved/issued_at/policy 白名单；新增 `verify_host_receipt_against_request`（无 DB 行的 Launcher 侧验证）；`append_receipt_evidence` 写 `receipt_signature`；`record_late_receipt` 捕获 `IntegrityError` 幂等 |
| `app/models/outbound.py` | `SendReceiptEvidence` 增 `receipt_signature` 列 + 部分唯一索引 |
| `app/models/s9_replay.py`（新） | `S9ReplayGuard` 模型 |
| `app/models/__init__.py` | 导出 `S9ReplayGuard` |
| `app/db.py` | 新增 `s9_replay_guard` append-only 触发器 |
| `app/services/s9_chain.py`（新） | 合成链路：`HostGateway` / `Launcher` / `EgressRelay` / `SyntheticProvider` / `ReplayStore` |
| `alembic/versions/0011_receipt_evidence_dedupe.py`（新） | `receipt_signature` 列 + 唯一索引 |
| `alembic/versions/0012_s9_replay_guard.py`（新） | 防重放表 + append-only 触发器 |
| `tests/test_s9_chain.py`（新） | 13 个链路测试 |
| `tests/test_s9_receipts.py` | 新增 4 个（approved/future issued_at/policy 白名单/并发唯一索引） |
| `tests/test_s9_win32.py` | 新增 3 个（缺失参数 fail-closed/错误程序摘要）+ 适配新签名 |

## 8. 执行边界确认

未变更生产 API Key 归属契约、未读取/使用真实 Key、未开启真实百炼请求、未创建 VM/系统账户、
未修改生产 ACL/防火墙、未访问真实业务仓库、未修改 ADLL-Knowledge、未 Git Commit/Push。
