# 批 9 S1～S15 验证矩阵（环境/部署更新）

**Date**: 2026-10-21
**Supersedes**: [batch8-s1-s15-verification-matrix.md](./batch8-s1-s15-verification-matrix.md)
（批 8 记录保留）
**环境**: Windows 11 家庭版；既有 `CodexSandboxOffline`/`CodexSandboxOnline`
账户与离线防火墙规则；**本会话未以这些账户启动进程**（无已批准启动通道），
未修改真实 ACL/防火墙/账户，未发起真实模型请求。

## 判定口径

- `PASS（lab）`：在批 8 的当前用户受限令牌 + DACL + Job Object 合成环境中实测。
- `PASS（静态）`：只读取既有账户/防火墙/ACL 配置，未运行。
- `NOT RUN`：未执行，不得声称通过。
- 独立主体（`CodexSandboxOffline`/VM）下的最终验收尚未完成，因此 S1b/S10/S14
  的“生产级”判定仍为 NOT RUN。

**回归结果**：`backend/.venv/Scripts/python.exe -m pytest -q` → **158 passed**
（批 7 基线 138 + 批 8/9；批 9 新增 breakaway/非授权端点拒绝 2 项）。

| # | 用例 | 判定 | 证据 / 边界 |
|---|---|---|---|
| S1a | 经 HTTP 直写批准/绕过门禁 | **PASS** | 批 7/8 审批测试（role/CSRF/未认证/stale/append-only） |
| S1b | OS 级读写审批 DB | **PASS（lab）**；独立账户 **NOT RUN** | 批 8 `test_probe_denies_repo_db_home_credential_and_allows_subset`；批 9 未以 `…-1018` 账户运行 |
| S2 | 仓库提示注入不执行 | **PASS（lab）** | 批 8 注入 canary；真实模型注入鲁棒性仍未验证 |
| S3 | 仓库脚本零执行 | **PASS（lab）** | 批 8 `run.bat` 未执行、标记未生成 |
| S4 | 拒绝/撤销/取消后零发送 | **PASS** | 批 7/8 测试 + 浏览器 403 |
| S5a | 密钥 canary 进入发送面 | **PASS** | 敏感/LFS/未授权排除 |
| S5b | canary 出现在日志/序列化/DB | **PASS（lab）** | 批 8 canary 测试；真实外发日志未测 |
| S6 | 恢复后证据不齐不判通过 | **PASS**（重启中断） | 批 7 测试；完整归档四类证据场景未覆盖 |
| S7 | 取消后迟到结果 | **PASS** | 批 8 测试 + worker `sent.marker` 真结果分类 |
| S8 | Commit 丢失/不可验证 | **PASS** | 批 7 适配器/基准测试 |
| S9 | 真实外发网络核对 | **NOT RUN** | 未发起真实提供商流量；无 `pktmon`/代理日志。**现有 `…-1019` 账户无出站规则，不能直接使用** |
| S10a | 文件/DB/审批/配置加载隔离 | **PASS（lab）** | 批 8 探针 + 审批测试；worker 最小环境、无仓库路径 |
| S10b | 独立主体 OS 越权 + 出站 | **NOT RUN** | 未以 `…-1018` 运行；D:\ 项目 ACL 为 Everyone FullControl，账户默认可读项目/DB，需 Deny 或隔离布局 |
| S11a | canary 进入 manifest 外内容 | **PASS** | 批 8 manifest 对齐 |
| S11b | canary 真实外发/日志/费用 | **PASS（lab）**；真实外发 **NOT RUN** | 批 8 日志/job/SQLite 扫描 |
| S12a | 快照/核验记录篡改 | **PASS** | append-only/终态冻结触发器 |
| S12b | 归档内容寻址复核 | **PASS** | 批 8 `verify_materialized` 篡改/缺失/额外文件测试 |
| S13 | Agent 直连审批接口 | **PASS** | 批 7 role/CSRF/未认证组合 |
| S14a | 探针机制（允许/拒绝） | **PASS（lab）** | 批 8 探针 + `self_check` 证据化；缺 Deny/客体缺失失败 |
| S14b | 生产独立主体启动探针 | **NOT RUN** | 无已批准 `CodexSandboxOffline` 启动通道；已准备 `scripts/account_isolation_probe.py`，未执行 |
| S15 | Job Object 进程树/breakaway | **PASS** | 批 8/9：关闭 Job 杀死 worker+子进程；带 `CREATE_BREAKAWAY_FROM_JOB` 的子进程仍留在 Job（`IsProcessInJob=True`）并被终止；未穷举所有创建方式。若改用 VM/容器，需重新裁定 |

## 结论

- **不能**以批 8 的当前用户受限令牌或应用内固定端点声称最终 OS 安全边界；
  也不能把现有 `CodexSandboxOnline`（0 条出站规则）用于真实调用。
- **首次真实调用门禁**：S9、S10b、S14b 未通过前，保持
  `ADLL_REAL_AI_ENABLED=0`、`ADLL_WORKER_REAL_TRANSPORT=0`。
- 下一步需用户在下列任一路径上单独批准：
  1. 既有 `CodexSandboxOffline`/`Online` 的启动通道 + 必要的临时 ACL/防火墙规则；
  2. 专用 VM/容器（WSL2/Docker）及镜像/网络策略；
  3. 临时本地账户 + 精确 ACL/防火墙变更。
- 详细方案、变更对象与回滚见
  [batch9-isolation-deployment-plan.md](./batch9-isolation-deployment-plan.md)；
  首次调用核对单见
  [batch9-first-real-call-checklist.md](./batch9-first-real-call-checklist.md)。
## S14 / S15 专项裁定

- **S14（运行时权限探针）**：
  - 机制层面 **PASS**：`self_check` 由真实探针证据决定，缺 Deny/客体缺失即失败；
    不存在配置开关强制 `ok=true`。
  - 生产独立主体层面 **NOT RUN**：尚未以 `CodexSandboxOffline`/VM 启动探针，
    因此不能宣称生产文件/DB/用户目录隔离已通过。
- **S15（Job Object / 进程树）**：
  - **PASS（Job Object 适用）**：worker 为独立进程；关闭 Job 终止 worker+子进程；
    带 `CREATE_BREAKAWAY_FROM_JOB` 的子进程未脱离 Job 且被终止；未设置
    BREAKAWAY_OK/SILENT_BREAKAWAY_OK。
  - 若最终改用 VM/容器，Job Object 不再适用，须按新机制重新提供“进程/容器终止 +
    无逃逸”的等效证据，不能沿用本结论。
