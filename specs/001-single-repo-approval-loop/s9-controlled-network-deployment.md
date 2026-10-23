# S9 受控网络环境部署说明（供人工审核，不实际执行）

> 当前效力：本文为历史记录，不可作为当前部署或真实发送许可。S9 架构与验收以 [执行身份与网络隔离架构裁定](s9-isolation-architecture-decision.md) 为准。旧 block_all + allow_dashscope 组合已裁定 NO-GO；部署位置待定，生产发送仍关闭。

**日期**：2026-10-23　**状态**：只读评估，未创建账户、未改防火墙、未装 VM/容器。

## 1. 关键事实：Worker 的真实 OS 安全主体

当前实现（`win32.create_restricted_token` + `CreateProcessAsUserW`）并**不是**以
独立账户启动 Worker：

| 概念 | 是什么 | 是否独立账户 |
|---|---|---|
| 父进程 TokenUser SID | 后端进程账户（开发者，如 `S-1-5-21-…-1001`） | — |
| Worker 子进程 TokenUser SID | 继承自父进程，**同一个账户 SID**（CreateRestrictedToken 不更换 TokenUser） | 否 |
| restricting SID | 随机 S-1-5-21-…-random，仅用于 DACL deny/allow 判定 | 不是账户 |

结论：**防火墙 `LocalUser` 出站规则要匹配的真实主体，是 Worker 子进程的实际
TokenUser（当前 = 后端账户），而不是 `ADLLTest`，也不是随机 restricting SID。**
仅靠 `CreateRestrictedToken` 无法让防火墙按独立账户区分 Worker 与后端。

因此，S9 要成立，必须先引入**专用 Worker 安全主体**（见 §2 两条路线）。

## 2. 两条可行路线对比

| 维度 | A. 专用本地账户 | B. 独立 VM / 容器 |
|---|---|---|
| 安全主体 | 新建本地账户 `ADLLWorker`（非 Codex 托管） | 独立 Windows/Linux VM 或容器 |
| 网络隔离 | 靠 Windows Firewall LocalUser 规则 | 靠 VM/容器网络策略（更彻底） |
| 资源 | 一个本地账户 + 一组防火墙规则 | 一台 VM / 容器编排 |
| 权限 | 最小权限、无交互登录、Deny Logon | VM 自身独立 |
| 网络 | 出站 block（IPv4+IPv6+回环+代理） + 仅允许百炼端点 | 默认拒绝 + 仅放行百炼端点 |
| 回滚 | 删账户 + 删规则，秒级 | 删 VM / 容器 |
| 成本 | 低 | 中-高 |

**推荐路线 A（专用本地账户）**：资源与回滚成本最低，且能直接用现有
`worker_principal_sid` 配置 + 防火墙 `LocalUser` 规则落地 S9 证据。

## 3. 推荐方案（路线 A）精确对象

- **安全主体**：本地账户 `ADLLWorker`（`New-LocalUser`，无管理员、无交互登录、
  `Deny Logon`），SID 记入 `ADLL_WORKER_PRINCIPAL_SID`。
- **执行文件**：`ADLL_WORKER_PYTHON` 指向的基础 Python（stdlib 只读）。
- **网络策略**（`New-NetFirewallRule`，全部 `Direction=Outbound`、绑定 `ADLLWorker`）：
  1. `block_all_ipv4`：`RemoteAddress=Any`，`Action=Block`，`Protocol=Any`；
  2. `block_all_ipv6`：`RemoteAddress=Any`，`Action=Block`，`Protocol=Any`；
  3. `block_loopback`：`RemoteAddress=127.0.0.0/8,::1`，`Action=Block`；
  4. `block_proxy`：阻止经父进程代理/回环绕过（配合 Worker 环境 `NO_PROXY=*`）；
  5. `allow_dashscope`：`RemoteAddress=<百炼端点解析的 IP 或 FQDN>`，
     `Action=Allow`，`RemotePort=443`，`Protocol=TCP`，**在 block 之后、作用域更窄**。
- **不触碰**：`codex_sandbox_offline_block_*`（…-1018）等 Codex 托管规则；不复用其账户。

## 4. 如何观测到 OS 拒绝（`observed_denial` 的证据来源）

- 以 `ADLLWorker` 身份发起对**非授权目的地**（如 `203.0.113.1:443`）的连接，
  连接被 `WSAECONNRESET` / 防火墙审计事件 `5157`（Windows Filtering Platform）
  拒绝，并记录时间戳 + 目标 + 主体 SID。
- 仅凭应用层 4xx、TEST-NET 超时、DNS 失败**不算**拒绝观测。

## 5. 授权通道如何保证可达

- 仅放行百炼端点 `dashscope.aliyuncs.com/apps/anthropic/v1/messages`（443/TCP），
  且 Worker 环境 `NO_PROXY=*`、`build_opener` 禁代理禁重定向；
- 发送前 `body_digest_error` 复核审计 `request_digest`，保证授权通道与审计一致。

## 6. 对宿主的影响

- 新增一个最小权限本地账户 + 若干防火墙规则；不影响现有用户、Codex 规则、
  生产项目 ACL；不改变后端主进程网络行为。

## 7. 精确回滚与失败恢复

```powershell
# 回滚：删除规则（按名称）与账户
Get-NetFirewallRule -DisplayGroup 'ADLLWorker*' | Remove-NetFirewallRule
Remove-LocalUser -Name 'ADLLWorker'
# 失败恢复：S9 评估器 fail-closed，未 verified 即零外发，不会半途放行。
```

## 8. 落地前的人工批准项

- 确认是否接受新增本地账户 + 防火墙规则（本文件不执行）。
- 确认百炼地域端点与模型（见首次调用核对单）。
