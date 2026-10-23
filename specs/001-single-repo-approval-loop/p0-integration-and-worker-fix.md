# P0 集成一致性与受限 Worker 回归修复

**日期**：2026-10-23
**边界**：未 Commit/Push、未调用真实百炼、未安装系统组件、未修改生产 ACL/防火墙、
未访问真实业务仓库、未修改 ADLL-Knowledge。

## 1. GitHub 与本地差异

`git log`：`265a8f9 chore: initial commit` → `d15fb3f 缺了的迁移和依赖锁定文件`。
`git status`：26 个已跟踪文件被修改（本轮之前的 P0 修复），无暂存内容。

`d15fb3f` 新增了 19 个文件（Alembic 0001–0007、requirements、README、CI、
`verification.py`、`test_verification.py`、P0 报告），**但它快照的 `services/*.py`
仍是 P0 修改前的版本**：

| 文件 | HEAD (d15fb3f) | 本地工作树 |
|---|---|---|
| `outbound_pipeline.py::Prepared` | 无 `data_types` 字段 | 有 `data_types` |
| `test_verification.py` | 使用 `Prepared(data_types=...)` | 同左 |
| 结果 | 干净检出运行即 `TypeError` | 一致，测试通过 |

同类未同步：`outbound.py`（无 attempt/phase）、`generation_service.py`（无 preview/
审计三态）、`api/generations.py`（无 preview 端点）、`models/outbound.py`（无新列）。
因此 **HEAD 与本地不是同一版本**；远端 CI 的后端测试即便装好依赖也会失败。

未跟踪且不应公开：`.specify/`（含宪章）、`repair_project_acl.ps1`、
`backend/scripts/harden_project_acl.ps1`、`install_account_staging_diag.ps1`、
`install_account_staging_repair.ps1`。

## 2. CI 失败根因与修复

失败包：`MarkupSafe==3.0.4`，锁内哈希
`11935df9…36fc7`。本地 `pip download --only-binary=:all:` 校验该哈希对应
`markupsafe-3.0.4-cp312-cp312-win_amd64.whl`——锁文件是 **Windows / CPython 3.12
wheel 锁**，Linux runner 只有 manylinux wheel，`--require-hashes` 必然拒绝。

修复：`.github/workflows/ci.yml` 的后端 job 改为 `windows-latest` + Python 3.12，
保留 `--require-hashes` 与官方 PyPI；前端仍为 `ubuntu-latest`。
理由不只是哈希：受限 worker 的 DACL/Job Object 证据本来就只在 Windows 可执行。

本地同构验证：新建 venv → `pip install --require-hashes -r requirements.lock`
→ 29 个包全部安装成功（含 MarkupSafe 3.0.4、pydantic_core 2.50.1）。
**GitHub Actions 的实跑仍需推送后复核**，本轮无法代替。

## 3. 受限 Worker 13 项

### 3.1 原因（逐项核对，不是单一原因）

| 类别 | 证据 | 影响 |
|---|---|---|
| 解释器 | `stderr_tail = "No pyvenv.cfg file"`、`exit_106`；`sys.executable` 指向 `backend/.venv/Scripts/python.exe`，而项目 ACL 已不允许受限令牌读取 `.venv/pyvenv.cfg` | 所有 spawn 探针/worker 的用例 |
| 脚本位置 | 换成基础解释器后报 `can't open ... app/isolation/probe_main.py: Permission denied` | 同上 |
| 测试自身 | Job 用例用 `sys.executable` 启动受限子进程，且未给脚本加 restricting-SID ACE；脚本错误信息按 GBK 写入、按 UTF-8 读取 | 2 个 Job 用例 |
| 预览门禁 | 生产模式用例未回传 `preview_digest` | 2 个用例（P0 新门禁的预期行为） |

### 3.2 修复

- `sandbox.py::default_python()`：优先 `sys._base_executable`（基础安装，stdlib 世界可读），
  避免 venv 重定向器读取项目内 `pyvenv.cfg`。
- `sandbox.py::_stage_script()`：把 `probe_main.py` / `worker_main.py` 复制进
  `sandbox/scripts/`，记录 SHA-256，只授予 `ReadAndExecute`。
- 权限收紧：`root`/`subset`/`scripts` → `ReadAndExecute`；仅 `work` → `Modify`。
  worker 不能再改可执行代码或授权子集。
- `_script_tampered()`：每次启动前重算暂存脚本 SHA-256；不一致立即 fail-closed
  （`script_tampered`）。
- 预览门禁：生产模式测试回传 `preview_digest`。
- Job 用例：改用 `default_python()`、显式授予脚本读权限、脚本输出统一 UTF-8。

### 3.3 结果

| 文件 | 用例数 | 结果 |
|---|---|---|
| `test_worker_adapter.py` | 7 | 7 passed |
| `test_worker_isolation.py` | 13（含新增 3 项 fail-closed） | 13 passed |
| `test_security_canary.py` | 1 | 1 passed |
| 合计 | 21 | **21 passed** |

新增 fail-closed 反例：
`test_probe_fails_when_staged_script_tampered`、
`test_worker_run_fails_when_staged_script_tampered`、
`test_probe_fails_when_interpreter_missing`。

## 4. 验证结果

| 项 | 命令 | 结果 |
|---|---|---|
| 工作树全量 | `pytest -q`（含全部 Worker 用例） | **247 passed**（29m32s） |
| 干净树全量 | `pytest -q`（全新 venv） | **245 passed, 2 skipped**（29m26s） |
| 干净树跳过项 | `-rs` | 2 项均为“本地 staging 候选目录不在仓库”，符合预期 |
| Alembic | `alembic upgrade head` | 0001→0007，17 表，`0007` |
| 锁定依赖 | `pip install --require-hashes -r requirements.lock`（全新 venv） | 29 包成功 |
| 前端 | `npm ci` / `npm test` / `npm run build` | 113 包 / 8 passed / 构建成功 |

`Prepared(data_types=...)` 与源码字段在**工作树**中一致（247 passed 直接覆盖该构造）；
**HEAD 仍不一致**，因此下一次提交必须包含 §7 中修改后的 `outbound_pipeline.py`
等 30 个文件，否则远端依旧红。

## 5. 干净检出

`D:\wo\tmp\adll-clean-<ts>`：复制工作树但排除 `.git`、`.venv`、`node_modules`、
`dist`、`__pycache__`、`adll-iso-*`、`.tmp-*`、`staging-*`、`.workbuddy`、`.claude`、
`.dsh_inspect`、`.specify` 与本机运维脚本，共 212 个文件；使用**全新 venv**（非项目 `.venv`）。

- `alembic upgrade head`：0001→0007 成功，17 张表，`alembic_version=0007`。
- `npm ci`：113 包安装成功；`npm test` 8 passed；`npm run build` 成功。
- `pytest -q`：**245 passed, 2 skipped**（跳过的是本地 staging 候选目录相关用例，
  该目录不属于仓库）。

**限制**：这是“工作树快照”的干净检出，不是 GitHub main 的检出；
在推送前不能声称 GitHub main 已完整验收。

## 6. 公开信息与宪章

- 密钥模式扫描：`sk-` / `ghp_` / `AKIA` / 私钥 / Bearer 长令牌均为 0 命中。
- 2 个证据文档含本机主机名与绝对路径（`batch9-environment-and-denial-evidence.md`、
  `batch9-isolation-deployment-plan.md`），公开前建议替换为占位符。
- **AGENTS.md 第 4/11 行引用的 `.specify/memory/constitution.md` 未跟踪**，
  GitHub 上找不到；`CLAUDE.md` 同样引用。最小修复：把该文件（RATIFIED v1.2.0，
  210 行）纳入仓库，**不修改内容**。是否公开需人工批准。

## 7. 待提交文件清单

已跟踪、需提交的修改（30 个）：

```text
.github/workflows/ci.yml
backend/app/agents/base.py
backend/app/agents/dashscope.py
backend/app/agents/mock.py
backend/app/agents/worker.py
backend/app/api/authorizations.py
backend/app/api/generations.py
backend/app/isolation/sandbox.py
backend/app/models/outbound.py
backend/app/services/generation_service.py
backend/app/services/outbound.py
backend/app/services/outbound_pipeline.py
backend/tests/helpers.py
backend/tests/test_account_script_ast_guard.py
backend/tests/test_authorizations_api.py
backend/tests/test_cancel_recovery.py
backend/tests/test_db_constraints.py
backend/tests/test_generation.py
backend/tests/test_isolation_recovery.py
backend/tests/test_mode_isolation.py
backend/tests/test_offline_e2e.py
backend/tests/test_outbound.py
backend/tests/test_outbound_pipeline.py
backend/tests/test_payload_digest.py
backend/tests/test_security_canary.py
backend/tests/test_worker_adapter.py
backend/tests/test_worker_isolation.py
frontend/src/api/index.ts
frontend/src/components/AuthorizationPanel.vue
frontend/src/components/GenerationPanel.vue
```

新增（1 个）：`specs/001-single-repo-approval-loop/p0-integration-and-worker-fix.md`

需人工决定是否公开（1 个）：`.specify/memory/constitution.md`
（AGENTS.md/CLAUDE.md 引用；内容不改，仅纳入仓库）

不应提交：`repair_project_acl.ps1`、`backend/scripts/harden_project_acl.ps1`、
`backend/scripts/install_account_staging_diag.ps1`、
`backend/scripts/install_account_staging_repair.ps1`、`.specify/` 的其余内容。
