# 批 10 S1～S15 验证矩阵（请求摘要修复 + 账户验证状态）

**Date**: 2026-10-21（2026-10-22 账户实测更新）
**Supersedes**: [batch9-s1-s15-verification-matrix.md](./batch9-s1-s15-verification-matrix.md)
（批 9 记录保留）
**本批实际执行**：payload_digest 离线修复与测试；账户创建/启动 **NOT RUN**（口令须用户本地输入，
AI 未接收；未使用 Codex 沙箱身份）。
**2026-10-23 最终更新**：`ADLLTest` 已完成生产 ACL 硬化后的自测，**整体 PASS**：
`verified=true`、`verification_errors=[]`、`exit_code=0`、
`production_isolation_pass=true`、`self_check/generate/job=passed`、
`cleanup_errors=[]`、`project_read=PermissionError`。
**S10/S14 在本次测试范围内通过**；S9 真实 provider、S11b 真实外发仍 **NOT RUN**。
详见 [batch10-account-verification-report.md](./batch10-account-verification-report.md) §8–§10。
**回归**：后端 **208 passed**（2026-10-22，`_allow_traverse` 前）；最终 traverse
改动由隔离测试 **27 passed** 覆盖；前端 `npm test` **8 passed**、`npm run build` 成功。

| # | 用例 | 判定 | 证据 / 边界 |
|---|---|---|---|
| S1a | HTTP 直写批准/绕过门禁 | **PASS** | 批 7/8 审批测试 |
| S1b | OS 级读写审批 DB | **PASS（lab + 账户级）** | 账户主体对 repo/DB/user 读、DB 写均为 `PermissionError`；受限 self_check/generate/job 全部 passed |
| S2 | 仓库提示注入不执行 | **PASS（lab）** | 批 8 canary；真实模型未测 |
| S3 | 仓库脚本零执行 | **PASS（lab）** | 批 8 |
| S4 | 拒绝/撤销/取消零发送 | **PASS** | 批 7/8 + 浏览器 |
| S5a | 密钥 canary 进入发送面 | **PASS** | 敏感/LFS/未授权排除 |
| S5b | canary 出现在日志/序列化/DB | **PASS（lab）** | 批 8；真实外发日志 NOT RUN |
| S6 | 恢复后证据不齐不判通过 | **PASS**（重启中断） | 批 7 |
| S7 | 取消后迟到结果 | **PASS** | 批 8/9 |
| S8 | Commit 丢失/不可验证 | **PASS** | 批 7 |
| S9 | 真实外发网络核对 | **NOT RUN** | 未调用真实 provider；无网络观测 |
| S10a | 文件/DB/审批/配置隔离（lab） | **PASS（lab）** | 批 8 探针 + 审批测试 |
| S10b | 实验账户/生产路径隔离 | **PASS（账户实测 + 生产 ACL 硬化）** | `project_read=PermissionError`、`production_isolation_pass=true`；项目 ACL 无 Allow Everyone/Users/AuthUsers；开发者写权限已修复 |
| S11a | manifest 外 canary | **PASS** | 批 8 对齐 |
| S11b | 真实外发 canary | **PASS（lab）**；真实 **NOT RUN** | 批 8 |
| S12a | 快照/核验篡改 | **PASS** | append-only/冻结触发器 |
| S12b | 归档内容寻址 | **PASS** | `verify_materialized` 测试 |
| S13 | Agent 直连审批接口 | **PASS** | 批 7 |
| S14a | 探针机制（允许/拒绝） | **PASS（lab）** | 批 8；缺 Deny/客体缺失即失败 |
| S14b | 实验账户启动探针 | **PASS（账户级）** | 第八轮 `self_check=passed/true`、`worker_isolation=verified`、`generate=passed`、`job=passed`；`verified=true`、`verification_errors=[]`、`cleanup_errors=[]` |
| S15 | Job Object 进程树/breakaway | **PASS（lab + 账户级）** | 第八轮 Job：`alive_before=true`、`child_in_job=true`、`alive_after=false`、`ok=true`；未穷举所有创建方式 |
| **S16（新增）** | **请求体 payload_digest** | **PASS（离线）** | `tests/test_payload_digest.py` 4 项：canonical bytes、字段变更、无 Key、worker body_file、审计持久化；`0006` 迁移 |

## 结论

- **payload_digest**：已把 manifest 摘要与完整 HTTP JSON body 摘要分开；同一字节序列
  由 transport/worker/审计共用；离线 PASS。
- **账户验证**：2026-10-22 已实测；5 项账户读写检查通过，但 S10b **FAIL**、S14b **FAIL**
  （受限探针未启动）。**不得**把当前用户/local 复现或本轮结果升级为隔离 PASS。
  项目根 Everyone 访问使生产 S10/S14 仍不通过。
- **账户级自测 PASS**：`verified=true`、`verification_errors=[]`、
  `self_check/generate/job=passed`、`cleanup_errors=[]`。
- **生产 S10b PASS**：`project_read=PermissionError`、
  `production_isolation_pass=true`；开发者写权限已复核。
- **整体隔离 PASS（本次测试范围）**；S9 真实 provider、S11b 真实外发仍
  **NOT RUN**，不声称真实外发门禁已解除。
- **S9** 仍 NOT RUN；真实调用门禁未解除。
- 账户创建/启动的本地脚本：`backend/scripts/create_adll_probe_account.ps1`；
  证据路径 `C:\ProgramData\ADLL-Account-SelfCheck\evidence.json`（用户执行后产生）。