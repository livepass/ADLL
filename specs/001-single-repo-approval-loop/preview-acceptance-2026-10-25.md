# V1.1 Preview 实际验收与最小修复

**日期**：2026-10-25　**基线**：`956c611`（本地 HEAD = origin/main = 远端 main）
**性质**：本地离线验收与修复；**未 Commit / 未 Push**。

## 1. 执行前检查

| 项 | 值 |
|---|---|
| HEAD / origin/main / 远端 | 均为 `956c6119ea7161d38565c15ab3fd69cfca1db299` |
| 未提交修改 | 无（仅 `.specify/` 未跟踪） |
| 后端启动 | `uvicorn app.main:app`（`ADLL_TESTING=1`、`ADLL_REAL_AI_ENABLED=0`） |
| 前端启动 | `npm run dev`（Vite，`/api` 代理到 `127.0.0.1:8000`） |
| 迁移 | 独立 DB 上 `alembic upgrade head` → `0013` |
| 测试环境 | 合成仓库 `D:/wo/code/ADLL/.tmp-preview/repo`（1 次提交）、独立 SQLite、测试口令 |
| 真实资源 | 未读取真实 Key、未访问真实业务仓库、未调用百炼 |

## 2. 浏览器实测（12 步，全部实际执行）

工具：Playwright + 系统 Chrome（headless），视口 1440×1500。截图目录：
`D:/wo/code/ADLL/.tmp-preview/shots2/`

| # | 步骤 | 结果 | 证据 |
|---|---|---|---|
| 1 | 登录并关联合成仓库 | **PASS** | `01-login.png`、`02-repo-linked.png`；`200 POST /api/auth/login`、`200 POST /api/repositories/link` |
| 2 | 核对完整 Commit SHA | **PASS** | `03-baseline.png`；页面显示 `2ebc5aed9074d7401fc90dc9b9cc87bee6c49482`，与 `git rev-parse HEAD` 完全一致（未截断） |
| 3 | 创建任务并保存正式需求 v1 | **PASS** | `04-requirement-v1.png`；`200 POST /api/tasks`、`200 PUT /api/tasks/1/requirement`；页面显示「当前 v1」+ content_hash |
| 4 | 创建 `mock://local` 出站授权 | **PASS** | `05-authorization.png`；`200 POST /api/tasks/1/outbound-authorizations`；页面显示 `#1 approved receiver=mock://local` |
| 5 | 预览完整请求（不发送） | **PASS** | `06-preview.png`/`06-preview.txt`；`200 POST .../generations/preview`；含请求摘要与文件范围 `src/calc.py` |
| 6 | 人工确认并生成 Mock 方案 v1 | **PASS** | `07-v1-generated.png`；`202 POST .../generations`；execution=1 `completed`、provider=`mock` |
| 7 | 查看执行状态 / 核验 / 出站审计 | **PASS** | `08-audit.png`；核验 `verified`，审计含 `confirmed_sent` 与 `payload_digest` |
| 8 | 提交对 v1 的修改意见 | **PASS** | `09-feedback.png`；`200 POST .../proposals/1/feedback`；页面提示「意见已记录」 |
| 9 | 再生成 Mock 方案 v2（手动确认） | **PASS** | `10-v2-generated.png`；再次 `preview` + `201/202 generations`；v2 内容含反馈 |
| 10 | v1 不被覆盖、v2 不继承旧审批 | **PASS** | `11-both-versions.png`；v1/v2 同时存在，`content_hash` 不同（`7ff3bba5` vs `21e9d790`）；v1 无「已批准」 |
| 11 | 批准或驳回 | **PASS** | `12-approved.png`；`200 POST .../proposals/2/approve`；v2 显示「当前版本 / 已批准且有效」 |
| 12 | 刷新 + 重启应用后复核 | **PASS** | `13-after-reload.png`、`14-after-restart.png`；重启后 v1/v2/审批/反馈内容/mock 标识/审计全部保留 |

**断言汇总**（脚本输出，`results.json`）：20/20 为 True，包括 `step2_sha_match`、
`step5_has_digest`、`step5_has_scope`、`step7_verified`、`step7_audit`、`step8_feedback_recorded`、
`step9_feedback_in_content`、`step10_v1_still_present`、`step11_approved`、`step12_*`。

**写操作状态码**（共 82 个 API 请求，9 类写操作）：

```text
200 POST /api/auth/login
200 POST /api/repositories/link
200 POST /api/tasks
200 PUT  /api/tasks/1/requirement
200 POST /api/tasks/1/outbound-authorizations
200 POST /api/tasks/1/generations/preview
202 POST /api/tasks/1/generations        （异步受理，轮询至 completed）
200 POST /api/tasks/1/proposals/1/feedback
200 POST /api/tasks/1/proposals/2/approve
```

## 3. 四个已知问题的复现与处置

| 问题 | 复现结果 | 是否阻断 | 处置 |
|---|---|---|---|
| **A** `submit_feedback()` 不自动再生成 | 确认：返回 `available=False, reason=real_adapter_unavailable`，页面明确提示「需要新版本=是，但当前不可自动生成；不会伪造新版本」 | **不阻断** | **不修改**。符合「优先手动确认再生成、不引入自动发送」；UI 已如实告知，用户手动「预览 → 确认生成」可完成闭环（步骤 9 已实测） |
| **B** `MockAgentAdapter.generate()` 忽略 `feedback_texts` | **确认且阻断**：v1/v2 `content_hash` 完全相同（`7ff3bba5…`），v2 是 v1 的复制品，闭环无意义 | **阻断** | **已修**：输出纳入反馈并标注 `MOCK_FEEDBACK_APPLIED（合成，非真实模型）`；无反馈时输出格式不变（不破坏既有断言） |
| **C** previewGate 指纹未覆盖正式需求 | 确认：`GateInput` 仅含 taskId/authorizationId/feedback，需求变更后旧预览仍可确认 | **阻断（安全语义）** | **已修**：指纹加入 `requirement`，`GenerationPanel` 传入当前正式需求内容；需求变更 → 预览 dirty、摘要不可用 |
| **D** 测试模式不校验已提供的 `preview_digest` | 确认：`if not testing:` 整段跳过，提供的错误摘要被忽略 | **阻断（安全语义）** | **已修**：测试模式「未提供可放行、提供则必须匹配」，不匹配 → `preview_digest_mismatch` |

## 4. S9 定向审核（`_revocation_race` / `settle` / §6.2.1）

### 4.1 发现：`authorization_missing` 曾 fail-open（已修）

`settle` 原只处理 `revoked_before_issue` / `revoked_after_issue`；
`_revocation_race` 返回的 `authorization_missing`（授权记录缺失）与
`issued_at_invalid`（签发时间不可解析）**没有分支**，会径直落到
`finish_attempt(confirmed_sent)` —— 即「查不到授权 → 默认放行」。

**已修**（fail-closed）：两者与 `revoked_before_issue` 同列，均不得升格 `confirmed_sent`，
落 `possibly_sent` + `error_code=<race>` + `revocation_race` 证据。

最小测试：
- `test_settle_fails_closed_when_authorization_missing`
- `test_settle_fails_closed_when_issued_at_unparseable`

### 4.2 发现：发送事实与授权有效性存在语义混淆（**仅建议，未改**）

当前 `revoked_before_issue` 落 `possibly_sent`，把「授权无效」表达成「可能没发出去」。
实际上收据已证明**确实发送**（`confirmed_sent` 是发送事实），而问题是**授权无效**。
降级 phase 会低估发送事实，导致审计失真（漏报已发送）。

因为 `confirmed_sent` 的语义属已批准契约，**本轮不擅自修改**，仅提出建议：

| 建议 | 内容 |
|---|---|
| C-1 | 增加独立字段 `authorization_violation`（值：`revoked_before_issue` / `authorization_missing` / `issued_at_invalid`），与 `phase` 正交 |
| C-2 | `phase` 保持发送事实（`confirmed_sent`），违规只体现在该字段 + 证据表 |
| C-3 | §6.2.1 增一句：「撤销竞态的处置不得降低已发生的发送事实，违规与事实分列记录」 |
| C-4 | 若维持现状（降级 `possibly_sent`），须在契约中显式声明「此处 phase 表示可接受性而非发送事实」，避免读者误解 |

迁移成本：C-1 需新增列（迁移 0014）；C-4 仅文档。建议按 C-4 先行（零代码），后续版本再评估 C-1。

## 5. 测试与构建结果

| 范围 | 结果 |
|---|---|
| 后端全量 `pytest -rs` | **352 passed / 0 failed / 0 skipped** |
| `test_s9_chain.py` | 36 passed（34 + 2 fail-closed） |
| `test_agent_mock.py` | +2（反馈生效 / 无反馈不变） |
| `test_generation.py` | +2（测试模式摘要不匹配拒绝 / 匹配放行） |
| 前端 Vitest | **22 passed**（20 + 2：需求指纹 / 需求变更使预览失效） |
| 前端 `npm run build` | 成功 |
| ruff（本轮改动文件） | 通过（9 个既有告警不在改动范围） |
| 数据库迁移 | 从零 `0001→0013` 通过（独立测试库） |

## 6. 代码修改清单

| 文件 | 变更 | 目的 |
|---|---|---|
| `backend/app/agents/mock.py` | 输出纳入 `feedback_texts`，加 `MOCK_FEEDBACK_APPLIED` 标注 | 问题 B |
| `backend/app/services/generation_service.py` | 测试模式下「提供摘要必须匹配」 | 问题 D |
| `frontend/src/state/previewGate.ts` | `GateInput` 增 `requirement`，指纹覆盖需求 | 问题 C |
| `frontend/src/components/GenerationPanel.vue` | 传入 `props.requirementContent` | 问题 C |
| `backend/app/services/s9_chain.py` | `authorization_missing` / `issued_at_invalid` fail-closed | S9 审核 |
| `backend/tests/test_agent_mock.py` | +2 | 回归 |
| `backend/tests/test_generation.py` | +2 | 回归 |
| `backend/tests/test_s9_chain.py` | +2 | 回归 |
| `frontend/src/state/previewGate.test.ts` | +2 | 回归 |

## 7. V1.1 Preview GO / NO-GO

| 判定 | 结论 | 依据 |
|---|---|---|
| 需求 → Mock v1 → 反馈 → Mock v2 → 人工审批 → 历史恢复 闭环 | **GO** | 12 步浏览器实测全 PASS；v2 与 v1 内容/hash 不同且含反馈；仅 v2 获批；重启后数据完整 |
| Preview 作为「可操作」产品形态 | **GO（本地/测试模式）** | 界面明确标注 Mock 合成、不调用外部 AI |
| Preview 作为「真实 AI 可用」 | **NO-GO** | 真实发送仍默认关闭；Mock 为合成替身，不代表模型能力 |
| 生产安全验收 | **NO-GO** | S9-3B 阻断未解（见前序 `s9-3b-readiness.md` §6） |

## 8. 边界确认

未发起真实 AI 请求、未创建 VM、未修改 ACL/防火墙、未修改 ADLL-Knowledge、未 Commit/Push。
测试期间安装的 Playwright 仅用于本地浏览器验收，未进入项目依赖清单。
