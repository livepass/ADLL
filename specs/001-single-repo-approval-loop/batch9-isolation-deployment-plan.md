# 批 9 独立隔离环境评估与部署方案

**Date**: 2026-10-21
**性质**: 只读环境核查 + 部署方案；未修改账户、ACL、防火墙、未安装组件、未发起模型请求。
**结论摘要**：机器上存在**已验证用途的独立低权限账户与离线网络阻断规则**
（`CodexSandboxOffline` / `CodexSandboxOnline`），但本会话没有获得
“以这些账户启动进程”的已批准凭据/启动通道；因此**独立主体下的运行时实测仍为
NOT RUN**。批 8 的“当前用户受限令牌”保留为纵深防御，**不作为最终 OS 安全边界**。

## 1. 机器实际能力（只读核查）

| 项 | 实际值 | 证据/说明 |
|---|---|---|
| OS | Windows 11 家庭中文版 10.0.22000（Build 22000） | `Win32_OperatingSystem` |
| 虚拟化 | `HypervisorPresent=True`；`vmcompute`、`vmms`、`WslService` 运行中 | WSL2/Hyper-V 平台存在 |
| Windows Sandbox | **不可用**：`C:\Windows\System32\WindowsSandbox.exe` 不存在；可选功能查询无结果 | 家庭版通常无此功能 |
| Hyper-V 管理 | `Get-VM` 不可用（无 Hyper-V PowerShell 模块） | 不能直接管理 VM |
| WSL | 仅 `docker-desktop` 发行版，状态 Stopped，版本 2 | 无常规 Linux 发行版 |
| Docker | Docker Desktop 未运行；`docker version` 无法连接 daemon；无可用本地镜像清单 | 启动/拉取镜像属于环境变更，本批未做 |
| 当前用户 | `LAPTOP-S7N4266A\焦嘉鑫`，SID `…-1001`，**本机 Administrators 成员** | 未使用管理员权限修改策略 |
| 本地账户 | `CodexSandboxOffline`（SID `…-1018`）、`CodexSandboxOnline`（SID `…-1019`），均启用 | 既有独立低权限账户 |
| 沙箱组 | `CodexSandboxUsers`，成员为上述两个账户 | 既有 |
| 沙箱服务 | `CodexSandboxService.OpenAI.Codex`（显示名 ChatGPT），LocalSystem，Running | 既有，属另一个应用；未调用其内部协议 |
| 沙箱 CLI | `codex sandbox` 帮助标明“Windows restricted token sandbox”；`codex-command-runner` 需要管道协议 | 未作为 ADLL 运行时依赖；未读取任何凭据 |
| 防火墙默认 | Domain/Private/Public 均启用；DefaultOutboundAction = `NotConfigured`（默认允许） | 共 511 条规则 |

## 2. 既有防火墙规则（静态证据，未修改）

存在 3 条针对 **CodexSandboxOffline SID `…-1018`** 的出站 Block 规则：

| 规则 | 方向/动作 | 作用域（关键字段） |
|---|---|---|
| `codex_sandbox_offline_block_outbound` | Outbound / Block / Profile=Any / Enabled | `LocalUser` = SID `…-1018`；`RemoteAddress` = 全部 IPv4/IPv6，但排除 `127.0.0.0/8` 与 `::1` |
| `codex_sandbox_offline_block_loopback_tcp` | Outbound / Block | `LocalUser=…-1018`；TCP 1-65535；RemoteAddress=Any |
| `codex_sandbox_offline_block_loopback_udp` | Outbound / Block | `LocalUser=…-1018`；UDP 任意 |

→ **静态结论**：该账户的出站流量（含回环）应被阻断。**运行时不等于已实测**：
本会话没有以 `…-1018` 启动进程的凭据/通道，故“实际连接被拒绝”仍为 NOT RUN。

对 **CodexSandboxOnline SID `…-1019`**：查询到 **0 条出站规则**。
→ 该账户默认允许全部出站，**不能用于 S9 的受限真实调用**。

## 3. 文件系统 ACL 发现

- `D:\wo\code\ADLL\ADLL`（项目根）ACL：`Everyone: FullControl`（继承）。
- `C:\Users\CodexSandboxOffline\Documents` / `…\Online\Documents`：仅
  `SYSTEM`、`Administrators`、账户自身 FullControl。
- 因此：即使以 `CodexSandboxOffline` 运行，它仍可读取
  `D:\wo\code\ADLL\ADLL` 下的项目/数据库（Everyone 授权），除非另行
  **Deny SID `…-1018`** 或将数据移到仅后端可读的目录。
- 该 Deny 属于修改真实项目/生产 DB ACL；本批未做，需单独批准。
- 合成测试可在临时目录完成：Allow 账户读 subset、Deny 账户读合成原仓库/合成 DB/
  合成用户目录；不触碰真实目录。

## 4. 方案比较与推荐

| 方案 | 隔离主体 | 文件隔离 | 出站阻断 | 所需变更/审批 | 评价 |
|---|---|---|---|---|---|
| A. 复用 `CodexSandboxOffline` + 既有 Block 规则 | 独立账户 SID 1018 | 需对真实路径 Deny 1018，或用临时合成根 | 已有静态规则，需运行时复核 | 需要一个**已批准的启动通道**（用户手动 `runas`/既有服务）；生产路径 ACL 或 staging | **离线 worker 首选**；不读凭据、不改防火墙 |
| B. 复用 `CodexSandboxOnline` + 新增出站限制 | 独立账户 SID 1019 | 同上 | 当前无限制；需新增 Block（排除回环）+ 本地 allowlist 代理，或改用 VM | 防火墙规则/代理/可能 PFX；需批准 | 首次真实调用**不能直接用现状**；需批准网络变更 |
| C. 专用 VM/容器（WSL2/Docker） | VM/容器 | 结构性（不挂载宿主） | 网络命名空间/iptables allowlist | 需启动 Docker/创建 VM、拉取/构建镜像（可能安装组件） | 安全上最干净；需环境/镜像授权 |
| D. 批 8 当前用户受限令牌 + DACL | 同一用户 restricted token | DACL（已验证） | 无 OS 出站边界 | 无 | **仅纵深防御；不作为最终边界** |

### 推荐（需用户选择其一）

**Offline 验证（S1b/S10/S14/S15）**：方案 A。
- 由用户或已获授权的本地助手以 `CodexSandboxOffline` 启动 `scripts/account_isolation_probe.py`
  （本批提供脚本，未执行）；测试根使用合成目录。
- 预期：读取合成原仓库/合成 DB/合成用户目录失败；读取 subset 成功；TCP/UDP 出站
  （含回环探针）失败；进程无法获取审批 DB/会话。
- **不需要**修改真实目录 ACL 或全局防火墙；仅临时目录 ACL。

**首次真实调用（S9）**：方案 B 需新增网络限制，或方案 C 专用 VM/容器。
- 方案 B 最小变更（需批准）：
  1. 新增 Outbound Block 规则，`LocalUser=SID …-1019`，`RemoteAddress` 排除
     `127.0.0.0/8`、`::1`（与离线规则同形）；
  2. 不添加回环 Block；worker 仅允许访问 `127.0.0.1:<proxy>`；
  3. 本地 allowlist CONNECT 代理仅允许 `dashscope.aliyuncs.com:443`；
  4. 记录代理日志 + `pktmon` 目的地证据。
  - 回滚：删除新增规则；停止代理；无账户变更。
- 方案 C 变更（需批准）：启动 Docker/创建 VM、获取 Python 运行时镜像；
  容器/VM 仅挂载 subset，`--network` 由 allowlist 策略控制。
- **不得**使用方案 D 声称 S9 通过。

## 5. 本批实际完成/未完成

- 完成：只读能力核查、既有账户/规则/ACL 清点、方案比较、临时 ACL 边界再验证
  （批 8 证据）、S15 Job Object breakaway 追加测试、首次调用核对单；
  后端回归 **158 passed**（含新增 breakaway/非授权端点拒绝测试）。
- **未完成（NOT RUN）**：以 `…-1018`/`…-1019` 账户实际启动进程；以这些账户
  实测文件拒绝/防火墙拒绝；S9 真实出站；生产 DB/仓库 ACL 变更。
- 阻塞原因：无已批准的凭据/启动通道；不读取凭据、不创建账户、不改系统防火墙。

## 6. 需要的单独审批（精确变更与回滚）

1. **授权启动通道**：允许用户/本地助手以既有 `CodexSandboxOffline` 账户运行
   ADLL 探针（不向 Agent 暴露密码；由用户执行 `runas` 或既有服务）。
2. 或 **创建临时本地账户**（随机口令、仅 Users 组、测试后删除）+ 防火墙
   Block 规则（精确 SID/端口）+ 临时目录 ACL；回滚：删除账户/规则/目录。
3. **首次真实调用**：新增 SID 1019 出站 Block + 本地 allowlist 代理（或 VM），
   并提供 `pktmon`/代理日志观测。
4. 若采用 VM/容器：批准启动 Docker/创建 VM、获取镜像；不修改宿主防火墙。

> 本文件不构成任何系统变更授权。批 9 结束时真实发送仍关闭，S9 仍 NOT RUN。
## 7. 既有账户探针的执行前置（待批准后由用户/获批助手执行）

1. 在专用临时根（例如 `D:\adll-isolation-test`）创建：
   `subset\allowed.txt`、`originals\repo\a.txt`、`originals\db.sqlite`、
   `originals\user\notes.txt`；把 `backend/scripts/account_isolation_probe.py`
   复制到临时根（避免依赖项目目录）。
2. 以管理员 PowerShell 对临时根设置 ACL（**只改临时根**）：
   ```powershell
   $sid = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-21-2025351319-2623125666-1605255925-1018')
   function Add-Rule($path, $rights, $type) {
     $acl = Get-Acl -LiteralPath $path
     $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
       $sid, $rights, 'ContainerInherit,ObjectInherit', 'None', $type)
     $acl.AddAccessRule($rule); Set-Acl -LiteralPath $path -AclObject $acl
   }
   Add-Rule 'D:\adll-isolation-test\subset' 'Read' 'Allow'
   Add-Rule 'D:\adll-isolation-test\originals' 'FullControl' 'Deny'
   ```
   记录每步原始 SDDL，按逆序回滚。
3. 另开一个控制台，由用户执行（会交互式要求该账户口令；Agent 不接触口令）：
   ```
   runas /user:CodexSandboxOffline "python -I D:\adll-isolation-test\account_isolation_probe.py --allow D:\adll-isolation-test\subset\allowed.txt --deny D:\adll-isolation-test\originals\repo --deny D:\adll-isolation-test\originals\db.sqlite --deny D:\adll-isolation-test\originals\user --deny-write D:\adll-isolation-test\originals\db.sqlite --out D:\adll-isolation-test\evidence.json"
   ```
4. 网络拒绝探针：先由后端用户在本机 `127.0.0.1:8765` 启动仅绑定回环的合成监听；
   在探针命令加 `--tcp-host 127.0.0.1 --tcp-port 8765`。离线规则应使连接失败/超时；
   再对 `203.0.113.1:443`（TEST-NET-3，无真实服务）做同样检查。记录结果与防火墙规则。
5. 预期：`allow` 读取成功；`deny` 读取/写入失败；TCP 连接失败；`evidence.json`
   `ok=true`。若任一项不符，停止并按回滚清理。

> 注意：该账户默认能读取 `D:\wo\code\ADLL\ADLL`（Everyone FullControl）；
> 生产前必须对真实仓库/DB 做 Deny 或改用 VM/容器。上述临时根操作不触碰真实目录。
