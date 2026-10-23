# 批 9 环境与拒绝证据（只读核查）

**Date**: 2026-10-21
**性质**: 只读命令 + 既有合成测试；未修改账户/ACL/防火墙/系统组件；
未读取任何 API Key 或账户密码。

## 1. 执行主体/系统

| 项 | 观察值 |
|---|---|
| 当前用户 | `LAPTOP-S7N4266A\焦嘉鑫`，SID `S-1-5-21-2025351319-2623125666-1605255925-1001` |
| 管理员角色 | `IsInRole(Administrator) = True`（未用于修改策略） |
| OS | Windows 11 家庭中文版 10.0.22000.2538，64 位 |
| HypervisorPresent | True |
| 服务 | `vmcompute`、`vmms`、`WslService` Running；`mpssvc` Running |
| Windows Sandbox | `WindowsSandbox.exe` 不存在；可选功能无结果 |
| WSL | `docker-desktop`（Stopped，v2） |
| Docker | daemon 未运行；无法列出镜像 |

## 2. 既有独立账户

| 账户 | SID | 状态 | 配置目录 |
|---|---|---|---|
| `CodexSandboxOffline` | `…-1018` | Enabled，PasswordRequired | `C:\Users\CodexSandboxOffline`（Loaded=False） |
| `CodexSandboxOnline` | `…-1019` | Enabled，PasswordRequired | `C:\Users\CodexSandboxOnline`（Loaded=False） |

- `CodexSandboxUsers` 本地组成员 = 上述两个账户。
- 两账户的 `Documents` ACL：SYSTEM / Administrators / 账户自身 FullControl。
- 既有服务 `CodexSandboxService.OpenAI.Codex`（ChatGPT）LocalSystem Running；
  本批未调用其内部协议，未读取 `.sandbox-secrets`。

## 3. 防火墙（静态配置，未修改）

主机默认：Domain/Private/Public 启用，`DefaultOutboundAction = NotConfigured`
（默认允许）；规则总数 511。

| 规则 | LocalUser | Direction/Action | RemoteAddress / Protocol |
|---|---|---|---|
| `codex_sandbox_offline_block_outbound` | `…-1018` | Outbound / Block / Any profile / Enabled | 全部 IPv4/IPv6，排除 `127.0.0.0/8` 与 `::1` |
| `codex_sandbox_offline_block_loopback_tcp` | `…-1018` | Outbound / Block | TCP 1-65535，Any |
| `codex_sandbox_offline_block_loopback_udp` | `…-1018` | Outbound / Block | UDP Any |
| （对 `…-1019` 的出站规则） | — | — | **0 条** |

**结论（静态）**：`…-1018` 被配置为阻断全部出站（含回环）；`…-1019` 无出站限制。
**运行时不等于已验证**：本会话无 `…-1018` 的已批准启动通道/凭据，故未实测连接拒绝。

## 4. 文件系统 ACL 关键发现

- `D:\wo\code\ADLL\ADLL`：`Everyone FullControl`（继承）。
- 因此 `CodexSandboxOffline` 若启动，默认可读取项目/数据库；必须：
  - 对真实路径添加 `Deny SID …-1018`（需批准；本批未做），或
  - 使用 VM/容器不挂载宿主，或
  - 将 DB 移到仅后端可读的目录并隔离 staging。
- 合成测试目录可在 ACL 上 Allow `…-1018` 读 subset、Deny 读合成 repo/DB/user；
  该操作只影响临时目录，允许执行。

## 5. 实际执行的测试证据（批 8/9）

| 测试 | 结果 |
|---|---|
| `pytest -q`（全量） | **158 passed** |
| `test_worker_isolation.py` | 9 passed（含 breakaway、非授权端点拒绝） |
| `test_worker_adapter.py` | 7 passed |
| `test_security_canary.py` | 1 passed |
| `test_snapshot.py` | 含归档篡改检测 |
| 批 8 浏览器（Edge/CDP） | 全流程 + 403/409/423/503/401 通过 |

Breakaway 实测（`test_job_object_denies_breakaway`）：
- 子进程以 `CREATE_BREAKAWAY_FROM_JOB` 启动成功（`STARTED`），
  但 `IsProcessInJob(child, job) = True`（未脱离），Job 终止后子进程不再存活。
- 未穷举所有子进程创建方式；若改用 VM/容器需重新裁定 S15。

## 6. 未执行与阻塞

| 项 | 状态 | 原因 |
|---|---|---|
| 以 `…-1018` 运行 ADLL 探针 | **NOT RUN** | 无已批准启动通道/凭据；不读取密码、不创建账户 |
| 以 `…-1018` 实测文件拒绝 | **NOT RUN** | 同上；且需临时 ACL 配置 |
| 以 `…-1018` 实测防火墙拒绝 | **NOT RUN** | 同上；静态规则已核对 |
| S9 真实外发核对 | **NOT RUN** | 未授权真实调用；`…-1019` 无出站限制 |
| 生产 DB/仓库 ACL 修改 | **未做** | 需单独批准 |

## 7. 现有可复用工具（未作为 ADLL 依赖）

- `.codex/.sandbox-bin/codex-command-runner-*.exe`：需要管道协议（`no pipe-in provided`），
  非通用 CLI；未使用。
- `codex sandbox` 子命令宣称“Windows restricted token sandbox”；未作为 ADLL 运行时依赖。
- `.sandbox-secrets` 存在但**未读取**；任何使用既有账户的方案都必须由用户/获批助手
  提供启动通道，Agent 不接触凭据。

## 8. 变更与回滚

本批**没有**变更：无账户、无防火墙规则、无真实目录 ACL、无系统组件、无服务。
若下一批批准 ACL/防火墙/账户变更，回滚要求：
- ACL：修改前保存 SDDL，按逆序恢复；
- 防火墙：记录规则名/GUID，删除新增规则；
- 账户：仅临时账户，测试后删除并确认 profile 清理；
- VM/容器：停止并删除实例/卷，不保留宿主挂载。