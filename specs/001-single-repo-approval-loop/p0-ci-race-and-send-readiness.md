# P0 CI 竞态修复与真实发送前最终收口

**日期**：2026-10-23
**基线提交**：`7c43bf3`（GitHub `livepass/ADLL` main）
**边界**：未 Commit/Push、未调用真实百炼、未读取 Key、未安装系统组件、
未修改生产 ACL/防火墙、未访问真实业务仓库、未修改 ADLL-Knowledge。

## 1. 本轮结论

| 项 | 结果 |
|---|---|
| CI 后端唯一失败（`test_offline_end_to_end_mock_workflow`） | **已定位并修复**：执行终态与核验记录不在同一事务 |
| 预览/确认分离 | **已实现**：两步按钮 + 指纹失效 + 服务端摘要复核 |
| 重启后悬空发送尝试 | **已实现**：补记 `possibly_sent`，不改写、不伪造 |
| 后端全量 | 见 §5 |
| 前端 `npm test` / `build` | **17 passed（3 文件）** / 成功 |

## 2. A. 执行终态与核验的提交边界

### 2.1 根因（可复现，不依赖时序）

`_run_body()` 原先的顺序是：

```text
db.commit()                       # ① execution.status = completed   ← 先暴露
verification.verify(...)          # ② 纯计算
db.add(VerificationAttempt); db.commit()   # ③ 核验记录后写
```

CI 上 `test_offline_e2e` 轮询到 `completed` 后立即读 `verification`，正好落在
① 与 ③ 之间 → `verification is None` → `TypeError`。本地因调度差异未命中，
属于典型**读侧可见性竞态**，不是环境问题。

### 2.2 修复

`backend/app/services/generation_service.py::_run_body`

- 先计算核验（纯函数，不写库），再**同一事务**写入
  `VerificationAttempt` + `ProposalVersion` + `execution.status=completed`，
  最后只 `commit()` 一次。读侧要么看到 `running`，要么看到
  `completed + 核验 + 方案`，不存在中间态。
- 核验抛异常 → `rollback()` → `failed / verification_error:<Exc>`，
  不再留下 `completed`。
- 最终提交失败（如并发 seq 冲突）→ `rollback()` → `failed /
  verification_persist_error:<Exc>`，执行不会停在 `completed`。
- 证据不足时行为不变：仍写 `unconfirmed` 核验记录、不建方案，不强行 `verified`。
- 取消/迟到结果分支保持原样（发送已发生时 `not_cancelled` + discard）。

### 2.3 负向与并发测试（`backend/tests/test_generation_consistency.py`）

| 测试 | 机制（无 sleep） |
|---|---|
| `test_completed_never_visible_before_verification_is_persisted` | 在 `verification.verify()` 内部用**独立会话**读取已提交状态，断言 `running` 且核验数 0 |
| `test_verification_exception_leaves_failed_state` | 注入 `RuntimeError` → `failed`、零核验、零方案、审计仍为 `prepared+confirmed_sent` |
| `test_persist_failure_rolls_back_completion` | 核验后置位标志，令下一次 `commit()` 抛错 → 回滚为 `failed`，零核验/零方案 |
| `test_detail_flags_legacy_completed_without_verification` | 历史 `completed` 无核验 → API 返回 `verification_missing=true` |

验证方式：把 `generation_service.py` 临时回退到修复前版本，第一个测试
**确定性失败**（观测到 `status=completed`、核验数 0），恢复后通过。
因此该测试确实能拦住本类回归，而不是靠时间窗。

### 2.4 历史数据（不篡改终态）

`generation_executions` 有数据库触发器 `execution_terminal_freeze`，终态不可改。
因此对“修复前写入的 completed 且无核验”不做回写，而是：

- `GET /api/generations/{id}` 返回 `verification_missing=true`；
- 前端在该状态下显示错误提示，且 `approval_service._checks()` 本就要求
  最新核验 `verified + sufficient`，这类执行无法被批准。

## 3. B. 预览与确认分离

### 3.1 后端：预览必须能逐字核对

`POST /api/tasks/{id}/generations/preview` 现在返回：

| 字段 | 说明 |
|---|---|
| `receiver` / `model` | 实际接收端点与模型（端点来自适配器 `capabilities()`） |
| `data_types` | 从最终请求独立计算的数据类型 |
| `request_digest` | 完整 HTTP 请求体 SHA-256 |
| `message.content` | **最终写入请求体的同一条 message**（逐字） |
| `requirement.content` | 需求原文 |
| `feedback[].content` | 每条反馈原文 |
| `source[].content` | 每个源码文件实际发送内容 + sha256 + bytes |
| `snapshot.*` | 快照摘要、进入请求的文件、排除项、属性提示 |
| `testing` | Mock 合成标识 |

`_prepare()` 在真实模式仍独立校验：`preview_digest` 缺失 → `preview_required`；
与**重新读取仓库后**重算的 `request_digest` 不一致 → `preview_digest_mismatch`。
所以预览后源码/需求/反馈任何变化都会被服务端拒绝，而不是只靠前端自觉。

### 3.2 前端：两个独立动作

`frontend/src/state/previewGate.ts` + `GenerationPanel.vue`：

- 「① 预览待发送内容」只调用 preview，**不会**发送；
- 「② 确认发送」在 `gate.fresh === false` 时禁用；`gate.consume()` 只在
  指纹一致时返回摘要，杜绝“自动取 digest 后直接发送”；
- 指纹 = `taskId + authorizationId + 反馈逐行归一化`；修改反馈、切换任务或
  授权 → `dirty=true`，界面提示“原预览确认已失效”，必须重新预览；
- 发送成功或服务端返回 `preview_digest_mismatch` → `gate.reset()`，旧确认作废；
- 新增 `OutboundPreview.vue` 统一渲染接收方、模型、数据类型、请求 SHA-256、
  快照 SHA-256，以及**可滚动的完整正文**（message / 需求 / 每条反馈 / 每个文件），
  不再只给哈希；
- Mock 模式：面板横幅、预览内 chip、按钮文案三处显式标注“Mock 合成”。

### 3.3 前端测试（`npm test` 共 17 passed）

- `src/state/previewGate.test.ts`（4）：反馈拆分、指纹随任务/授权/反馈变化、
  未预览不可消费摘要、修改反馈后必须重新预览。
- `src/components/GenerationPanel.test.ts`（5，jsdom + `@vue/test-utils`）：
  1. 预览后**未**调用发送；发送按钮此时才可用；正文与模型可见；
  2. 修改反馈 → 发送按钮禁用且点击无效；
  3. 切换 `taskId` → 旧确认失效；
  4. 服务端 `preview_digest_mismatch` → 提示并作废预览；
  5. 一次成功发送后必须重新预览。
- `src/api/client.test.ts`（8）保持通过。

## 4. C. 重启后的发送审计恢复

`generation_service.reconcile_orphan_attempts()`：

- 找出只有 `prepared`、没有终态的尝试；
- 若所属执行仍在 `running`（本进程仍在处理）→ 跳过；
- 否则**追加**一行 `possibly_sent`，`error_code=restart_unconfirmed`；
- 不改写原 `prepared` 行，不删除，不补 `confirmed_sent`/`not_sent`；
  本地无法证明请求是否写出网络，因此只给“可能已发送”；
- 已有终态的尝试不重复终结；重复调用幂等。

`reconcile_after_restart()` 先按原逻辑把遗留 `running` 置
`failed / restart_incomplete`，再调用上述函数；`main.create_app()` 启动时执行。

测试（同文件）：孤立尝试补记、幂等、已有终态不重复、`running` 执行不被截断。
迁移未变（仍为 `0007`），`send_audit_records` 无新增列。

## 5. 回归与复现

| 项 | 命令 | 结果 |
|---|---|---|
| 定向（先跑失败用例） | `pytest tests/test_offline_e2e.py::test_offline_end_to_end_mock_workflow -q` | **1 passed** |
| 后端全量 | `pytest tests -q`（`CODEBUDDY_SAFE_DELETE_ENABLED=0`） | **256 passed**（1187.11s） |
| 干净副本（排除 `.venv`/`.git`/staging） | 5 个受影响文件 | **42 passed**（109.47s） |
| 前端单测 | `npm test` | **17 passed**，3 个文件 |
| 前端构建 | `npm run build`（`vue-tsc -b`） | 成功 |
| 迁移 | `alembic upgrade head`（空库） | `0001→0007`，`alembic_version=0007`，无新迁移 |
| 依赖锁 | `npm ci --dry-run` | 通过 |

说明：

- 本地全量包含仓库外的 `backend/staging-account-ast-20261023` 候选目录，因此
  `test_account_script_ast_guard` 中 2 项 staging 断言会实际执行；CI 干净检出会
  `skip`（该行为是本轮之前刻意保留的）。
- 前端测试脚本改为 `vitest run --no-file-parallelism`。原因：本机（WorkBuddy
  文件代理）在并发写 vitest 的 `ssr/<hash>` 临时缓存时偶发
  `EPERM: operation not permitted`，会导致某个测试文件未执行却只报
  “Unhandled Error”。串行后连续 3 次 `npm test` 均为 **17 passed / 无错误**；
  3 个测试文件规模很小，串行开销可忽略。CI 不受该代理影响，但保持同一脚本
  以确保本地与 CI 行为一致。
- 迁移未变更：本轮没有新增列，`send_audit_records` 仍为 12 列。

## 6. 未解决 / 仍需人工

1. **GitHub Actions 需推送后复跑**：本轮只做本地同构验证。
2. CI 现在会在 Windows runner 上跑全部测试（含受限 worker），首次推送后
   需确认 Job Object/DACL 用例在 GitHub 托管的 Windows 上同样成立。
3. 真实 provider（百炼）仍未启用，`S9`/`S11b` 仍为 NOT RUN。
4. 许可证仍未选择。
5. `AGENTS.md` / `CLAUDE.md` 引用的 `.specify/memory/constitution.md`
   仍未跟踪（需人工批准是否公开）。
