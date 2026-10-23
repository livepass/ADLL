# FV-1 阶段 2A / 2B —— 执行清单与网络隔离验证方案（fv1-stage2a-2b-execution-plan.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**Date**: 2026-10-18
**性质**: **执行方案（未执行）**。本轮仅授权编制本方案；**不授权实际 Wheel
获取、创建 venv、安装 SDK、安装或运行 SDK/CLI、发起 AI 调用、使用 API Key**。
**依据**: 用户 2026-10-18 阶段 1 审核裁定（四项技术裁定 + 阶段 2 拆分）·
[fv1-stage1-version-verification-record.md](./fv1-stage1-version-verification-record.md)
（版本与供应链核验）· 官方文档核验（本方案 §0.3 列出全部来源与核验日）·
[fv1-pre-execution-approval-checklist.md](./fv1-pre-execution-approval-checklist.md)
（§A/§B/§C/§I/L1–L12）。

## 0. 授权边界与本方案的事实基础

### 0.1 用户裁定登记（2026-10-18，逐条原文要旨）

| # | 裁定 | 对本方案的影响 |
|---|---|---|
| D-PY | 选择现有 **Python 3.12.10**，使用**独立 venv**，执行前核对 **64 位环境与解释器路径** | §2A-0 / §2B-1 前置检查 |
| 网络 | **允许扩展只读官方文档范围至 `code.claude.com`**；**不开放 `claude.ai`**；**必须使用 PyPI 发布的 Windows Wheel**，**禁止 sdist 和自动 CLI 下载/更新** | §2A 网络范围、§2B 静态校验、§5 更新阻断 |
| C2-e | **不接受**以普通代理 + hosts + 阶段断网**冒充不可绕过的网络隔离**；阶段 2 采用**受控获取 Wheel + 断网安装**；阶段 3 的出站安全边界**另行实施和验证**；**不得修改宿主机全局防火墙** | §4（阶段 2 隔离设计）与 §6（阶段 3 边界，仅登记要求与候选，**不含**任何"已等效"表述） |
| 供应链 | 接受**仅用于隔离合成测试的有限风险**；必须核验**整个 Wheel 的哈希**、记录**内嵌 CLI 的版本和哈希**、检查**额外下载及自动更新风险**；**不视为生产安全验证** | §5（更新与额外下载阻断）+ §3.4（内嵌 CLI 核验） |
| 阶段拆分 | 原阶段 2 → **2A**（完整依赖解析、锁定清单、Wheel 获取准备）+ **2B**（审核锁定清单后**独立批准离线安装**） | §1–§4 |
| 保留未完成项 | 完整传递依赖锁定、P6 语义核验、内嵌 CLI 使用条款、网络隔离实施验证 | §7 未核实项清单（P6 语义已在本次部分核实，见 §7） |

### 0.2 本方案的边界（明确不做）

- 不下载任何 wheel/CLI/安装包；不创建 venv；不安装或运行 SDK/CLI；不发起 AI 调用；
  不使用 API Key；不执行 FV-2～FV-7；不修改真实仓库或 ADLL-Knowledge；不清理既有
  证据；不 Git Commit/Push；**不修改宿主机全局防火墙或任何网络配置**。

### 0.2b 阶段 2A 受限执行结果（2026-10-18，已获批准并执行）

- **执行根**：`%TEMP%/adll-fv0/run-20261018-fv1-2a`；记录见
  [fv1-stage2a-execution-record.md](./fv1-stage2a-execution-record.md)。
- **实际执行**：只读元数据核查 + 候选清单（**31 个分发包**）+ P-2 三文件签名核验
  （**签名通过**，指纹与官方一致；CLI 2.1.301 win32-x64 校验和已取得）。
- **未执行**：pip `--dry-run/--report`（用户裁定：不具备请求层阻断能力 → 不得执行）
  → **依赖解析仍未完成**，候选清单**不是锁文件**。
- 因此本方案 §2A-3/§2A-4 中**关于运行解析器的步骤（及其参数）尚未实际执行**；
  其是否可执行取决于未来的阻断能力或另行裁定。

### 0.3 本次新核验的官方事实（`code.claude.com` 只读，核验日 2026-10-18）

| # | 事实（原文要旨） | 来源 |
|---|---|---|
| F-1 | **原生安装（native）会自动后台更新**：「Native installations automatically update in the background」；「Claude Code checks for updates on startup and periodically while running」 | `/docs/en/setup` |
| F-2 | **`DISABLE_AUTOUPDATER=1`**（settings `env`）仅停**后台检查**，`claude update`/`claude install` 仍可用；**`DISABLE_UPDATES`** 用于**阻断全部更新路径（含手动）** | `/docs/en/setup` |
| F-3 | 更新相关端点：`downloads.claude.ai`（native installer、native auto-updater、update version checks）；旧版（<2.1.116）走 `storage.googleapis.com` | `/docs/en/network-config` |
| F-4 | **发布物有 GPG 签名 manifest**：`https://downloads.claude.ai/claude-code-releases/<VERSION>/manifest.json`（+ `.sig`），含各平台二进制 **SHA256**；**签名自 2.1.89 起可用**；签名密钥指纹 `31DD DE24 DDFA B679 F42D 7BD2 BAA9 29FF 1A7E CACE`（security@anthropic.com） | `/docs/en/setup` |
| F-5 | **Windows 二进制有 Authenticode 代码签名**，签名者 "Anthropic, PBC"，可 `Get-AuthenticodeSignature` 核验（**离线可做**） | `/docs/en/setup` |
| F-6 | **CLI 自带沙箱（Bash sandbox）在 macOS/Linux/WSL2 由操作系统强制执行；在原生 Windows 上命令以「未沙箱」方式运行**；「To use the sandbox on a Windows machine, run Claude Code inside a WSL2 distribution」 | `/docs/en/sandboxing`、`/docs/en/setup` |
| F-7 | 沙箱仅覆盖**shell 命令**；「Claude's file tools, MCP servers, and hooks run outside it」 | `/docs/en/sandboxing` |
| F-8 | SDK 侧 `SandboxSettings.enabled` **默认 `False`**；**当 `enabled=True` 但沙箱无法启动时，Python SDK 默认以未沙箱方式运行并仅向 stderr 告警**（TS SDK 的 `failIfUnavailable` 默认为 `true`，Python 不同）。官方文档出现「Set `"failIfUnavailable": True` in your sandbox settings」与「The SDK forwards `failIfUnavailable` to Claude Code along with the declared `SandboxSettings` fields」的表述；**但 SDK 0.2.168 的 `SandboxSettings` TypedDict 未声明该键**（本阶段源码核验字段：`enabled`、`autoAllowBashIfSandboxed`、`excludedCommands`、`allowUnsandboxedCommands`、`network`、`ignoreViolations`、`enableWeakerNestedSandbox`）→ **该安全设置的传递机制未核实**（用户 2026-10-18 勘误） | `/docs/en/agent-sdk/python` + 用户勘误 |
| F-9 | `SandboxNetworkConfig` 字段：`allowedDomains`、`deniedDomains`、`allowManagedDomainsOnly`、`allowUnixSockets`、`allowAllUnixSockets`、`allowLocalBinding`；**不约束 WebFetch 工具** | `/docs/en/agent-sdk/python` |
| F-10 | `setting_sources`：**「Pass `[]` to disable user, project, and local settings」**；但「**Endpoint-managed policy loads regardless**」（托管策略无视该选项） | `/docs/en/agent-sdk/python` |
| F-11 | `tools`：CLI 侧 `--tools ""` **禁用全部内置工具**；「**The flag doesn't affect MCP tools**；to deny those too, use `--disallowedTools "mcp__*"`」；「A list that omits `EndConversation` doesn't remove it; `""` removes it only when no MCP tools remain」 | `/docs/en/cli-reference` |
| F-12 | `allowed_tools`：**「This does not restrict Claude to only these tools」**（未列工具落入 `permission_mode`/`can_use_tool`）→ **再次确认勘误** | `/docs/en/agent-sdk/python` |
| F-13 | `disallowed_tools`：裸名**从上下文移除**该工具；带作用域规则（如 `Bash(rm *)`）在**所有权限模式（含 `bypassPermissions`）**下拒绝匹配调用 | `/docs/en/agent-sdk/python` |
| F-14 | `skills`：**「When set, the SDK adds the Skill tool to `allowed_tools` automatically. If you also pass `tools`, include `"Skill"` in that list」**；`skills` 传 `"all"` 即启用全部已发现技能；非法名在启动前以 `ValueError` 拒绝（需 ≥0.2.129） | `/docs/en/agent-sdk/python` |
| F-15 | `task_budget`：**「API-side token budget. Sent as `output_config.task_budget` with the `task-budgets-2026-03-13` beta header. Pass `{"total": <int>}`」** | `/docs/en/agent-sdk/python` |
| F-16 | `max_budget_usd`：**「Stop the query when the client-side cost estimate reaches this USD value. The estimate can pass this value, so leave headroom」** → 确认**非硬上限** | `/docs/en/agent-sdk/python` |
| F-17 | `max_turns`：「Maximum agentic turns (tool-use round trips)」 | `/docs/en/agent-sdk/python` |
| F-18 | `env`：「Environment variables **merged on top of the inherited process environment**」→ 确认**非白名单** | `/docs/en/agent-sdk/python` |
| F-19 | `--restricted`（**需 CLI ≥2.1.248；本版 2.1.301 满足**）：移除运行命令/代码的内置工具与 WebFetch（除非在 `--tools` 中逐个点名）、将文件工具限制在工作目录、**只加载托管设置与 `--settings`**、**拒绝 `bypassPermissions`** | `/docs/en/cli-reference` |
| F-20 | `--permission-prompts none`（≥2.1.259）：无人应答时权限提示一律**拒绝** | `/docs/en/cli-reference` |
| F-21 | `permission_mode` 字面量：`default`/`acceptEdits`/`plan`/`auto`/`dontAsk`/`bypassPermissions`/（`manual`＝`default` 别名） | `/docs/en/cli-reference` |
| F-22 | 可关闭的非必要流量：`DISABLE_TELEMETRY`/`DO_NOT_TRACK`（Datadog 运维遥测）、`DISABLE_ERROR_REPORTING`、**`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`**（同时停两处 Datadog 主机与 Gerrit 查询）、`ENABLE_CLAUDEAI_MCP_SERVERS=false` / `disableClaudeAiConnectors`（停 claude.ai 连接器）、`CLAUDE_CODE_DISABLE_ARTIFACT=1` | `/docs/en/network-config`、`/docs/en/settings` |
| F-23 | **非交互（`-p`/SDK）会话不会后台抓取 changelog**（`raw.githubusercontent.com` 的 `/release-notes` feed 仅交互式会话启动时抓） | `/docs/en/network-config` |
| F-24 | CLI 自述「**internet connection required**」；网络要求列出全部必需/可选端点（含 `api.anthropic.com` 同时承载 API、**feature flag 抓取**与**遥测事件上报**） | `/docs/en/setup`、`/docs/en/network-config` |
| F-25 | 托管设置（`managed-settings.json`/MDM/claude.ai console）**无视** `setting_sources`；`/status` 的 `Setting sources` 行列出来源 | `/docs/en/settings` |

> **核验级别说明**：以上均为**官方文档声明**（非本机实测）。凡涉及本机行为
> （如沙箱能否启动、更新是否真被阻断）一律需在 2A/2B **实测留证**后方可采信。

## 1. 阶段划分与授权关系

```
阶段 1（已完成 · 已批准）官方资料核验与版本准备
   ↓
阶段 2A（本方案：待批准执行）完整依赖解析 · 锁定清单生成 · Wheel 获取准备
   ↓  ← 交付物：可供哈希校验的完整锁定清单 + wheelhouse
阶段 2B（本方案：待批准执行；须先审核 2A 交付物后【独立批准】）断网离线安装
   ↓
阶段 3（本方案仅登记要求：网络出站安全边界另行实施与验证；调用仍待批准）
```

**授权纪律**：2A 与 2B **各自独立审批**；**2B 的批准前提是 2A 交付的锁定清单
与 wheelhouse 已经人工审核**；任一阶段失败 → 停止、留证、报告，**不自行修复
重试**。

## 2. 阶段 2A 执行清单（完整依赖解析 · 锁定清单 · Wheel 获取准备）

### 2A-0 前置检查（全部通过方可继续）

| # | 检查项 | 方法（只读/本地） | 判定 |
|---|---|---|---|
| A0-1 | **64 位环境** | `"$PY" -c "import sys,platform;print(sys.maxsize>2**32, platform.machine(), platform.architecture())"`（期望 `True AMD64`） | 非 64 位 → 停 |
| A0-2 | **解释器路径** | 期望 `sys.executable` = `D:\wo\python\Python312\python.exe`；`sys.version` 以 `3.12.10` 开头 | 不符 → 停 |
| A0-3 | pip 版本与能力 | `"$PY" -m pip --version`（期望 ≥22.2，本次实测 26.2.1）；**并保存 `pip install --help` 全文入证据**（用于核实 dry-run/report 语义，见 §2A-3） | 无 `--report` → 停 |
| A0-4 | 执行根 | 全新专用目录（TEMP 白名单 + ReparsePoint 探针 + `realpath` 断言），与既有证据/FV-0 档案分离 | 不符 → 停 |
| A0-5 | 目标 wheel 哈希基线 | 记录 §A4 的 `win_amd64` wheel sha256 `ed1814b0…` 作为比对基线 | — |
| A0-6 | **托管设置面检查**（新，F-25/F-10） | 检查本机是否存在 `managed-settings.json`（系统目录/MDM）与 `~/.claude/settings.json`；记录内容摘要 | 存在托管策略 → **停并报告**（策略无视 `setting_sources`，会破坏隔离假设） |
| A0-7 | 网络基线 | 记录当前网络状态与 DNS 配置（只读）；声明 2A 允许的出站范围（§2A-2） | — |

### 2A-1 目标与交付物

| 交付物 | 说明 |
|---|---|
| **`wheelhouse/`** | 全部目标 wheel 落盘（**含 SDK 本体与全部传递依赖**），文件名/大小/sha256 逐项记录 |
| **`lock.txt`** | **requirements 语法**的锁文件：每行 `包名==版本 --hash=sha256:<64位>`；**这是唯一供 `--require-hashes` 使用的锁文件** |
| **`lock-manifest.csv`（侧车清单）** | 每包一行：包名、版本、文件名、sha256、来源 URL、`requires_python`、**许可证**、依赖来源（谁引入）、是否有 win_amd64 轮子 |
| **`2A-report.json`** | pip 生成的原始 report（**仅作原始证据**，见 §2A-3 的禁止事项） |
| 网络与命令证据 | 全部命令全文、pip 详细日志、**目的地址留证**、耗时、退出码、文件夹全量清单 |

### 2A-2 网络范围（**须在批准中逐项确认**）

| 项 | 内容 |
|---|---|
| 允许域名 | `pypi.org`、`files.pythonhosted.org`（+ 若指定镜像：______） |
| **允许但需单独确认** | `downloads.claude.ai` —— **仅用于取 `…/claude-code-releases/2.1.301/manifest.json` 与 `manifest.json.sig` 两个只读文件**，用于核验**内嵌 CLI 的哈希与签名**（用户明确要求"记录内嵌 CLI 的版本和哈希"）。**若不予开放**：仍可完成 2A/2B，但内嵌 CLI 只能"记录哈希"而**无法与官方签名 manifest 溯源比对**（如实降级登记） |
| **明确不允许** | **`claude.ai`**（用户裁定不开放）、`downloads.claude.ai` 下除上述两个文件以外的任何内容（尤其**不得**取 installer/二进制）、任何安装包镜像的第三方来源、任何 CDN |
| 规则 | 出现计划外目的地 → **立即停止**并留证（不自行换源、不重试） |

### 2A-3 pip `dry-run/report` 的联网与下载行为（**必须明确，且不得误解**）

> 用户要求：「阶段 2A 应明确 pip dry-run/report 的联网与下载行为；最终交付
> 必须是可供哈希校验的完整锁定清单，**不能直接将 report.json 当作锁文件**」。

**（a）已知/可预期的行为与不确定项——按证据分级陈述**

| 断言 | 分级 | 依据/处置 |
|---|---|---|
| `--dry-run` **不安装**：不写入任何 site-packages、不改变当前解释器环境 | **已核实（pip 语义）** | 仍须以 2A 执行时的 `pip freeze`/site-packages 前后对照留证 |
| `--report <file>` 生成 JSON，含 `download_info.url` 与 `archive_info.hashes`（供哈希比对） | **已核实（pip ≥22.2 语义）** | 2A 执行时保存报告全文与 `pip install --help` 佐证 |
| **dry-run/report 是否会真正下载分发包**（完整 wheel，还是仅取 PEP 658 元数据 `.metadata`），取决于索引是否提供元数据与 pip 版本 | **未核实（本次仅联网读取官方文档，未实测）** | **2A 执行时必须实测并留证**：①`-v` 详细日志中的 HTTP 记录；②临时目录/缓存观测（配合 `--no-cache-dir` 使临时物不残留）；③pip 日志中的下载条目；④目的地址留证。**结论以实测为准，本方案不预设** |
| `--report` 与 `--dry-run` 的配合（是否需要同时给出） | **未核实** | 以 2A 执行时 `pip install --help` 的原文为准；**若不确定则恒显式加 `--dry-run`** |
| 解析是否会选择 sdist | **未核实**（取决于包是否有匹配 wheel） | **强制 `--only-binary=:all:`**：出现"只能用 sdist"的包 → **停止**（用户禁止 sdist） |

**（b）硬性纪律（无论上述不确定项如何）**

1. **必须显式使用 `--dry-run`**（不落盘安装）；**必须 `--only-binary=:all:`**；
   **建议 `--no-cache-dir`**（避免 wheel 残留于共享缓存，便于"临时物零残留"核验）；
   **不得**使用 `--target`/`--prefix` 等真实写入模式。
2. **不得**将 `2A-report.json` 作为锁文件使用。理由（**明确登记**）：
   - report JSON **不是** pip 可消费的安装输入，无法直接用于 `--require-hashes`；
   - 它是**解析结果快照**，不含"钉版 + 逐包哈希"的声明式约束，也不能表达
     `--only-binary`、无 extras 等**安装纪律**；
   - 其哈希来自索引元数据，**须与实际获取的工件逐项复核**后才可作为锁定依据；
   - 因此必须由 report **转换**为 `lock.txt`（+ `lock-manifest.csv`），转换须
     **可复核**（见 §2A-4）。
3. dry-run 阶段的网络行为**只允许**访问 §2A-2 的允许域名；任何其他目的地 → 停。

### 2A-4 锁定清单生成（report → lock.txt 的确定性转换）

| 步骤 | 内容 |
|---|---|
| T1 | 命令：`"$PY" -m pip install --dry-run --report 2A-report.json --only-binary=:all: --no-cache-dir --require-hashes` **不能直接用**（`--require-hashes` 需已有哈希约束）→ 首轮解析**不加** `--require-hashes`，只加 `--dry-run --report --only-binary=:all:`，**并固定顶层要求**：`claude-agent-sdk==0.2.168`（**不装 extras**） |
| T2 | 由 report 生成 `lock.txt`：对 `install` 数组每一项输出 `"<name>==<version> --hash=sha256:<sha256>"`；**排序稳定**（按包名）；**含全部依赖**（传递闭包），**不含** extras 包 |
| T3 | 生成 `lock-manifest.csv` 侧车（§2A-1），**许可证列必填**（用户要求 + 清单 §B 要求）；`requires_python` 与 win_amd64 轮子可用性必填 |
| T4 | 交叉校验：①锁文件与 report 的包集合**逐项一致**（数量/名字/版本）；②与 §4.2（阶段 1 核验的一级依赖）**一致性检查**（不一致须解释：如版本更新）；③`mcp-types==2.3.0` 必须与 `mcp` 声明一致；④**无** GitPython/pygit2/Dulwich/ORM/DB；⑤`rpds-py`/`cryptography`/`pywin32` **有 win_amd64 轮子**，否则停 |
| T5 | **独立性复核**：对每包哈希与 PyPI 索引 JSON 的 `digests.sha256` **逐项对比**（同一来源的第二次独立读取）；不一致 → 停 |
| T6 | 输出**供人工审核**的锁定清单定稿（+ 与 §3.1 的 SDK wheel 哈希比对） |

### 2A-5 Wheel 获取（获取准备与获取本身 —— **须明确授权**）

| 项 | 内容 |
|---|---|
| 目标 | 将 `lock.txt` 中**全部**包的实际 wheel 落到 `wheelhouse/`（**获取**行为 = 下载；**本方案不授权执行**） |
| 方式 | ①`pip download --no-deps --require-hashes -r lock.txt -d wheelhouse`（**不加 `--dry-run`**，即真实下载；仍 `--only-binary=:all:`）；或 ②按 `files.pythonhosted.org` 的 URL 逐个人工获取。**推荐 ①**（可强制逐包哈希） |
| 获取即核验 | 每包下载后立即 `sha256sum` 与 `lock.txt`/`lock-manifest.csv` 比对；**任一不符 → 立即停止、留证、报告**（不得删除已获工件，保留为证据） |
| **SDK wheel 重点** | `claude_agent_sdk-0.2.168-py3-none-win_amd64.whl` 的 sha256 必须等于 `ed1814b0…`；**体积应约 117 MB**（若明显偏小 → 高度怀疑拿到 sdist 或损坏 → 停） |
| sdist 防线 | wheelhouse 内**不得出现任何 `.tar.gz`/`.zip` 源码包**；出现即停 |
| 证据 | 命令全文、每包哈希、下载时间/大小、目的地址记录、退出码、文件夹清单 |
| **本方案不授权** | 不授权执行本节任何下载动作 |

## 3. 阶段 2B 执行清单（断网离线安装 + 全量校验）

### 3B-1 前置检查

| # | 检查项 | 判定 |
|---|---|---|
| B0-1 | 2A 交付物**已经人工审核**（锁定清单 + wheelhouse + 哈希复核记录） | 未审核 → 停 |
| B0-2 | `wheelhouse/` 完整性：包数 = 锁文件行数；**零 sdist**；全部 wheel 哈希与锁文件一致 | 不符 → 停 |
| B0-3 | 解释器 64 位与路径（同 A0-1/A0-2）；venv 目标路径在执行根内 | 不符 → 停 |
| B0-4 | 本机**无托管设置**（同 A0-6） | 存在 → 停并报告 |
| B0-5 | （**2026-10-19 修订**：取消人工断网；无需断网前置）——离线安装由 pip 层 `--no-index --find-links` 保证零索引访问 | — |

### 3B-2 安装步骤（**离线**）

```
① "$PY" -m venv <执行根>/venv           # 或 --copies；记录 venv 内 sys.executable
② <执行根>/venv/Scripts/python.exe -c 检查 64 位与路径（与 A0 同判据）
③（**2026-10-19 修订**）不执行 OS 层断网；pip 层用 `--no-index --find-links` 保证不访问在线索引（宿主网络可保持连接）
④ venv pip install --no-index --find-links <wheelhouse> --require-hashes -r lock.txt
     （等价强制：不得回退到索引；若 pip 报"无法在 find-links 中满足" → 停）
⑤ pip freeze 全文留存，与 lock.txt 逐项对照
⑥ 复演校验：venv pip install --dry-run --no-index --find-links <wheelhouse> --require-hashes -r lock.txt  (期望"已满足"，零网络)
⑦ 哈希复核：wheelhouse 内全部 wheel sha256 再算一遍，与锁文件比对
⑧ 静态核验（§3B-3 与 §3B-4）——不运行 SDK/CLI
```

### 3B-3 静态核验（**不运行** SDK/CLI；离线）

| # | 项 | 方法 | 判定 |
|---|---|---|---|
| S1 | 已安装版本 | 读 venv 内 `claude_agent_sdk/__init__.py`/`_version` 或 dist-info `METADATA`（**纯文件读取**） | 期望 `0.2.168` |
| S2 | **P6 语义项复核** | 离线读 venv 内 `types.py`，逐字确认 `tools`/`allowed_tools`/`disallowed_tools`/`skills`/`plugins`/`mcp_servers`/`strict_mcp_config`/`setting_sources`/`permission_mode`/`hooks`/`env`/`cwd`/`max_turns`/`task_budget`/`max_budget_usd`/`max_tokens`(应 ABSENT)/`thinking`(应 PRESENT；`ThinkingConfig` 三态)/`max_thinking_tokens`(应 PRESENT，已弃用)/`sandbox` 与 §A/§I 记载一致 | 任一不符 → 停并更新记载 |
| S3 | 安装物清单 | 列出 venv `site-packages` 顶层分布，与锁文件逐项对照（**无多余包**） | 多余包 → 停 |
| S4 | 写入面核查 | 确认安装仅在执行根内产生写入；真实项目仓库 status 前后 byte-compare；`%LOCALAPPDATA%`/`~/.claude` 等**是否被创建**（只记录，不改动） | 计划外写入 → 停并报告 |
| S5 | 依赖红线复核 | 安装后 site-packages 内**确实不存在** GitPython/pygit2/Dulwich/ORM/DB | 存在 → 停 |

### 3B-4 **内嵌 CLI 的版本与哈希核验**（用户明确要求；离线优先）

| # | 项 | 方法 | 判定 |
|---|---|---|---|
| C1 | **定位内嵌 CLI** | 解包/读取已安装 wheel 内容（`python -m zipfile -l <wheel>`，或直接读 venv 内文件树），找出捆绑的 CLI 可执行文件路径。**wheel 内布局本次未核实** → 以实测为准并记录 | 找不到 CLI → 停并报告（与"CLI 随 wheel 捆绑"的既有推断矛盾） |
| C2 | **版本** | 优先**静态**读取（版本文件 / `package.json` 等）；若静态不可得，则记"需执行 `claude --version`"（→ **属"运行 CLI"，须在 2B 批准中单独授权**） | 期望与 release 记录 **`2.1.301`** 一致；不一致 → 记录并以实测为准 |
| C3 | **哈希（本地计算）** | `sha256sum`（或 PowerShell `Get-FileHash -Algorithm SHA256`）计算内嵌 CLI 可执行文件的 sha256，**入证据** | 记录值（基线） |
| C4 | **官方溯源比对（需 `downloads.claude.ai` 授权）** | 取 `https://downloads.claude.ai/claude-code-releases/2.1.301/manifest.json` + `.sig`，`gpg --verify`（指纹 `31DD DE24 DDFA B679 F42D 7BD2 BAA9 29FF 1A7E CACE`），再比对 `platforms.<win32 平台>.checksum` 与 C3 值 | 签名无效/哈希不符 → **停并报告**；**未获授权** → 记为「哈希已记录、**未溯源比对**」 |
| C5 | **Windows 代码签名（离线，F-5）** | `Get-AuthenticodeSignature <claude.exe>`，期望签名者 "Anthropic, PBC" | 无签名/签名者不符 → 停并报告 |
| C6 | **额外下载/更新器静态检查** | ①列出 wheel 内全部可执行/脚本文件；②在 wheel 内文本文件与二进制中检索更新/下载相关字符串（如 `downloads.claude.ai`、`install.ps1`、`autoupdate`、`DSABLE_UPDATE` 等）；③检查是否有随包 `.ps1`/`.sh`/安装器 | 发现**运行期自动下载/更新**迹象 → 记录，并按 §5 处置 |
| C7 | **许可与条款** | 记录 wheel/仓库内 CLI 许可与条款文件（若随包存在）；**CLI 官方条款页在 `code.claude.com`，允许只读访问 → 若已获取则记录版本与核验日** | 未取得 → 保持「未核实项」 |

### 3B-5 2B 的停止条件（命中任一立即停）

依赖/哈希不符 · 出现 sdist · 需要回退到索引（即本地 wheel 不满足）· **计划外网络访问
（宿主可在线，但 pip 或安装相关的任何在线索引/URL/下载均停止）** · 计划外写入 ·
内嵌 CLI 哈希/签名不符 · 依赖红线命中 · 托管设置存在 ·
任何"本方案未授权"的动作（含**运行 SDK/CLI、import SDK、调用 query**）。

## 4. 网络隔离验证方案（阶段 2：受控获取 + 断网安装）

> 用户裁定：**不接受**普通代理 + hosts + 阶段断网**冒充不可绕过的隔离**；
> 阶段 2 采用**受控获取 Wheel + 本地离线安装**；**不得修改宿主机全局防火墙**。
> 故本节**不主张**任何"不可绕过"性质，仅规定**可验证的隔离操作与证据**。
>
> **2026-10-19 修订**：阶段 2B 取消「安装前物理断网」（见 §4.2）；允许宿主网络保持连接，
> 以 pip 层 `--no-index --find-links` 保证不访问在线索引。

### 4.1 分层设计（按阶段）

| 阶段 | 联网状态 | 隔离机制 | 可验证性 |
|---|---|---|---|
| 2A（解析/获取） | **受控联网**（仅 §2A-2 域名） | 受控获取：固定顶层要求 + `--only-binary` + 逐包哈希即时核验 + 目的地址留证 | 中等（联网本身不可"证明零越界"，只能靠**日志留证 + 异常即停**）**——本方案不称其为隔离** |
| 2B（安装） | **本地离线安装（宿主网络可保持连接）**【2026-10-19 修订】 | **仅 pip 层**：`--no-index --find-links <wheelhouse>`（pip 不使用任何索引 → 不发起任何 HTTP 请求）；**是否已取消 OS 层物理断网** | 强（pip 层可由命令语义 + 日志零 HTTP 证明；「计划外网络访问 / pip 回退索引」为停止条件） |

### 4.2 隔离实现（**2026-10-19 修订：取消物理断网**）

> **修订（用户 2026-10-19 裁定）**：取消阶段 2B「安装前必须物理断网」的条件，允许宿主机
> 保持网络连接；离线安装由 **pip 层 `--no-index --find-links`** 单一保证（不访问任何在线
> 索引/URL）。**仍禁止**：在线包索引、下载新依赖、源码构建、运行 Claude CLI、调用模型 API。
> 出现**计划外网络访问 / 依赖异常 / 哈希不一致 / 越界写入** → 立即停止。

| 手段 | 做法 | 证据 | 局限（如实登记） |
|---|---|---|---|
| **pip 层（唯一隔离面）** | `--no-index --find-links <wheelhouse> --require-hashes --only-binary=:all:` | 命令原文 + pip 日志**零 HTTP 条目** + 成功安装（全部来自本地 wheel） | pip 层只约束 pip；**宿主网络保持连接**（修订后不再断网），故不宣称「无网环境」，也不把此表述为不可绕过隔离 |
| **明确取消** | ~~OS 层人工物理断网~~ | — | 2026-10-19 取消 |
| **明确不用** | 修改宿主机**全局防火墙**规则（仍禁止）；普通代理/hosts 冒充隔离 | — | — |

**新旧边界差异（一句话）**：旧 =「pip 层 + OS 层物理断网」双层、且「安装前须确认断网，否则停止」；
新 =「仅 pip 层 `--no-index --find-links`」、宿主可在线，任何在线索引访问/回退一律列为停止条件。

### 4.3 验证判据（阶段 2）

1. **2B 期间零出站**：pip 日志与任何已记录证据中**无 HTTP/HTTPS 访问**；
2. **安装成功且逐包哈希通过**（`--require-hashes` 未回落）；
3. **零在线索引访问**：pip 日志与证据中无任何在线索引/URL 请求（`--no-index --find-links` 生效；不要求 OS 断网留证）；
4. **零计划外写入**（真实仓库 status 前后一致；执行根外无新增）；
5. **内嵌 CLI 版本与哈希已记录**（§3B-4）；
6. 任一判据不成立 → **不得**宣告阶段 2 通过。

### 4.4 阶段 3 的出站安全边界（**另行实施与验证；本节仅登记要求与候选**）

**要求（用户裁定）**：阶段 3 需要的是**不可绕过的出站安全边界**；普通代理 +
hosts + 阶段断网**不能满足**该要求。**当前状态：未选定、未实施、未验证。**

**候选（全部未验证；仅登记，供后续单独裁定）**：

| # | 候选 | 为何可能满足"不可绕过" | 关键未决问题 |
|---|---|---|---|
| W1 | **虚拟化/容器级隔离**（Hyper‑V、Windows Sandbox、Docker/WSL2 容器）：Python+CLI 在隔离环境内运行，网络策略由隔离层强制 | 边界由**宿主/虚拟化层**强制执行，环境内进程无法改网络策略 | 与 ADLL 本机工具链（Git/Windows 路径）的兼容性；WSL2 下 CLI 沙箱可用（F-6）但 Python 侧架构需重设计；隔离层自身配置须证明 |
| W2 | **WSL2 + CLI 自带 OS 沙箱**（`sandbox.enabled` + `network.allowedDomains` + `failIfUnavailable: True`，F-6/F-8/F-9） | 官方声明该沙箱由**操作系统**强制执行；`failIfUnavailable` 可避免"沙箱不可用却继续运行" | 仅覆盖 shell 命令（F-7）；**原生 Windows 不支持**（F-6）；SDK 与 CLI 的跨环境编排复杂 |
| W3 | **专用受限账户/环境 + 无网络**（完全离线执行 + 人工窗口） | 离线态下无出站 | 属人工纪律，**不是技术边界**；对"需要真实 API 调用"的阶段 3 不适用 |
| W4 | ~~Windows 防火墙出站规则~~ | — | **用户裁定排除**（不得修改宿主机全局防火墙） |

**阶段 3 隔离的验证标准（须在方案获批时一并确认）**：
①在隔离环境内**实测**双向用例（允许目的地 `api.anthropic.com` 可达 / **非白名单目的地被真实拒绝**）；
②证明**无旁路**（无直连 IP、无代理旁路、无额外网络接口/适配器可绕过）；
③证据含隔离层配置、探测结果、宿主侧网络状态；
④**禁止**把任何未验证手段表述为等价替代。

## 5. 自动更新与"额外下载"风险处置（用户明确要求检查）

| # | 风险 | 事实依据 | 处置（**阶段 2B 后、阶段 3 前**落实；本轮不执行任何配置变更） |
|---|---|---|---|
| R1 | **原生安装自动后台更新**（本 CLI 为随 wheel 的原生二进制） | F-1 | ①设 **`DISABLE_UPDATES`**（阻断全部更新路径，含手动，F-2）；②辅以 **`DISABLE_AUTOUPDATER=1`**（仅停后台检查）；③`claude doctor` 的 `Auto-updates` 行应为 `disabled (… DISABLE_AUTOUPDATER)`（F-2）→ **该核验需运行 CLI，属单独授权动作** |
| R2 | 更新/版本检查出站 `downloads.claude.ai`（及旧版 `storage.googleapis.com`） | F-3 | 与 §4.4 的边界设计联动；**列入阶段 3 阻断清单** |
| R3 | 遥测/错误上报（Datadog 两主机）、Gerrit 查询 | F-22 | 设 `DISABLE_TELEMETRY=1`（或 `DO_NOT_TRACK=1`）、`DISABLE_ERROR_REPORTING=1`、**`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`** |
| R4 | claude.ai MCP 连接器（`mcp-proxy.anthropic.com`） | F-22 | `ENABLE_CLAUDEAI_MCP_SERVERS=false` / `disableClaudeAiConnectors`；并与 `strict_mcp_config=True`、`mcp_servers={}` 叠加 |
| R5 | Artifact 读取（`*.frame.claudeusercontent.com`） | F-22 | `CLAUDE_CODE_DISABLE_ARTIFACT=1` / `enableArtifact: false` |
| R6 | 插件安装/市场（`github.com`、`registry.npmjs.org`、`storage.googleapis.com`） | F-3/F-22 | 不装插件（`plugins=[]`）；不使用 `--plugin-url`/`--plugin-dir`；`strict_mcp_config=True` 阻止外部 MCP 发现 |
| R7 | changelog 后台抓取（`raw.githubusercontent.com`） | F-23 | **非交互（SDK/`-p`）会话不抓**（官方声明）→ 仍需列入阻断清单以覆盖交互式意外 |
| R8 | **托管设置无视 `setting_sources` 强制加载** | F-10/F-25 | A0-6/B0-4 检查 + 若存在则停 |
| R9 | **沙箱在原生 Windows 不可用**，且 Python SDK 默认「沙箱启动失败仍继续运行」 | F-6/F-8 | **不得宣称本机有 CLI/OS 沙箱**；**在 `failIfUnavailable` 的传递机制核实前，不得依赖该设置、不得宣称"沙箱不可用时会停止"**（用户勘误）；若未来使用 `sandbox`，须先以锁定版本的**离线源码/行为证据**确认该安全设置的有效传递方式 |
| R10 | `env` 非白名单（继承父进程） | F-18 | 干净环境在**宿主启动层**建立（既有纪律不变） |
| R11 | `skills` 会自动加入 `Skill` 到 `allowed_tools`（F-14） | F-14 | 若设 `skills=[]`，**"是否仍触发该自动加入"未核实** → 阶段 2B 后离线确认；阶段 3 前以行为证据确认 |

## 6. 证据产物清单（2A / 2B 各自）

| 阶段 | 产物 |
|---|---|
| **2A** | 环境与解释器清单（64 位/路径/版本/pip）· `pip install --help` 全文 · 命令全文与 pip 详细日志 · **目的地址记录** · `2A-report.json`（原始）· **`lock.txt`** · **`lock-manifest.csv`** · 每包哈希与 PyPI 索引 JSON 对照记录 · `wheelhouse/` 清单（文件名+大小+sha256）· 网络范围与异常记录 · （若授权）CLI manifest.json + .sig + gpg 验证输出 · 汇总行与 EXIT_CODE |
| **2B** | 2A 交付物审核记录 · venv 创建与解释器清单 · **断网状态留证**（前后网络状态、断开期间连接失败记录、操作者/时间）· 安装命令与完整日志（**零 HTTP 证明**）· `pip freeze` 与锁文件逐项对照 · 复演校验输出 · wheelhouse 哈希复核 · **内嵌 CLI 定位/版本/哈希/代码签名/manifest 比对**记录 · 依赖红线与托管设置检查 · site-packages 清单 · 执行根外零写入抽查（真实仓库 status 前后 byte-compare）· 汇总行/STOP 行/EXIT_CODE · 全量文件清单与 mtime 全序 |

## 7. 未核实项与遗留风险（不得升格为事实）

| # | 未核实项 | 处置 |
|---|---|---|
| 1 | pip `--dry-run/--report` 是否下载完整包（依赖 PEP 658 元数据） | 2A 执行时实测留证（§2A-3） |
| 2 | `--report` 是否必须与 `--dry-run` 同时给出 | 以 2A 时 `pip install --help` 原文为准 |
| 3 | **wheel 内 CLI 的文件布局与版本文件位置** | §3B-4 C1/C2 实测 |
| 4 | 内嵌 CLI 哈希与官方签名 manifest 是否一致 | §3B-4 C4（**需 `downloads.claude.ai` 授权**） |
| 5 | `DISABLE_UPDATES` 在**随 SDK 捆绑的 CLI**上是否等效生效 | 需**运行 CLI** 核验（单独授权）；未核验前**不得**宣称更新已被阻断 |
| 6 | `skills=[]` 是否仍自动把 `Skill` 加入 `allowed_tools`（F-14 的触发条件） | 2B 后离线 + 阶段 3 前行为核实 |
| 7 | `task_budget` 的最低 `total` 与在 SDK 侧的实际生效方式（F-15 只给出 `{"total": N}`） | 阶段 3 前核实 |
| 8 | **CLI 使用条款**（`code.claude.com` 上是否有随包条款、版本与核验日） | §3B-4 C7；未取得则保持未核实 |
| 9 | 二级依赖许可证与 win_amd64 轮子可用性 | 2A 的 `lock-manifest.csv` 逐项填写 |
| 10 | 阶段 3 的隔离方案（W1/W2）可行性、兼容性与验证结果 | **另行实施与验证**；本方案不含结论 |
| 11 | 沙箱在 WSL2 下对本项目工作流的适用性 | 若走 W1/W2 须单独评估 |
| 12 | 内嵌 CLI 是否有运行期附加下载 | §3B-4 C6 静态检查 + 阶段 3 阻断；未核验前不得宣称无 |

## 8. 明确不做（本方案与本轮）

1. 不下载 wheel/CLI/安装包；不创建 venv；**不安装或运行 SDK/CLI**；不发起 AI 调用；
   不使用 API Key；不执行 FV-2～FV-7。
2. 不修改本机任何网络配置或**全局防火墙规则**；不实施 §5 的任何配置变更
   （仅为待落实清单）。
3. 不修改宪章、spec.md、AGENTS.md、ADLL-Knowledge、既有 FV-0/V2/V2.1/V2.2/FS2
   证据与脚本；不清理 fixtures；不 Git Commit/Push；不进入业务编码阶段。
4. 不在文中把任何未验证手段（代理/hosts/断网/沙箱）表述为**不可绕过**的隔离，
   也不把"有限供应链风险"表述为生产级安全验证（用户裁定）。

## 9. 待批准项（供 2A/2B 分阶段授权引用）

| # | 待批准项 | 建议 |
|---|---|---|
| P-1 | **2A 执行**（联网解析 + 生成锁定清单；是否含真实 Wheel 获取） | 建议**先批"解析+锁定清单"**（可含 dry-run 的元数据取得），Wheel **获取**单独一批 |
| P-2 | **`downloads.claude.ai` 只读两文件授权**（manifest.json + .sig） | 建议批准（否则内嵌 CLI 只能记哈希、无法溯源） |
| P-3 | pip 选项集合（`--only-binary=:all:`、`--no-cache-dir`、`--dry-run`） | 建议按 §2A-3（b）固定 |
| P-4 | **2B 执行**（离线安装） | **须在审核 2A 交付物后**独立批准 |
| P-5 | 2B 内**是否允许执行 `claude --version` / `claude doctor`**（"运行 CLI"） | 建议**默认不允许**，优先静态核验；如需，单独列明并强制离线 |
| P-6 | 阶段 3 隔离候选（W1/W2）与验证标准 | 另行裁定（本方案仅登记） |
| P-7 | venv 具体参数（`--copies` 与否、venv 路径注入键名） | 建议 `--copies` 以显式固定解释器；路径经环境配置注入（AGENTS.md §3） |