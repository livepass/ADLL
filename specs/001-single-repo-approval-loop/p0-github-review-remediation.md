# GitHub 审核后 P0 修复记录

**日期**：2026-10-23
**范围**：仅本地源码与离线测试。未调用百炼、未读取 API Key、未修改 Windows ACL/防火墙、
未访问真实用户业务仓库、未修改 ADLL-Knowledge、未 Git Commit/Push。

## 1. 具体缺陷（修复前）

| ID | 位置 | 现状 | 风险 |
|---|---|---|---|
| P0-1 | `api/generations.py::_materialize_sources` | `paths = (auth.send_scope or {}).get("paths")`；`send_scope={}` → `paths=None` → `materialize(authorized_paths=None)` 表示不过滤 | 空范围把仓库全部文本文件纳入发送 |
| P0-2 | `api/generations.py::start_generation` | `data_types=list(auth.data_types)` 传给门禁 | 用授权记录验证自己，真实发送类型从未计算 |
| P0-3 | 同上 | `receiver=auth.receiver` | 接收方自证，未校验适配器真实端点 |
| P0-4 | `services/generation_service.py::_run_body` | `outbound.record_send` 在 `adapter.generate` 成功后才调用 | 超时/HTTP 错误/取消无审计；发送前无留痕 |
| P0-5 | `models/outbound.py::SendAuditRecord` | 只有一条“已发送”记录 | 无法区分“准备发送/可能已发送/确认发送” |
| P0-6 | `services/generation_service.py` | `status = "verified" if testing else "unconfirmed"` | 真实模式永远无法产出可审批方案；核验写死 |
| P0-7 | 前端 `AuthorizationPanel.vue` / 授权 API | “留空表示按默认范围”；授权允许 `send_scope={}` | 把 P0-1 暴露为正常操作 |
| P0-8 | `tests/test_account_script_ast_guard.py` | 依赖未提交的 `backend/staging-account-ast-20261023` | 干净检出必然失败 |
| P0-9 | 仓库根 | 无 README/LICENSE/CI；迁移止于 0006 | 公开仓库无法从零复现 |

## 2. 修复内容

### 2.1 发送授权（P0-1/2/3/7）

- `services/outbound.py`
  - `scope_paths()`：只接受 `{"paths": [...]}`；拒绝绝对路径、`..`、盘符；`{}` 或缺失 `paths`
    视为**空白名单**，不再等于“全部源码”。
  - `evaluate()`：空白名单 → `scope_required`；实际路径必须是授权路径的子集；
    `source` 类型但无路径 → `source_scope_required`；裸标签 receiver → `receiver_unverifiable`。
  - `valid_receiver()`：必须是 `scheme://...` 的完整端点。
- `services/outbound_pipeline.py`
  - `actual_data_types()`：从最终请求（requirement/feedback/source/tool_return）独立计算。
  - `prepare()` 删除 `data_types`/`scope` 入参，内部生成实际 scope；manifest 必须与
    `source_items` 的 path+sha256 完全一致。
- `services/generation_service.py`
  - `actual_receiver(adapter)`：从 `adapter.capabilities()["endpoint"]` 读取真实端点；
    Mock 声明 `mock://local`。
  - 生产模式必须回传预览摘要，否则 `preview_required`；不一致 `preview_digest_mismatch`。
- `api/authorizations.py`：创建授权时校验端点、数据类型与 scope（source 必须非空 paths；
  未授权 source 不得带 paths；拒绝 `tool_return`）。
- `api/generations.py`：新增只读 `POST /tasks/{id}/generations/preview`，返回
  接收端点、实际数据类型、request_digest、snapshot_digest、逐文件 path/sha256/bytes 与排除项。
- `frontend/src/components/AuthorizationPanel.vue`：路径必填、展示真实端点与预览明细；
  `GenerationPanel.vue` 先预览再把 `preview_digest` 随生成请求回传。

### 2.2 发送审计（P0-4/5）

- `models/outbound.py`：`SendAuditRecord` 新增 `attempt_id`、`phase`、`receiver`、
  `request_digest`、`error_code`；`alembic/versions/0007_send_audit_attempt_phases.py`。
- `services/outbound.py`
  - `begin_attempt()`：**网络调用前**写入 `prepared`（manifest、content_digest、
    payload/request 摘要、receiver、authorization 引用），独立提交。
  - `finish_attempt()`：追加终态行；禁止重复终结；不更新既有行（保持 append-only 触发器）。
- `generation_service._run_body`：成功 → `confirmed_sent`；超时/HTTP 错误/未知异常 →
  `possibly_sent`；`AdapterDisabled` / 取消且未写出 → `not_sent`；取消发生在发送前仍记录
  `not_sent(cancelled_before_send)`。
- `/generations/{id}/send-audit` 返回 `phase`/`attempt_id`/`receiver`/`request_digest`/`error_code`。

### 2.3 核验服务（P0-6）

- 新增 `services/verification.py`：逐项计算
  `payload_digest`、`manifest_source`、`manifest_tool_return_empty`、
  `snapshot_digest`（由快照清单重算）、`isolation_verified`、`send_confirmed`、
  `response_present`、`response_digest`、`transport_confirmed`、`non_synthetic_evidence`。
- 任一不满足 → `unconfirmed` 并记录原因；只有全部满足才 `verified`，才创建 `ProposalVersion`。
- 合成/Mock 证据只在 `testing=True` 的离线测试中可判 verified，并在
  `evidence_sufficiency.synthetic` 显式标注；`testing=False` 一律拒绝合成证据。

### 2.4 可复现（P0-8/9）

- `tests/test_account_script_ast_guard.py`：候选 staging 不存在时 `skip`，干净检出可运行。
- `README.md`：从零安装、迁移、测试、安全默认值；许可证明确标注“待人工选择”。
- `.github/workflows/ci.yml`：后端 `pip install --require-hashes -r requirements.lock`
  → `alembic upgrade head` → `pytest`；前端 `npm ci` → `npm test` → `npm run build`。

## 3. 负向测试

| 文件 | 用例 | 断言 |
|---|---|---|
| `tests/test_outbound_pipeline.py` | `test_empty_scope_never_authorizes_all_source` | 空 scope → `scope_required` |
| 同上 | `test_bare_receiver_label_is_unverifiable` | `dashscope` → `receiver_unverifiable` |
| 同上 | `test_receiver_endpoint_mismatch_denied` | 端点不同 → `receiver_mismatch` |
| 同上 | `test_source_outside_scope_denied` | 越界路径 → `scope_mismatch` |
| 同上 | `test_data_type_not_authorized_when_source_not_granted` | 只授权 requirement 时发 source → 拒绝 |
| 同上 | `test_scope_cannot_contain_traversal` | `../` → `unverifiable` |
| `tests/test_authorizations_api.py` | `test_create_rejects_empty_scope_for_source` | API 400 `scope_required` |
| 同上 | `test_create_rejects_bare_receiver_label` | API 400 `invalid_receiver` |
| 同上 | `test_create_rejects_tool_return_and_paths_without_source` | API 400 |
| 同上 | `test_preview_shows_scope_and_digests_without_sending` | 预览返回路径与两个摘要 |
| `tests/test_generation.py` | `test_timeout_records_possibly_sent` | 审计 `[prepared, possibly_sent]` |
| 同上 | `test_disabled_adapter_records_not_sent` | 审计 `[prepared, not_sent]`，零调用 |
| 同上 | `test_production_requires_preview_digest` | `preview_required`，零调用 |
| 同上 | `test_production_rejects_stale_preview_digest` | `preview_digest_mismatch` |
| 同上 | `test_unverified_execution_yields_no_proposal` | 无真实证据 → `unconfirmed`，无方案 |
| `tests/test_verification.py` | 13 项 | 缺隔离/快照/摘要/响应/传输，或生产用合成证据 → `unconfirmed` |

## 4. 从零部署结果

| 项 | 命令 | 结果 |
|---|---|---|
| Alembic | `ADLL_DATABASE_URL=sqlite:///./.tmp-alembic.db alembic upgrade head` | 0001→0007 全部成功；17 张表；`alembic_version=0007`；`send_audit_records` 含新列 |
| 后端测试 | `pytest -q`（排除 3 个受本机 ACL 影响的 worker 用例文件） | **226 passed**（194s） |
| worker 三文件 | `pytest tests/test_worker_adapter.py tests/test_worker_isolation.py tests/test_security_canary.py` | 5 passed / **13 failed**，全部为同一环境原因（见 §6） |
| 依赖锁 | `requirements.lock` 29 条含 SHA-256，与已安装版本一致 | 通过 |
| 前端锁 | `npm ci --dry-run` | 47 包，lock 与 package.json 一致 |
| 前端测试 | `npm test` | 8 passed |
| 前端构建 | `npm run build`（`vue-tsc -b && vite build`） | 成功 |

## 5. 变更文件

```text
backend/app/models/outbound.py
backend/app/services/outbound.py
backend/app/services/outbound_pipeline.py
backend/app/services/generation_service.py
backend/app/services/verification.py                  （新增）
backend/app/api/authorizations.py
backend/app/api/generations.py
backend/app/agents/base.py
backend/app/agents/mock.py
backend/app/agents/dashscope.py
backend/app/agents/worker.py
backend/alembic/versions/0007_send_audit_attempt_phases.py（新增）
frontend/src/api/index.ts
frontend/src/components/AuthorizationPanel.vue
frontend/src/components/GenerationPanel.vue
backend/tests/test_outbound.py
backend/tests/test_outbound_pipeline.py
backend/tests/test_authorizations_api.py
backend/tests/test_generation.py
backend/tests/test_cancel_recovery.py
backend/tests/test_mode_isolation.py
backend/tests/test_offline_e2e.py
backend/tests/test_payload_digest.py
backend/tests/helpers.py
backend/tests/test_verification.py                    （新增）
backend/tests/test_account_script_ast_guard.py
README.md
.github/workflows/ci.yml
```

## 6. 剩余阻断项

1. **初始提交缺少迁移与依赖锁定文件**：`backend/alembic.ini`、`backend/alembic/`、
   `backend/requirements.txt`、`backend/requirements-dev.txt`、`backend/requirements.lock`、
   `backend/pytest.ini`、`README.md`、`.github/` 仍是未跟踪状态；干净检出无法执行
   `alembic upgrade head`。发布前必须把它们与新文件一并 `git add`（含
   `backend/app/services/verification.py`、`backend/tests/test_verification.py` 与本文件）。

2. **受限 worker 的 13 个测试仍失败**（`test_worker_isolation` / `test_worker_adapter` /
   `test_security_canary`）：受限令牌无法读取项目内 `.venv/pyvenv.cfg` 与
   `app/isolation/probe_main.py`，根因是生产 ACL 硬化后项目不再向 Users 授予读权限。
   这是运行环境约束，不是本次代码缺陷；修复需把 probe/worker 脚本 staged 到沙箱或
   调整测试运行时路径，属下一轮独立变更。
3. **`npm ci` 未真实执行**（仅 `--dry-run` 校验锁一致性）；真实安装需要网络。
4. **许可证未选择**：README 已声明“待人工决定”，未添加 LICENSE。
5. **公开仓库泄露检查**：未发现 `sk-`/`ghp_`/`AKIA`/私钥/Bearer 令牌；
   但 2 个证据文档含本机主机名与绝对路径
   （`specs/.../batch9-environment-and-denial-evidence.md`、
   `batch9-isolation-deployment-plan.md`），公开前建议替换为占位符。
6. **真实 provider 未启用**：本轮只用离线合成证据验证 `verified` 路径；
   真实百炼调用与真实发送仍为 NOT RUN。
