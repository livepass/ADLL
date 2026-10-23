# FV-1 阶段 2B —— 本地离线安装验证执行记录（fv1-stage2b-execution-record.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**Date**: 2026-10-19
**性质**: **阶段 2B 本地离线安装验证（修订后，单次执行）**。
**执行根（全新，未复用已停止批次）**：
`%TEMP%/adll-fv0/run-20261019-fv1-2b-r2`（路径白名单 + ReparsePoint 检查通过）。
**结论**：**安装成功，31/31 依赖与锁文件一致，原始 Wheelhouse 前后逐字节一致，
SDK/内嵌 CLI 静态核验全部通过（含一处 P6 勘误）。未触发停止条件。**

**人工验收（2026-10-19）**：**PASS（Installation & Static Verification）**。
该 PASS **仅代表**本地离线安装与静态核验通过；**不表示** SDK 运行时、Agent 权限隔离
或真实模型调用已经通过。

## 1. 新执行根与环境信息

| 项 | 值 |
|---|---|
| 执行根 | `C:/Users/焦嘉鑫/AppData/Local/Temp/adll-fv0/run-20261019-fv1-2b-r2` |
| 路径安全 | TEMP 白名单 + `realpath` 断言 + ReparsePoint 探针（`00-2b-r2-preflight.txt`） |
| 基底解释器 | Python **3.12.10**（64 位 AMD64），`sys.executable = D:\wo\python\Python312\python.exe`（`00-2b-r2-interp.txt`） |
| venv | `--copies` 创建（无 `--upgrade-deps`、无 `--system-site-packages`）；venv 内 `sys.version=3.12.10`、`is64=True`、`base_prefix=D:\wo\python\Python312`、`prefix=<root>\venv`（`01-2b-venv.txt`） |
| venv 内 pip | **vendor pip 25.0.1**（venv 自带；唯一"锁清单之外"的分发，属 bootstrap，已登记） |
| 安装前锁文件核验 | 31 行；**无 `://`、无 VCS（`git+`/`hg+`/`svn+`/`bzr+`）、无 `-e`、无 `file:`/`--find-links`/`--extra-index`、无任何主机名**（`00-2b-r2-lock-safety.txt`，全为 0） |

## 2. venv 创建与 pip 安装记录

**安装命令**（`02-2b-pip-install.log`）：
```
<venv>\Scripts\python.exe -m pip --isolated install \
  --no-index --find-links <原Wheelhouse> --require-hashes --only-binary=:all: \
  --no-cache-dir --disable-pip-version-check --no-input -r <lock.txt>
```

- **pip 退出码 = 0**。
- 日志仅出现 `Looking in links: <本地 wheelhouse>` 与逐项 `Processing <本地 wheel>`；
  **无任何 HTTP/HTTPS、无在线索引访问**。
- 末尾 `Successfully installed` 列表**恰好 31 个包**（`claude-agent-sdk-0.2.168` 等，
  与 lock.txt 一一对应）。

## 3. 31 项依赖安装前后核验

| 核验 | 结果 |
|---|---|
| 安装前 Wheelhouse（31 wheel，哈希 vs lock.txt） | `BEFORE_VERIFY = PASS`（0 unmatched） |
| 安装后 `pip freeze` vs `lock.txt`（**规范化比较**：`-`/`_`/`.` → `-`） | **PASS 31==31**：missing=[]，extra=[]，version_mismatch=[] |
| 命名说明 | freeze 的 `pydantic_core`/`typing_extensions` 与锁文件 `pydantic-core`/`typing-extensions` 为**同一包**（PEP 503 规范化），非差异 |
| 唯一额外项 | `pip 25.0.1`（venv bootstrap，非依赖） |
| 安装后 Wheelhouse | **与安装前逐字节一致**（31/31 sha256 相同 → 原 Wheelhouse **只读未被改动**） |

## 4. SDK 0.2.168 与内嵌 CLI 2.1.301 静态验证（未运行，未 import）

| 项 | 结果 |
|---|---|
| SDK 版本 | `_version.py` → `__version__ = "0.2.168"` |
| 内嵌 CLI 版本 | `_cli_version.py` → `__cli_version__ = "2.1.301"` |
| SDK 许可证 | `METADATA`：`Name=claude-agent-sdk`、`Version=0.2.168`、`License: MIT`、`Requires-Python: >=3.10` |
| **内嵌 CLI 哈希** | `venv/.../claude_agent_sdk/_bundled/claude.exe`：大小 **271,840,416**、sha256 **`84d61feeb1a07e5a5b3354d68432591cac18a5d38a419a30d86d0f3ad8cba397`**（== 经 GPG 验签的官方 manifest `win32-x64` 值，**逐字节一致**） |
| **内嵌 CLI Authenticode** | `Status = Valid`，签名者 `CN="Anthropic, PBC"`（离线读，未执行） |
| SDK 类型定义（`types.py`） | 见 §7（P6 静态核验） |

**未执行**：未运行 `claude.exe`、未 `claude --version`、未 `doctor`、未 `query()`、
**未 `import claude_agent_sdk`**（所有核验均为纯文件读取 + 哈希/签名计算）。

## 5. 网络行为与写入边界证据

- **网络行为**：pip 以 `--no-index --find-links` 运行，日志无在线请求。
  **不宣称`--no-index`为 OS 级网络隔离证明**（按用户边界要求：由 pip 层保证零索引访问；
  宿主网络保持连接）。
- **写入范围（两类须区分，2026-10-19 补记）**：
  1. **安装进程的写入**：仅 `<root>/venv/`（venv + 31 个包）与 `<root>/evidence/`（证据文件）。
     `%APPDATA%\Local\ClaudeCode` **不存在**（未被安装创建）；`~\.claude` 与 `~\.claude.json`
     为 Claude Code 宿主**预先存在**的状态（mtime 反映宿主会话活动，非本安装产生）；
     原 Wheelhouse 只读、前后哈希一致。以上由 `--no-index --find-links --no-cache-dir` 的
     约束及核验证据支撑。
  2. **已授权的 ADLL 项目文档更新**（独立于安装进程）：本轮在
     `D:\wo\code\ADLL\ADLL\specs\001-single-repo-approval-loop\` 下**新增**本记录文件，
     并对 `fv1-stage1-version-verification-record.md`、`fv1-stage2a-2b-execution-plan.md`、
     `fv1-pre-execution-approval-checklist.md` 做**勘误登记**（`thinking` 字段）与状态登记
     （§N 阶段 2B 标 ☑）。这些写入由**用户本轮授权**的文档登记行为产生，**发生在项目
     `specs/` 目录内**，与安装进程写入的 TEMP 执行根**完全不同路径**、不同目的。
- 真实仓库 `D:\wo\code\ADLL\ADLL`：`git status --porcelain` 输出 6 行 `?? `（`.claude/`、
  `.specify/`、`AGENTS.md`、`CLAUDE.md`、`docs/`、`specs/`）——与**会话开始快照**的
  **未跟踪路径集合**一致，**仅能证明安装进程未新增/删除未跟踪条目、未改动被跟踪文件**。
**未跟踪目录内部文件内容是否未变**：`git status` 对未跟踪路径只显示其**顶层存在性**，
  **不**对其内部文件做内容 diff；因此「git status 前后一致」**不能证明** `specs/`、`docs/`
  等未跟踪目录内部的文件内容**逐字节未变**（事实上 `specs/` 本轮已按授权发生文档更新）。
  要证明「未变」须对各已知文件做**哈希基线比对**，本轮未做该比对；故本节**只断言安装进程
  未改动仓库被跟踪文件、未新增/删除未跟踪条目**，**不**断言未跟踪目录内容逐字节未变。
- 原始 Wheelhouse `run-20261019-fv1-wheel2/wheelhouse` **只读**，前后哈希一致（§3）。

## 6. P6：已完成静态核验 vs 仍需真实行为验证

### 6.1 已通过（本轮静态核验，`05-2b-sdk-static.txt` + `05b-thinking-precise.txt`）

| 字段/项 | 结果 |
|---|---|
| `max_tokens` | **ABSENT**（全字段无此名）→ H4「SDK 无 `max_tokens`」结论维持 |
| `thinking` | **PRESENT**（`thinking: ThinkingConfig \| None = None`；`ThinkingConfig` = `{"type":"adaptive"}` / `{"type":"enabled","budget_tokens":N}` / `{"type":"disabled"}`）——**勘误，见 §6.3** |
| `max_thinking_tokens` | **PRESENT**，`int \| None`，**已弃用**（docstring：「Deprecated. Use `thinking` instead」） |
| `task_budget` | **PRESENT**（`task_budget: TaskBudget \| None`） |
| `sandbox` | **PRESENT**（`SandboxSettings` 字段：`enabled`/`autoAllowBashIfSandboxed`/`excludedCommands`/`allowUnsandboxedCommands`/`network`/`ignoreViolations`/`enableWeakerNestedSandbox`） |
| `failIfUnavailable` / `fail_if_available` | **ABSENT**（Types 中无此键）→ **确认 P6 勘误**：该安全设置不是 SDK 0.2.168 声明的 Python 字段 |
| `tools`/`allowed_tools`/`disallowed_tools`/`skills`/`plugins`/`mcp_servers`/`strict_mcp_config`/`setting_sources`/`permission_mode`/`hooks`/`env`/`cwd`/`max_turns`/`max_budget_usd` | **PRESENT**（与 §A/§I 记载一致） |
| 版本/许可证/内嵌 CLI | `0.2.168` / `2.1.301` / MIT / 哈希==官方 manifest / Authenticode `Valid`（§4） |

### 6.2 仍需真实行为验证（阶段 3 前；本轮不授权运行，故留待）

1. `tools=[]` 是否**真正移除内置工具集**（含 `EndConversation` 移除的边界）——静态仅知
   类型为 `list[str] | ToolsPreset | None`。
2. `setting_sources=[]` 的实际加载行为（官方文档「Pass `[]` to disable user/project/local」，
   需行为证据；且**托管策略无视该选项**须再核）。
3. `task_budget` 的 beta 头 `task-budgets-2026-03-13`、最低 `total`、实际生效/交互。
4. `sandbox` 在**原生 Windows 不受支持**（官方），若用须核实其 `network` 子策略与
   `failIfUnavailable` 的**有效传递方式**（已确认非 Python 字段）。
5. `max_budget_usd` 为客户侧**估算**（官方「estimate can pass this value」）→ 非硬上限。
6. `permission_mode` 六值（含新增 `auto`/`dontAsk`）的实际默认与自动许可行为。
7. `DISABLE_UPDATES`/`DISABLE_AUTOUPDATER`/`DISABLE_TELEMETRY` 等环境变量对**捆绑 CLI**
   是否等效生效——需运行 CLI 观测，本轮不授权。

### 6.3 P6 勘误登记（本轮新发现）

阶段 1 曾记录「`thinking`：ABSENT（无该字段）」，**经本轮对已安装 0.2.168 `types.py` 的
静态核验更正为 PRESENT**（第 2714 行 `thinking: ThinkingConfig | None = None`；第 2705 行
`max_thinking_tokens` 已弃用并指示「Use `thinking` instead」）。原因与 `cryptography` 哈希
一致：**WebFetch 摘要遗漏了 types.py 尾部字段**。已追加勘误至
[fv1-stage1-version-verification-record.md](./fv1-stage1-version-verification-record.md)
与 [2A/2B 方案](./fv1-stage2a-2b-execution-plan.md) §3B-3-S2；原始记录行保留、以勘误标注更正。

## 7. 阶段 3 仍需解决的风险（如实登记）

| # | 风险 | 说明 |
|---|---|---|
| 1 | **OS 级出站安全边界未实施** | 阶段 3 需「不可绕过」边界；候选 W1（独立虚拟机，优先）/W2（WSL2 + CLI 沙箱）**未实施、未验证** |
| 2 | **运行期 CLI 出站端点** | `api.anthropic.com`（API + feature-flag 抓取 + 遥测上报）、`downloads.claude.ai`（更新/版本检查）、`raw.githubusercontent.com`（交互式 changelog）等 —— 须在阶段 3 阻断或经 `DISABLE_UPDATES`/`DISABLE_TELEMETRY` 等关闭（**其效用需行为验证**） |
| 3 | **托管设置无视 `setting_sources`** | 阶段 3 前须确认本机无 `managed-settings.json`/MDM/claude.ai 托管策略 |
| 4 | `permission_mode` 新增 `auto`/`dontAsk` | 必须显式 `"default"`，规避自动许可 |
| 5 | `sandbox` 不可用于原生 Windows，`failIfUnavailable` 传递未核实 | 不得宣称本机有 CLI/OS 沙箱 |
| 6 | 金额/Token 控制非硬上限 | `max_budget_usd` 估算式、`task_budget` 为预算感知（非严格上限）、无 `max_tokens` |
| 7 | 内嵌 CLI 供应链「有限风险」 | 已溯源至官方签名 manifest，但按用户裁定**不视为生产级安全验证** |

## 8. 停止条件核验与未授权项

- **停止条件全部未触发**：锁文件与 Wheelhouse 一致 · 哈希无异常 · 无网络访问/清单外依赖 ·
  pip 安装成功（exit 0）· 无未授权目录写入 · 证据完整 · 安全门禁通过。
- **未执行**：运行 SDK/CLI（含 `--version`/`doctor`/`query`/`import`）· API Key · 付费调用 ·
  阶段 3 · FV-2～FV-7 · 业务开发 · 修改网络/防火墙 · 在线索引 · 源码构建 · 自动更新。
- **未修改**：宪章、spec.md、AGENTS.md、ADLL-Knowledge、任何原始实验档案；本轮仅**新增**
  本记录文件，并对两处既有 P6 记载做**勘误标注**（`thinking` PRESENT），原始证据与
  已停止批次目录均**完整保留未被改写**；无 Git Commit/Push。

## 9. 证据清单（执行根 `%TEMP%/adll-fv0/run-20261019-fv1-2b-r2/evidence`）

`00-2b-r2-preflight.txt` · `00-2b-r2-interp.txt` · `00-2b-r2-lock-safety.txt` ·
`01-2b-wheelhouse-before.txt` · `01-2b-venv.txt` · `02-2b-pip-install.log`（命令全文 + exit 0）·
`03-2b-pip-freeze.txt` · `03-2b-freeze-vs-lock.txt` · `04-2b-wheelhouse-after.txt` ·
`04-2b-wheelhouse-diff.txt`（IDENTICAL=True）· `05-2b-sdk-static.txt` ·
`05b-thinking-precise.txt` · `06-2b-repo-status.txt` · `99-2b-r2-final.txt` · `lock.txt`（副本）。