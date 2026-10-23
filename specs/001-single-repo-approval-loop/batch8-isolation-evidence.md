# 批 8 受限 worker 与 Windows 权限隔离证据

**Date**: 2026-10-21
**Scope**: ADLL V1.1 批 8（受限运行环境实现与离线安全验收收口）
**边界（本批实际执行）**：
- 未发起任何真实百炼/模型 API 请求；未读取或记录 `DASHSCOPE_API_KEY`。
- 未访问真实用户业务仓库；未向外部发送源码。
- 未修改系统全局防火墙、未创建永久系统账户、未修改真实用户目录 ACL、
  未扩大管理员权限。
- 所有 ACL 修改均限于 `backend/` 下专用临时测试目录（合成仓库、合成 DB、
  合成用户目录 canary），并在测试结束时通过 SDDL 快照回滚。

## 1. 受限 worker 结构（实现文件）

| 组件 | 文件 | 作用 |
|---|---|---|
| 受限令牌 / DACL / Job Object 原语 | `backend/app/isolation/win32.py` | `CreateRestrictedToken`（restricting SIDs）、`CreateProcessAsUserW`、`IsTokenRestricted`、Job Object（kill-on-close、禁 breakaway）、`Deny/Allow <SID>` ACL、SDDL 快照与回滚 |
| 权限探针（worker 内） | `backend/app/isolation/probe_main.py` | 在受限进程中实测：授权子集可读、原仓库/DB/用户目录/凭据不可读、DB 不可写；只输出布尔/错误类型/长度，不复制内容 |
| 生成 worker（独立进程） | `backend/app/isolation/worker_main.py` | 仅标准库；只读父进程写入 sandbox 的 payload；真实模式必须显式 `ADLL_WORKER_REAL_TRANSPORT=1`；禁代理/禁重定向/固定端点；默认 fail-closed |
| sandbox 编排 | `backend/app/isolation/sandbox.py` | 创建临时 sandbox、物化子集、ACL Deny、运行探针/worker、超时终止、资源清理 |
| WorkerAgentAdapter | `backend/app/agents/worker.py` | `self_check()` 完全由真实探针证据决定；探针失败 → `AdapterDisabled`（零发送）；每次生成重新探针 |
| 工厂 | `backend/app/agents/factory.py` | `real_ai_enabled` 时使用 WorkerAdapter；默认仍 `NoRealAdapterAvailable` |
| 配置 | `backend/app/config.py` | `ADLL_WORKER_SANDBOX_ROOT`、`ADLL_WORKER_ACL_ROOT`、`ADLL_WORKER_DENY_READ/WRITE`、`ADLL_WORKER_PYTHON`、`ADLL_WORKER_REAL_TRANSPORT` |

### 1.1 执行主体与机制（事实）

- **执行主体**：父进程（后端）以 `CreateRestrictedToken` 派生受限令牌子进程；
  restricting SIDs = `BUILTIN\Users (S-1-5-32-545)`、`Authenticated Users (S-1-5-11)`、
  `Everyone (S-1-1-0)` + 本次随机专用 SID `S-1-5-21-…`（不可映射的本地 SID）。
- **读取隔离权威**：对原仓库/审批 DB/用户目录 canary/凭据 canary 添加
  `Deny <专用 SID> FullControl`（目录继承 OI/CI）。低完整性（MIC）未作为证据。
- **允许面**：仅 sandbox 子集目录显式 `Allow <专用 SID>`；worker 只收到 payload，
  不收到原仓库/DB 路径。
- **令牌证据**：父进程打开 worker 进程令牌并调用 `IsTokenRestricted`；
  结果为真才继续，否则立即终止并拒绝运行。worker 内探针再次报告可读/不可读/不可写。
- **进程生命周期**：Job Object 设置 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`，
  未设置 BREAKAWAY_OK / SILENT_BREAKAWAY_OK；关闭 Job 终止整个进程树。

## 2. 实际执行证据

### 2.1 权限探针与 DACL（`tests/test_worker_isolation.py`）

命令：

```text
backend/.venv/Scripts/python.exe -m pytest tests/test_worker_isolation.py -q
→ 7 passed
```

| 测试 | 实际结果 |
|---|---|
| `test_probe_denies_repo_db_home_credential_and_allows_subset` | `token_restricted=True`（父进程打开子进程令牌）；原仓库/DB/用户目录/凭据读取均为 `PermissionError`；DB 与仓库写入均 `PermissionError`；受权子集读取成功且父进程复核 SHA-256 一致 |
| `test_probe_fails_when_dacl_deny_missing` | 对未加 Deny 的可读文件，探针返回 `denied=False`、`ok=False`（不会把“未验证”当通过） |
| `test_acl_scope_refuses_paths_outside_isolation_root` | 对用户主目录路径执行 ACL 修改被 `ValueError` 拒绝（防止误改真实目录） |
| `test_worker_synthetic_job_and_no_credential_in_environment` | worker 合成结果成功；`DASHSCOPE_API_KEY`（测试 canary）不在 worker env、job、stdout/stderr |
| `test_worker_real_mode_refuses_without_explicit_transport_flag` | 未设置 `ADLL_WORKER_REAL_TRANSPORT=1` 时返回 `real_transport_disabled`，无网络调用 |
| `test_job_object_kills_worker_child_tree` | 关闭 Job 后 worker 与其派生的子进程均不再存活 |
| `test_injection_text_is_data_not_command_and_repo_scripts_never_run` | 注入指令仅作为文本进入 payload；仓库 `run.bat` 未执行，标记文件未生成 |

### 2.2 WorkerAgentAdapter（`tests/test_worker_adapter.py`）

```text
→ 7 passed
```

覆盖：`self_check` 证据化（受限令牌 + allow/deny）、无 Deny 配置/客体缺失时失败、
合成生成经真实受限进程、真实模式未显式启用时 `AdapterDisabled`、探针失败禁止生成、
generation service 使用 worker 后执行完成但非 testing 下不产生 `verified`/方案。

### 2.3 敏感 canary 全链路（`tests/test_security_canary.py`）

```text
→ 1 passed
```

合成 `.env` 含 canary；实际发送面仅授权 `a.txt`。结果：
- canary 不在 worker job / result 序列化内容中；
- 不在 Python 日志（`caplog` DEBUG）中；
- 不在临时 SQLite 数据库文件字节中；
- job 中不含原仓库路径与 `DASHSCOPE_API_KEY`。

### 2.4 恶意内容与脚本零执行（S2/S3）

`test_injection_text_is_data_not_command_and_repo_scripts_never_run`：
仓库含 `README.md` 注入指令与 `run.bat`（会写标记文件）；worker 仅返回合成文本，
标记文件不存在、`run.bat` 未被调用。**注意**：本项验证的是“无执行通道 + 文本作为数据”，
不是对真实模型的提示注入鲁棒性测试。

## 3. 未覆盖与限制（不得宣称通过）

1. **真实用户目录/真实业务仓库/生产审批 DB 的 ACL 未修改**：本批按授权仅使用临时测试目录。
   生产启用需另行批准，对真实路径添加 `Deny <专用 SID>`，或改用独立低权限账户/VM/AppContainer。
2. **S9 真实外发核对 NOT RUN**：未发起真实提供商流量，未使用防火墙/代理日志观测；
   worker 端仅以代码约束（固定端点、禁代理、禁重定向、单次请求）作为出站策略。
3. **OS 级出站白名单未实施**：未修改系统防火墙；不能声称“网络已隔离”。
4. **未使用 AppContainer/Windows Sandbox/WSL/VM**：本批使用受限令牌 + DACL + Job Object；
   不声称其强度等同独立虚拟机。
5. **取消**：worker 超时/关闭由 Job Object 终止进程树；显式取消通过
   `_ACTIVE_ADAPTERS` → `WorkerAgentAdapter.cancel` → `Sandbox.cancel` 终止 Job。
   worker 在真实发送前写 `sent.marker`；编排层据此区分 `cancelled`（未发出）与
   `not_cancelled`（可能已发出，不可撤回）。合成模式不写 marker。相关测试：
   `test_cancel_recovery.py::test_worker_termination_records_true_cancel_outcome`
   （`cancelled` / `not_cancelled` 两分支）。真实 HTTP 发送阶段的取消未做真实验证。
6. **探针局限**：`probe_main` 不导入 `ctypes/hashlib`（受限令牌下部分 DLL 不可加载），
   `token_restricted` 由父进程打开子进程令牌证据化，allowed 文件哈希由父进程复核；
   这仍是 OS 证据，但不是 worker 自证。

## 4. 回滚方案

- 每个 `deny_sid`/`allow_sid` 在修改前保存目标路径原始 SDDL；`Sandbox.close()` 逆序
  恢复 SDDL。测试结束删除临时 sandbox 目录。
- 不创建账户、不写注册表、不改全局防火墙；无系统级残留。
- 若进程异常中断：残留仅可能出现在 `backend/` 下临时测试目录；可安全删除；
  不影响真实用户目录/仓库/系统。
- 生产化前需批准的额外操作：
  1. 对真实仓库/DB/用户目录添加 Deny ACE（需列出精确路径与专用 SID，提供 SDDL 回滚）；
  2. 或部署独立低权限账户/虚拟机/AppContainer；
  3. 若需 OS 出站白名单，需批准 Windows 防火墙按进程规则（本批禁止）。

## 5. 复现命令

```text
backend/.venv/Scripts/python.exe -m pytest tests/test_worker_isolation.py tests/test_worker_adapter.py tests/test_security_canary.py -q
backend/.venv/Scripts/python.exe -m pytest -q          # 156 passed（批 7 基线 138 + 批 8）
frontend/npm test                                       # 8 passed
frontend/npm run build                                  # 成功
```

浏览器验收命令与环境见 [batch8-browser-verification.md](./batch8-browser-verification.md)。