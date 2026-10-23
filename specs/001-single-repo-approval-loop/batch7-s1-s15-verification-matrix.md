# 批 7 安全验收矩阵（S1～S15）

**Date**: 2026-10-21
**Scope**: ADLL V1.1 批 7（T033–T038）离线验收；依据
[quickstart.md §安全验收清单](./quickstart.md#安全验收清单阻断级s1s15r2-最终安全修订扩面)。
**Environment**: Windows 11；后端 Python 3.12.10 独立 venv；`ADLL_TESTING=1`；
Mock AgentAdapter；**未读取 `DASHSCOPE_API_KEY`，未发起任何真实百炼请求，未访问真实用户业务仓库**。
**性质**: 只记录本次实际执行/未执行的项目；单元/集成测试**不能**替代 OS 级或真实网络观测，
凡未做 OS 级验证的一律标 `NOT RUN`，不得据此宣称通过。

## 执行命令与结果（事实）

| 项 | 命令 | 结果 |
|---|---|---|
| 后端全量 | `backend/.venv/Scripts/python.exe -m pytest -q` | **138 passed**（含批 7 新增 19 项与离线 E2E 1 项），0 failed |
| 前端单元 | `frontend/npm test`（Vitest 1.6.1） | **8 passed**（`src/api/client.test.ts`） |
| 前端类型/构建 | `frontend/npm run build`（`vue-tsc -b && vite build`） | **成功**（50 modules；`dist/` 生成） |
| 离线 E2E | `tests/test_offline_e2e.py` | **PASS**（登录→关联→任务/需求→授权→Mock 生成→核验→批准→失效→撤销后拒绝） |

## S1～S15 判定

| # | 用例 | 判定 | 证据（本次实际执行） / 未覆盖边界 |
|---|---|---|---|
| S1a | Agent/组件经 HTTP 直写批准或绕过门禁 | **PASS** | `tests/test_approval.py::test_agent_subject_cannot_approve`（role 非 user → 403 + SecurityEvent）、`test_unauthenticated_rejected`（401）、`test_missing_csrf_rejected`（403）、`test_stale_version_rejected`（409，无事件）；DB append-only：`test_append_only_proposal_and_approval`、`tests/test_db_constraints.py::test_append_only_trigger` |
| S1b | Agent 进程在 OS 层直接写 DB/审批表 | **NOT RUN** | 需独立受限运行环境与 OS 观察；本批未创建该环境 |
| S2 | 目标仓库 README/规则/提示词注入不执行 | **NOT RUN** | 候选 C 无工具/指令通道，源码仅作为 payload 数据；但本批**未**用注入 canary 做端到端证据，不能宣称已验证 |
| S3 | 目标仓库构建/测试脚本 0 次执行 | **NOT RUN** | GitAdapter 仅执行白名单只读 git 命令（代码检查事实）；本批无 OS 进程观测证据 |
| S4 | 拒绝/撤销/取消后发送量为 0 | **PASS** | `tests/test_authorizations_api.py::test_revoked_authorization_blocks_generation_zero_send`（403 + 零执行）、`tests/test_generation.py::test_gate_denied_zero_send`、`tests/test_cancel_recovery.py::test_cancel_before_send_is_cancelled_without_send`（适配器调用 0 次）、`tests/test_offline_e2e.py`（撤销后 403 `outbound_denied`） |
| S5a | 密钥 canary 进入发送面 | **PASS**（自动化 manifest 层） | `tests/test_snapshot.py::test_sensitive_excluded`、`test_lfs_pointer_flagged`（LFS 指针显式排除 `lfs_pointer`）、`test_attribute_source_unavailable_fails_closed`（属性无法按 Commit 核验 → `attribute_verification_unavailable`，零文件）、`tests/test_generation.py::test_api_generation_testing_flow`（`.env`/`secret.txt` → `sensitive`，`other.txt` → `not_authorized`）、E2E 中 send-audit 源码仅 `a.txt` |
| S5b | 密钥出现在日志/方案/费用信息 | **NOT RUN** | 本批未做全量日志脱敏扫描；不得宣称已验证 |
| S6 | 恢复后证据不齐仍不判通过 | **PASS**（重启中断场景） | `tests/test_cancel_recovery.py::test_restart_recovery_marks_running_failed`（running → failed `restart_incomplete`，无 VerificationAttempt）、`tests/test_approval.py::test_restart_recomputes_validity`。注：未覆盖“哈希一致但四类证据不齐”的完整归档复核场景 |
| S7 | 取消后迟到结果 | **PASS** | `tests/test_cancel_recovery.py::test_cancel_after_send_is_not_cancelled_and_late_result_recorded`（`not_cancelled`、LateResultRecord `discard`、无 ProposalVersion）、`test_late_result_append_only` |
| S8 | 原绑定 Commit 丢失/不可验证 | **PASS**（适配器/基准层） | `tests/test_git_adapter.py::test_missing_commit_unavailable`、`tests/test_task_api.py::test_baseline_does_not_drift_on_head_change`；未做“删除真实仓库对象后经 API 全流程”的额外验证 |
| S9 | 真实外发网络核对（仅授权端点、与 SendAuditRecord 一致） | **NOT RUN** | 本批明确禁止真实百炼请求；无防火墙/代理观测。send-audit 结构已在 Mock 下验证（`tests/test_generation.py`、E2E），但不等于真实出站已核对 |
| S10 | 权限隔离穿透（工具/文件/命令/配置加载） | **NOT RUN** | 未建立隔离运行环境。相关门禁行为：`tests/test_mode_isolation.py::test_real_ai_enabled_but_isolation_unverified_blocks`、`tests/test_generation.py::test_isolation_unverified_blocks_before_send`（发送前阻断） |
| S11a | 敏感 canary 进入 manifest 之外入模内容（自动化） | **PASS**（manifest 层） | 同 S5a；`_assert_alignment`/五条件与 payload 对齐测试：`tests/test_outbound_pipeline.py` |
| S11b | 敏感 canary 真实外发、日志、费用信息 | **NOT RUN** | 无真实外发；无 OS/日志观测 |
| S12a | 快照/核验记录篡改被拒（append-only/终态冻结） | **PASS**（DB 约束层） | `tests/test_db_constraints.py::test_append_only_trigger`、`tests/test_approval.py::test_append_only_proposal_and_approval`、`tests/test_generation.py::test_terminal_freeze_and_verification_append_only`、`tests/test_migrations.py`（触发器存在性）。**不宣称**检测任意 DB 篡改 |
| S12b | 快照归档内容寻址 SHA-256 复核 | **NOT RUN** | 本批未实现/未验证归档重放复核；不得以 digest 长度断言替代 |
| S13 | Agent 直连审批接口（无会话/无 CSRF/角色伪造） | **PASS**（服务端层） | `tests/test_approval.py::test_agent_subject_cannot_approve`、`test_missing_csrf_rejected`、`test_unauthenticated_rejected`；CORS/Origin/前端按钮未作为唯一防线。注：伪造 Origin 的组合未单独测试 |
| S14 | 启动运行时权限探针（应拒绝/应允许客体） | **NOT RUN** | 真实适配器 `self_check()` 对真实 transport 返回 `ok=False`（隔离证据未实现）；系统按 fail-closed 拒绝发送，而非宣称探针已通过。见 `app/agents/dashscope.py`、`tests/test_mode_isolation.py` |
| S15 | Job Object 子进程逃逸 | **NOT APPLICABLE** | 候选 C（Messages API + 自建编排）无 Agent 子进程/Job Object；Claude Agent SDK 阶段 3 维持暂停、未执行。不可将“不适用”表述为“已通过” |

## 结论（本次可声称 / 不可声称）

- **可声称**：服务端审批与出站门禁、取消/迟到结果/重启恢复语义、撤销后零发送、
  敏感/未授权排除、append-only 与终态冻结、Mock 结果标识、生产 fail-closed，
  均有本次实际执行的自动化证据（138 项后端 + 8 项前端）。
- **不可声称**：S9/S10/S11b/S14 的 OS 级或真实网络验证，S2/S3 的注入与脚本执行观测，
  S12b 的归档哈希复核，S1b 的 OS 级 DB 写隔离，以及任何真实百炼外发/费用/隔离能力。
- **下一步前置**：独立受限运行环境 + 真实出站核对（S9/S10/S11/S14）通过后，才考虑首次
  正式模型调用；本批结束时真实发送仍默认关闭。