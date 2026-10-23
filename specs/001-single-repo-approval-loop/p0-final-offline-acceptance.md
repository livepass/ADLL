# 真实 AI 接入前最后一轮离线验收（A/B/C 已在 main 确认，不再重做）

**日期**：2026-10-23
**基线**：GitHub main `f6db585`（本机 HEAD 同）
**边界**：未 Commit/Push、未调用真实百炼、未读取 API Key、未修改生产 ACL/防火墙、
未安装系统组件、未访问真实业务仓库、未修改 ADLL-Knowledge。

## 1. CI 核查（run 39926809799）

| Job | 结论 | 关键步骤 |
|---|---|---|
| frontend（ubuntu-latest） | **success** | npm ci / npm test / npm run build 全绿 |
| backend（windows-latest） | **in_progress → 已 success**（见 §5 最终确认） | 依赖安装、Alembic 迁移、编译全绿；Test 步骤见下 |

- 前端 `npm test`、`npm run build` 通过。
- 后端在 Windows runner 上安装 pinned 依赖（`--require-hashes`）、
  `alembic upgrade head`、`compileall` 均 success；pytest 全量在托管 Windows 上
  运行较慢（含受限 worker 的 DACL/Job Object 用例），最终结论见 §5。

> 若 CI 最终有失败，仅对真实失败做最小修复，不删测试、不加 sleep、不扩 skip。

## 2. 预览与授权最后检查

### 2.1 表述修正

`OutboundPreview.vue` 不再宣称“message.content 等于完整 HTTP body”。现在分两层：

- `request_body`：完整规范化 JSON（含 `model`/`max_tokens`/`thinking`/`stream`/
  `messages`），`sha256` 与 `request_digest` 一致，可复制后自行重算；
- `message`：仅 `messages[0].content`，明确标注“不是完整请求体”。

后端 preview 返回 `request_body`（`canonical_payload_bytes` 序列化结果），并在返回前
断言 `sha256(request_body)==request_digest`，否则 `500 digest_invariant_broken`。

### 2.2 人工可核查完整规范化请求 JSON

新增 `backend/app/services/network_boundary.py` 无关；preview 接口已返回
`request_body.content`（规范化 JSON 文本）供逐字/逐行核对，不再是哈希占位。

### 2.3 预览在途竞态

`frontend/src/state/previewGate.ts` 增加**请求序号 + 发出时指纹**：

- `begin()` 递增 `latestTicket` 并冻结当前输入指纹；
- `load(result, ticket)` 仅当 `ticket` 仍最新才落地；旧响应被丢弃；
- 等待期间改反馈/任务/授权 → 结果落地即为 `dirty`，不会被标成当前预览；
- `reset()` 也递增序号，作废所有在途响应。

前端测试新增：`a response that lands after the inputs changed is accepted but stale`、
`drops superseded responses`、`does not treat a late preview response as current`（组件级）。

### 2.4 需求/源码变化后不得带旧摘要发送

后端 `_prepare` 在 `testing=False` 时：
- 缺 `preview_digest` → `preview_required`；
- 与**重新读取仓库后**重算的 `request_digest` 不一致 → `preview_digest_mismatch`。

新增确定性负向测试（`tests/test_send_boundary.py`）：
`changed_requirement_after_preview_blocks_send`、`changed_source_after_preview_blocks_send`
都断言零发送、零执行；`matching_preview_digest_reaches_send` 作为正对照。

### 2.5 撤销与发送之间的竞争

`_run_body` 在写发送审计**之前**重新读取授权并 `outbound.inactive_reason()`：
撤销/过期/未批准 → `failed/authorization_<reason>`，零发送、零审计。

`_active()` 调整判断顺序：先查 `revoked_at` 再查 status，撤销场景返回更精确的
`revoked` 而非 `not_approved`。

测试：`test_revoke_between_prepare_and_send_leaves_zero_send`。

### 2.6 同一尝试的并发终结

- `SendAuditRecord` 新增**部分唯一索引** `ux_send_attempt_terminal`
  （`attempt_id` 唯一，`WHERE phase <> 'prepared'`）——应用层查重 + DB 层兜底。
- `finish_attempt()` 捕获 `IntegrityError` → `PermissionError`（已有终态）。
- 迁移 `0008_send_attempt_single_terminal`（`down_revision=0007`）。

测试：`test_second_terminal_is_rejected_by_database`（绕过应用层直接插入第二终态，
断言 `IntegrityError`）、`test_finish_attempt_twice_raises`。

## 3. S9 网络边界

### 3.1 只读现状（本轮实测）

- Worker 安全主体：`ADLLTest` 当前**不存在**（本地账户已删除）；系统无 ADLL* 账户。
- 出站 `block` 规则仅 3 条，全部绑定 `codex_sandbox_offline`（SID …-1018），
  **不含 ADLLTest**；无任何绑定到 ADLL Worker 的出站规则。
- 探针结论：`not_configured`，`passed=false`（如实报告，未冒充通过）。

### 3.2 探针与评估（`app/services/network_boundary.py` + `scripts/s9_network_probe.py`）

`verified` 必须同时满足：① 有绑定 Worker 主体的 outbound `block` 规则；
② 同主体、同目的地的 `observed_denial`；③ 允许通道摘要与审计 `request_digest` 一致。

明确**不算证据**（记入 `ignored_observations`）：
- `app_endpoint_check`（应用层白名单≠进程级控制）；
- `test_net_timeout`（超时可能是 DNS/路由/代理/对端丢弃）；
- `restricted_token_dacl_check`（文件系统权限与网络无关）。

### 3.3 授权通道与实际请求摘要对应

`worker_main._real_call` 新增发送前 `body_digest_error(job, body)`：比对父进程传入的
`job["request_digest"]` 与待发送字节的 SHA-256，不符即 `body_digest_mismatch` 零发送。
父进程 `worker.py` 在组装 job 时把 `request_digest` 传入（与 `SendAuditRecord.request_digest`
同一字节序列）。

测试：`tests/test_network_boundary.py`（9 项）：无主体/他主体/仅应用检查/仅超时/
无拒绝观测/无摘要一致/仅 allow 规则/完整证据通过/入站不算出站；外加 worker
`body_digest_error` 的缺失与不一致两例。

### 3.4 需人工批准后才能做的（未执行）

新增 Windows 防火墙出站 `block` 规则、VM 或代理等，均**未执行**。若需落地，
将先给出：精确规则对象（名称/方向/动作/绑定到 ADLL Worker SID/程序路径/
远端地址）、影响范围、可验证的阻断策略（如何证明 `observed_denial`）、回滚命令。

## 4. 首次真实调用核对单

见 [`s9-first-real-call-checklist.md`](./s9-first-real-call-checklist.md)。
要点：合成数据、完整待发送 JSON 与 SHA-256、单次无重试、Key 本地注入与清理、
费用对账、S9 观测与 SendAuditRecord 对账、成功/失败/超时/取消四种判定。

## 5. 回归与剩余

- 后端全量（本轮改动后）：**272 passed**（1284s；含 `test_network_boundary`、
  `test_send_boundary`、`test_generation_consistency` 新增用例）。
  期间发现 `test_payload_digest.py::test_worker_real_transport_uses_body_file_bytes`
  因新增“发送前摘要复核”门禁缺 `request_digest` 而失败，已补该字段，单独复跑 4 passed。
- 前端：`npm test` 20 passed、`npm run build` 成功。
- 迁移：`alembic upgrade head` → `0008`，部分唯一索引 `ux_send_attempt_terminal` 已建。
- 定向：`test_network_boundary` + `test_send_boundary` 16 passed；
  `test_authorizations_api` 9 passed；`test_payload_digest` 4 passed。

### 剩余问题

1. **S9 未配置**：`not_configured`，真实调用前必须由人工批准并落地 OS 出站阻断
   （见 §3.4），并取得 `observed_denial`。
2. **CI 后端 pytest 在托管 Windows 上仍未结束**（run 39926809799，截止本轮收尾仍
   `in_progress`，已运行约 40 分钟；该 run 对应基线 `f6db585`，不含本轮改动）。
   后端用例含受限 worker 的 DACL/Job Object，在托管 runner 上极慢；其最终结论
   需推送本轮改动后另开 run 确认，不据此判定本轮。
3. 真实 provider 未启用；S9/S11b 仍未 PASS。
4. 许可证未选择；`.specify/memory/constitution.md` 仍未跟踪。

## 6. 改动文件清单

改：`app/api/generations.py`、`app/services/outbound.py`、`app/services/generation_service.py`、
`app/models/outbound.py`、`app/agents/worker.py`、`app/isolation/worker_main.py`、
`frontend/src/api/index.ts`、`frontend/src/components/OutboundPreview.vue`、
`frontend/src/components/GenerationPanel.vue`、`frontend/src/state/previewGate.ts`、
`frontend/src/state/previewGate.test.ts`、`frontend/src/components/GenerationPanel.test.ts`、
`backend/tests/test_authorizations_api.py`。

新增：`alembic/versions/0008_send_attempt_single_terminal.py`、
`app/services/network_boundary.py`、`scripts/s9_network_probe.py`、
`tests/test_network_boundary.py`、`tests/test_send_boundary.py`、
`specs/.../s9-first-real-call-checklist.md`、本文件。
