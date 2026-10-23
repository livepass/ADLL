# S9 真实发送门禁与 OS 隔离方案收口

> 当前效力：本文为历史记录，不可作为当前部署或真实发送许可。S9 架构与验收以 [执行身份与网络隔离架构裁定](s9-isolation-architecture-decision.md) 为准。旧 block_all + allow_dashscope 组合已裁定 NO-GO；部署位置待定，生产发送仍关闭。

**日期**：2026-10-23　**基线**：GitHub main `2df5fcc`（= 本机 HEAD）
**边界**：未 Commit/Push、未调用真实百炼、未读 Key、未改 ACL/防火墙、未创建账户/VM/容器、
未访问真实业务仓库、未修改 ADLL-Knowledge。

## 1. CI（run 39955948177）

| Job | 结论 | 说明 |
|---|---|---|
| backend（windows-latest） | **success** | 依赖安装、迁移、编译、pytest 全绿（11 分钟） |
| frontend（ubuntu-latest） | **success** | npm ci / test / build 全绿 |

无失败、无 skipped 步骤。该 run 对应 `2df5fcc`（上一轮提交已推上 GitHub）。

## 2. S9 评估器假阳性修复

`services/network_boundary.py` 重写 `evaluate()`，`verified` 现在要求**完整覆盖**，
任意一条狭窄 block 不再算数：

- `outbound_block_covers_all` / `_ipv4` / `_ipv6` 必须全部成立；
- `loopback_blocked` / `proxy_blocked` / `no_allow_bypass` 缺一即 `unverified`；
- 同一主体存在任何出站 `allow` 规则 → `allow_rule_overrides_block`；
- `collector_errors` 非空 → 立即 `unverified`（fail-closed），不再进入任何通过分支；
- 不能靠直接传几个 True 冒充：`collect_boundary_evidence()` 只做只读采集，
  `observed_denial`/`allowed_channel_digest_match`/覆盖标志一律从 False 起步，
  只有专项拒绝观测探针才能补真。

新增负向测试（`tests/test_network_boundary.py` 18 项）：窄 block 非完整白名单、
缺 IPv6/IPv4、回环未阻断、代理未阻断、allow 绕过、同主体 allow+block、采集错误 fail-closed。

## 3. Worker 真实 OS 安全主体

事实（只读核对 `win32.py`）：

- 父进程 TokenUser = 后端账户 SID（`current_user_sid()`）。
- Worker 子进程用 `CreateRestrictedToken` + `CreateProcessAsUserW` 派生，
  **TokenUser 仍 = 父账户 SID**（CreateRestrictedToken 不更换 TokenUser），
  只是叠加 restricting SIDs（Users/Authenticated/Everyone/随机）。
- 随机 restricting SID 只用于 DACL 判定，不是账户、不出现在 TokenUser。

结论：防火墙 `LocalUser` 规则应匹配的**真实主体是 Worker 子进程的实际 TokenUser**，
当前即后端账户；`ADLLTest`/随机 SID 都不是。要让 S9 成立，必须先有**专用 Worker 账户**。

两条路线（对比见部署说明）：A. 专用本地账户（推荐，成本/回滚最低）；B. 独立 VM/容器。
本文件不创建账户、不改配置。

## 4. S9 作为真实发送强制门禁

- `config.py` 新增 `worker_principal_sid`（env `ADLL_WORKER_PRINCIPAL_SID`）。
- `factory.py` 传入；`WorkerAgentAdapter.generate()` 在 `mode=="real"` 分支，
  于 `DASHSCOPE_API_KEY` 检查之后、启动 worker 之前调用
  `collect_boundary_evidence()` + `evaluate()`，未 `passed` → `AdapterDisabled`（零外发）。
- 仅 `real_ai_enabled` + `worker_real_transport` + Key 存在**不能**绕过 S9。
- 合成模式（`synthetic=True`）不进 real 分支，不触发、也不冒充 OS 网络证据。
- worker 发送前 `body_digest_error` 已复核审计 `request_digest`。

离线负向测试 `tests/test_s9_gate.py`（4 项，mock 采集器）：无主体/采集异常/无出站规则/
仅有 Key+transport 四种情况均被拒绝，且 `last_result is None`；合成模式不调用采集器。

## 5. 交付材料

- [`s9-controlled-network-deployment.md`](./s9-controlled-network-deployment.md)：受控网络部署说明（安全主体、执行文件、策略范围、拒绝观测、授权通道、宿主影响、回滚）。
- [`s9-first-real-call-checklist.md`](./s9-first-real-call-checklist.md)：首次真实调用核对单（合成数据、固定端点/模型、完整 JSON+SHA-256、单次无重试、max_tokens/timeout/费用、Key 注入清理、S9/审计/响应/核验/方案对账）。

## 6. 改动文件

- 改：`app/services/network_boundary.py`、`app/agents/worker.py`、`app/agents/factory.py`、
  `app/config.py`、`scripts/s9_network_probe.py`、`tests/test_network_boundary.py`。
- 新增：`tests/test_s9_gate.py`、两份部署/核对单文档。

## 7. 实际 S9 阻断项（截至本轮）

- Worker 安全主体未配置（`ADLL_WORKER_PRINCIPAL_SID` 空）；`ADLLTest` 不存在。
- 无绑定 Worker 的出站 block 规则（仅 Codex …-1018 的 3 条）。
- 无 `observed_denial`、无完整覆盖证明 → 评估器 `not_configured`，真实发送必然被 S9 门禁拒绝。

## 8. 回归

| 项 | 结果 |
|---|---|
| 后端全量 `pytest -q` | **285 passed**（1407s；含 `test_s9_gate`、`test_network_boundary` 新增用例） |
| 定向 S9 | `test_s9_gate` + `test_network_boundary` 23 passed |
| 前端 | `npm test` 20 passed、`npm run build` 成功 |
| lint | 改动文件 `ruff --select F,I` 全绿 |

CI：run 39955948177（`2df5fcc`）backend + frontend 均 **success**，无失败/跳过步骤。
