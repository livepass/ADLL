# 批 8 S1～S15 验证矩阵（更新版）

**Date**: 2026-10-21
**Supersedes**: [batch7-s1-s15-verification-matrix.md](./batch7-s1-s15-verification-matrix.md)（批 7 记录保留）
**Environment**: Windows 11；后端 Python 3.12.10；`ADLL_TESTING=1`（浏览器）；
受限 worker = 受限令牌 + DACL + Job Object；**无真实模型请求、无 API Key 读取、无真实业务仓库**。

## 执行结果（事实）

| 项 | 命令 | 结果 |
|---|---|---|
| 后端全量 | `backend/.venv/Scripts/python.exe -m pytest -q` | **156 passed** |
| 隔离专项 | `pytest tests/test_worker_isolation.py tests/test_worker_adapter.py tests/test_security_canary.py -q` | **15 passed** |
| 前端单元 | `frontend/npm test` | **8 passed** |
| 前端构建 | `frontend/npm run build` | **成功** |
| 浏览器（testing） | `scripts/browser_e2e.py --mode full ...` | 14 步全部 PASS（见浏览器证据） |
| 浏览器（生产 503） | `scripts/browser_e2e.py --mode 503 ...` | 7 步全部 PASS |

## S1～S15

| # | 用例 | 判定 | 本批证据 / 边界 |
|---|---|---|---|
| S1a | Agent/组件经 HTTP 直写批准或绕过门禁 | **PASS** | `tests/test_approval.py`（role/CSRF/未认证/stale/append-only）；批 7 证据保留 |
| S1b | Agent/worker 在 OS 层直接读写审批 DB | **PASS** | `tests/test_worker_isolation.py::test_probe_denies_repo_db_home_credential_and_allows_subset`：受限进程读 DB → `PermissionError`；写 DB → `PermissionError` |
| S2 | 仓库 README/规则/提示词注入不能变成执行指令 | **PASS**（离线） | `test_injection_text_is_data_not_command_and_repo_scripts_never_run`：注入文本仅进入 payload；无执行通道、无标记文件。未测试真实模型的提示注入鲁棒性 |
| S3 | 目标仓库构建/测试脚本零执行 | **PASS**（离线） | 同上：仓库 `run.bat` 未被调用；worker 仅运行自身固定脚本 |
| S4 | 拒绝/撤销/取消后发送 0 | **PASS** | 批 7 API/取消测试 + 浏览器 403 场景（撤销后生成 → `outbound_denied`，零发送） |
| S5a | 密钥 canary 进入发送面 | **PASS** | 敏感/LFS/未授权排除；`test_security_canary.py` 授权面仅 `a.txt` |
| S5b | 密钥 canary 出现在日志/序列化/DB | **PASS**（离线） | `test_security_canary.py`：canary 不在 caplog、worker job/result、SQLite 字节、worker env；真实外发日志仍未验证（S9） |
| S6 | 恢复后证据不齐仍不判通过 | **PASS**（重启中断场景） | `test_cancel_recovery.py::test_restart_recovery_marks_running_failed`；未覆盖完整归档四类证据复核 |
| S7 | 取消后迟到结果 | **PASS** | `test_cancel_after_send_is_not_cancelled_and_late_result_recorded`、`test_late_result_append_only`；worker 终止分支 `test_worker_termination_records_true_cancel_outcome`（`cancelled`/`not_cancelled` 由 `sent.marker` 决定） |
| S8 | 原绑定 Commit 丢失/不可验证 | **PASS**（适配器/基准层） | `test_git_adapter.py::test_missing_commit_unavailable`、`test_baseline_does_not_drift_on_head_change` |
| S9 | 真实外发网络核对 | **NOT RUN** | 未发起真实提供商流量；无防火墙/代理观测。worker 代码约束固定端点/禁代理/禁重定向/单次请求，但不等于 OS 级已核对 |
| S10 | 运行时越权读写、审批越权、配置加载隔离 | **PASS**（离线） | 探针：原仓库/DB/用户目录/凭据读写拒绝、子集允许；审批越权沿用批 7 测试；worker 仅标准库、最小环境、无仓库/DB 路径。OS 出站部分见 S9（NOT RUN） |
| S11a | 敏感 canary 进入 manifest 之外入模内容 | **PASS** | 同 S5a；manifest 对齐测试保留 |
| S11b | 敏感 canary 真实外发/日志/费用信息 | **PASS**（离线） | 日志、job/result、DB 字节均无 canary；真实外发未执行（S9） |
| S12a | 快照/核验记录篡改被拒 | **PASS** | append-only/终态冻结触发器测试；`verification_no_update`/`verification_no_delete` |
| S12b | 归档内容寻址复核 | **PASS** | `tests/test_snapshot.py::test_materialized_archive_tamper_detected`：内容篡改/缺失/清单外文件均被 `verify_materialized` 检出 |
| S13 | Agent 直连审批接口 | **PASS** | 批 7：role/CSRF/未认证组合均拒绝并记安全事件；CORS/Origin/前端按钮未作为唯一防线 |
| S14 | 运行时权限探针（应拒绝/应允许） | **PASS** | `test_worker_isolation.py` + `test_worker_adapter.py::test_self_check_is_evidence_based`；缺 Deny/客体缺失 → `self_check` false；`generate` 在探针失败时 `AdapterDisabled`（零发送） |
| S15 | Job Object 子进程逃逸 | **PASS** | 受限 worker 为独立进程 → 本项**适用**；`test_job_object_kills_worker_child_tree`：关闭 Job 后 worker + 子进程均终止；未设置 breakaway 标志；显式取消经 Job 终止 worker（`Sandbox.cancel`）。未穷举所有子进程创建方式 |

## 结论

- **本批可声称**：Windows 受限令牌 + DACL 的读取/写入隔离、Job Object 进程树终止、
  探针 fail-closed、canary 不进入日志/序列化/DB、归档篡改检测、浏览器完整离线闭环
  及 401/403/409/423/503 页面反馈，均有实际执行证据。
- **仍不可声称**：真实提供商外发/费用/网络白名单（S9），真实模型提示注入鲁棒性，
  真实用户目录/仓库 ACL 隔离（本批禁止修改）；生产启用前须完成独立受限环境与真实出站验证。