# FV-1 阶段 1 —— 官方资料核验与版本准备记录（fv1-stage1-version-verification-record.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**Date**: 2026-10-18
**性质**: **阶段 1 授权范围内的只读核验记录**（未下载任何安装包、未安装依赖、
未创建 Agent、未访问模型 API、未使用 API Key）。**阶段 2 须单独审批。**
**授权依据**: 用户 2026-10-18 阶段 1 执行授权（J1 三阶段机制：阶段 1 官方资料
核验与版本准备 / 阶段 2 SDK 受控安装 / 阶段 3 首次真实模型调用；**本次仅批准
阶段 1**）。
**核验日**: 2026-10-18（所有外部事实均为该日只读取得；**版本敏感，阶段 2/3
须按锁定版本重核**，AGENTS.md §5.6）。

## 0. 授权范围与访问边界（本阶段严格遵守）

| 项 | 授权内容 | 本次执行情况 |
|---|---|---|
| 协议/方式 | **只读 HTTPS** | ✅ 全部为只读 GET；零写入远端；零下载安装包 |
| 白名单域名 | `platform.claude.com`、`github.com`、`api.github.com`、`raw.githubusercontent.com`、`pypi.org`、`www.anthropic.com` | ✅ 实际访问 4 个：`pypi.org`、`api.github.com`、`raw.githubusercontent.com`、`platform.claude.com`（`github.com`、`www.anthropic.com` **未使用**） |
| 重定向纪律 | **不得自动跟随白名单外重定向** | ✅ 未发生跨域重定向（见 §1 说明） |
| 明确不授权 | 下载 Wheel/CLI/安装包、安装依赖、创建实际 Agent、访问模型 API、使用 API Key | ✅ 均未执行 |
| C2-e | 仅作后续安装/运行阶段推荐；**不允许修改宿主机全局防火墙规则** | ✅ 未修改任何防火墙/网络配置（**已登记为约束，见 §6-5**） |
| 文档纪律 | 不得修改已批准需求、宪章、AGENTS.md、ADLL-Knowledge 或原始实验档案；不得 Git Commit/Push | ✅ 仅新增本记录（+ 清单 §A 核验结果登记）；无 Git 操作 |

## 1. 访问记录（透明留痕）

| # | URL | 目的 | 结果 |
|---|---|---|---|
| 1 | `https://pypi.org/pypi/claude-agent-sdk/json` | 包元数据 | ✅ 部分（**响应 766,682 字符，分块截断**，仅读到前 100,000 字符） |
| 2 | `https://api.github.com/repos/anthropics/claude-agent-sdk-python/releases/latest` | 最新发行版 | ✅ 完整 |
| 3 | `https://api.github.com/repos/anthropics/claude-agent-sdk-python` | 仓库/许可证元数据 | ✅ 完整 |
| 4 | `https://raw.githubusercontent.com/…/main/pyproject.toml` | 依赖与打包声明 | ✅ 完整 |
| 5 | `https://pypi.org/pypi/claude-agent-sdk/0.2.168/json` | 指定版本分发物与哈希 | ✅ 完整 |
| 6 | `https://raw.githubusercontent.com/…/main/README.md` | 安装/CLI 捆绑/条款 | ✅ 完整（**回复经摘要，非逐字全文**，见 §10-1） |
| 7 | `https://api.github.com/repos/…/contents/scripts` | 构建脚本清单 | ✅ 完整 |
| 8 | `https://raw.githubusercontent.com/…/main/src/claude_agent_sdk/types.py` | 参数定义 | ⚠️ 部分（文件 106,384 字符，**两次分块截断**） |
| 9 | `https://platform.claude.com/docs/en/about-claude/models/overview` | 模型清单 | ✅ 完整 |
| 10 | `https://platform.claude.com/docs/en/about-claude/pricing` | 价格 | ✅ 完整（输出另存本地 49.2KB 后完整读取） |
| 11 | `https://raw.githubusercontent.com/…/main/scripts/download_cli.py` | CLI 获取来源与时机 | ✅ 完整（摘要） |
| 12 | `https://pypi.org/pypi/anyio/json`、`/mcp/json`、`/jsonschema/json` | 依赖元数据 | ⚠️ mcp/jsonschema 文件哈希被截断 → 改用指定版本端点（#14/#15） |
| 13 | `https://pypi.org/pypi/sniffio/json`、`/typing-extensions/json` | 依赖元数据 | ✅ 完整 |
| 14 | `https://pypi.org/pypi/mcp/2.3.0/json` | 指定版本哈希 | ✅ 完整 |
| 15 | `https://pypi.org/pypi/jsonschema/4.26.0/json` | 指定版本哈希 | ✅ 完整 |
| 16 | `https://raw.githubusercontent.com/…/main/CHANGELOG.md` | 版本变更 | ✅ 完整（摘要） |
| 17 | `https://raw.githubusercontent.com/…/main/src/claude_agent_sdk/types.py`（第二段） | 类型字面量 | ⚠️ 见 §7 未取得项 |

**跨域重定向说明（如实登记）**：请求 #9 的路径为
`/docs/en/about-claude/models/overview`，返回页面的规范 `url` 字段为
`https://platform.claude.com/docs/en/models/overview`——**同域**，属站点内部
规范 URL，**非跨域重定向**，未产生白名单外目的地。**未发生任何白名单外跳转**。

**本地只读检查（非联网、非安装）**：为确定阶段 2 的 venv 基础解释器，执行了
`python --version`、`py -0p`、`conda env list`、`where python`、`sha256sum --version`、
`curl --version` 等只读命令（结果见 §4-5）。**未安装、未修改任何环境**。

## 2. 版本候选（SDK 与捆绑 CLI）

| 项 | 核验结果 | 来源 |
|---|---|---|
| **SDK 包名** | `claude-agent-sdk`（PyPI） | #1/#4 |
| **候选版本** | **`0.2.168`**（最新发行版；`prerelease=false`） | #1/#2/#4（三处一致：PyPI `info.version`、`pyproject.toml` `version`、GitHub release tag `v0.2.168`） |
| 发布时点 | sdist 上传 `2026-10-15T20:20:43.683793Z`；GitHub release `published_at = 2026-10-15T20:22:18Z` | #2/#5 |
| 仓库状态 | 默认分支 `main`；`archived=false`；`pushed_at=2026-10-16T20:54:47Z`；stars 8,293 | #3 |
| **捆绑 Claude Code CLI** | **`2.1.301`** | #2 发布正文「Updated bundled Claude CLI to version 2.1.301」＋ #16 CHANGELOG 0.2.168 |
| CLI/SDK 耦合 | **每版 SDK 跟一轮 CLI 版本**：0.2.163→2.1.286、0.2.164→2.1.292、0.2.165→2.1.294、0.2.166→2.1.299、0.2.167→2.1.300、0.2.168→2.1.301 → **锁定 SDK 即锁定 CLI**（二者不可分开选版） | #16 |
| 最低 Python | `>=3.10`（PyPI `requires_python`、`pyproject` `requires-python`、wheel 元数据三处一致） | #1/#4/#5 |
| 备选版本 | **无**（本阶段未评估降级候选）。0.2.168 若在阶段 2/3 失败 → 停止、报告，**降级须重新授权**（不得自行换版） | — |

## 3. 分发物与哈希（阶段 2 安装对象）

### 3.1 本机目标分发物（Windows x86_64）

| 项 | 值 |
|---|---|
| 文件名 | `claude_agent_sdk-0.2.168-py3-none-win_amd64.whl` |
| 类型 / Python 标记 | `bdist_wheel` / `py3` |
| 大小 | **117,292,475 字节**（≈117 MB） |
| **sha256** | **`ed1814b0dd1c113bdaf3e51e6a67aa5b96b8f5c5839a43aeb6ae1e6ed23a5b35`** |
| 上传时间 | `2026-10-15T20:21:07.053548Z` |
| requires_python | `>=3.10` |

### 3.2 同版本其他分发物（登记完整性；本机不使用）

| 文件名 | 类型 | 大小（字节） | sha256 |
|---|---|---|---|
| `…-py3-none-macosx_11_0_arm64.whl` | wheel | 104,355,641 | `2ef1e7fc442c5abdc1e698027bf1b5faa8ea2130134a14364e2ae3c53bf31fdd` |
| `…-py3-none-macosx_11_0_x86_64.whl` | wheel | 109,438,860 | `653fc7bbe56630e6ddd9601a7cfe50586667e74102da3fb90571456c63655a62` |
| `…-py3-none-manylinux_2_17_aarch64.whl` | wheel | 114,030,032 | `77ae66b10edfd07b6ea3dec2af106ad47a9d616f8eb52d4f9b385e1b00bb2a27` |
| `…-py3-none-manylinux_2_17_x86_64.whl` | wheel | 114,443,626 | `be197be92549909ec62a2cee04c27f4b0a38c80f723735538a3efc352507f81d` |
| `claude_agent_sdk-0.2.168.tar.gz` | **sdist** | **371,591** | `80388054a09c137d76fc29caa6e46bc90d2ae2ef09fac5ee1c38fc36d2762fda` |

**哈希来源**：PyPI JSON API 的 `urls[].digests.sha256`（证据 #5）。
该来源属**第一方索引哈希**，与 `--require-hashes` 所使用的索引哈希同源。

### 3.3 安装必须以 **wheel** 进行（不得用 sdist）

- **证据（脚本自述）**：`scripts/download_cli.py` 模块 docstring
  「This script is run during the wheel build process to fetch the Claude Code
  CLI」，`__main__` 注释「This script runs as a build step」（#11）。
- **证据（体积）**：win_amd64 wheel 117 MB vs sdist **371 KB**（相差约 315 倍）
  → 与「CLI 二进制随 wheel 分发」一致。
- **证据（官方声明）**：README「The Claude Code CLI is automatically bundled with
  the package - no separate installation required!」（#6）。
- **结论**：**SDK 安装（wheel 路线）预期只需 PyPI 访问**，不需要安装期访问
  `claude.ai`；**sdist 路线会触碰构建期 CLI 获取路径（`claude.ai`），超出
  阶段 2 授权网络范围 → 禁止**。
- **登记为推断（未实测）**：「wheel 安装不触发 claude.ai」为**基于上述证据的
  推断**，尚未实测；阶段 2 须以「网络阻断 + 目的地址留证」验证，若出现
  `claude.ai` 等计划外目的地 → **立即停止**（既有 §C 规则）。

## 4. 依赖与哈希来源

### 4.1 直接依赖（权威声明，两处一致）

`mcp>=1.23.0,<3.0.0`、`jsonschema>=4.20.0`、`anyio>=4.0.0`、`sniffio>=1.0.0`、
`typing_extensions>=4.0.0; python_version<'3.11'`（#4 `dependencies` 与 #1
`requires_dist` 一致）。

**extras 一律不安装**：`dev`（pytest/anyio[trio]/pytest-cov/mypy/ruff）、
`examples`（boto3/moto/redis/fakeredis/asyncpg）、`otel`（opentelemetry-api）。

### 4.2 一级依赖：核验日（2026-10-18）最新版本与首方哈希

| 包 | 最新版本 | requires-python | 许可证 | wheel sha256 | sdist sha256 |
|---|---|---|---|---|---|
| `anyio` | 4.15.1 | `>=3.10` | MIT | `6152fdbbf9a77fdec97731721bebf7c4c44f7c29b424b0065826173efc7ed101` | `9f28306018cbd6d329e64a36d58256edff76dd996fe423bc957326e578b82a94` |
| `sniffio` | 1.3.1 | `>=3.7` | MIT OR Apache-2.0 | `2f6da418d1f1e0fddd844478f41680e794e6051915791a034ff65e5f100525a2` | `f4324edc670a0f49750a81b895f35c3adb843cca46f0530f79fc1babb23789dc` |
| `typing-extensions` | 4.16.0 | `>=3.9` | PSF-2.0 | `481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8` | `dc983d19a509c94dba722ee6abd33940f7c05a89e243c47e907eb4db6f1a43e5` |
| `mcp` | 2.3.0 | `>=3.10` | MIT | `dd0c44c089d16453e8ae31a3877a0054d7a2314caaa81f5e0541b9b1734b2377` | `8b147a50441cf059dc88c684e0aeed3687f0aa0f39c6cde7b90330effd2b34d8` |
| `jsonschema` | 4.26.0 | `>=3.10` | MIT（`license_expression`） | `d489f15263b8d200f8387e64b4c3a75f06629559fb73deb8fdfb525f2dab50ce` | `0c26707e2efad8aa1bfc5b7ce170f3fccc2e4918ff85989ba9ffa9facb2be326` |

### 4.3 二级及更深依赖（由一级 `requires_dist` 核验得出的名字集合）

| 来源包 | 引入的下一级（原文条件保留） |
|---|---|
| `mcp` 2.3.0 | `mcp-types==2.3.0`、`httpx2>=2.10.0`、`pydantic>=2.12.0`、`pyjwt[crypto]>=2.10.1`、`python-multipart>=0.0.9`、`sse-starlette>=3.0.0`、`starlette>=0.27`（py<3.14）/`>=0.48.0`（py≥3.14）、`uvicorn>=0.31.1`（非 emscripten）、`opentelemetry-api>=1.28.0`、`typing-inspection>=0.4.1`、`typing-extensions>=4.13.0`、`anyio>=4.9`（py<3.14）/`>=4.10`（py≥3.14）、`jsonschema>=4.20.0`、**`pywin32>=311; sys_platform=="win32"`** |
| `jsonschema` 4.26.0 | `attrs>=22.2.0`、`jsonschema-specifications>=2023.03.6`、`referencing>=0.28.4`、`rpds-py>=0.25.0` |
| `anyio` 4.15.1 | `idna>=2.8`、`typing_extensions>=4.16.0; python_version<"3.15"`、**`exceptiongroup>=1.0.2; python_version<"3.11"`** |
| `sniffio` / `typing-extensions` | 无依赖（叶子） |

**二级集合汇总（名字级）**：`mcp-types`、`httpx2`、`pydantic`、`pydantic-core`、
`annotated-types`、`pyjwt`（+ `cryptography`）、`python-multipart`、`sse-starlette`、
`starlette`、`uvicorn`（+ `click`、`h11`）、`opentelemetry-api`、`typing-inspection`、
`attrs`、`jsonschema-specifications`、`referencing`、`rpds-py`、`idna`、`pywin32`（win32）、
`exceptiongroup`（仅 py<3.11）、以及 `httpx2` 自身的传递依赖（`httpcore`/`certifi`/
`idna`/`anyio` 等，**待解析器确定**）。

### 4.4 完整解析树与逐包哈希：**本阶段未锁定**（如实说明）

- **原因（技术性，非疏漏）**：精确版本由 pip 解析器按**实际选用的 Python 版本**
  与约束（如 `starlette`/`anyio` 的 `python_version` 分支）决定；不同解释器会
  产生不同的钉版集合。本阶段（只读资料核验）不具备解析器。
- **阶段 2 的权威生成方式（已写入安装清单 §9）**：
  `python -m pip install --dry-run --report <file>.json claude-agent-sdk==0.2.168`
  → 生成含**逐包 `download_info.url` + `archive_info.hashes.sha256`** 的完整锁定清单，
  经批准人确认后以 `--require-hashes` 安装。
- **哈希来源统一**：PyPI JSON `digests.sha256`（本记录 §4.2 即该来源）或
  `--require-hashes` 模式使用的同源索引哈希。
- **本阶段实际价值**：候选集合 + 首方哈希来源 + 生成程序 + 红线核对（§4.6）。

### 4.5 本机解释器事实（只读检查，2026-10-18）

| 解释器 | 版本 | pip | 说明 |
|---|---|---|---|
| `D:\wo\miniconda3\python.exe`（base，**PATH 首位**） | 3.10.12 | 23.1.2 | conda base；**不建议**作 venv 基础（污染面） |
| `D:\wo\python\Python312\python.exe` | **3.12.10** | 26.2.1 | 满足计划「Python 3.11+」的**唯一**本机解释器 |
| `D:\wo\python\python-3.10\python.exe` | 3.10（具体补丁号未取） | 未取 | 满足 `>=3.10` 但非 3.11+ |
| conda 命名环境 | `D:\wo\conda_envs\{Alpha,d2l,openai-cookbook,paperlab,weather,xarray}` | — | 各有用途，**不得**作 venv 基础 |
| 本机工具 | `sha256sum`（coreutils 8.32）、`curl` 8.14.1（Schannel） | — | 可用于阶段 2 的 wheel 哈希核验（`pip` 亦自带哈希校验） |

**待批准裁定项 D-PY**：阶段 2 的 venv 基础解释器选 **Python 3.12.10**
（`D:\wo\python\Python312\python.exe`，符合计划「3.11+」）**还是** 3.10.12
（PATH 默认，但依赖树多引 `exceptiongroup` 且触发 `typing-extensions<3.11` 分支）。
**本记录不代为选定。**

### 4.6 依赖红线核对（对照清单 §B5）

| 红线 | 核对结果（一级 + 二级名字集合） |
|---|---|
| 无 GitPython / pygit2 / Dulwich | ✅ 树中**不存在** |
| 无 ORM | ✅ 不存在（`pydantic` 为校验库，非 ORM） |
| 无 DB 驱动 | ✅ 不装 extras 时不存在（`asyncpg`/`redis`/`boto3`/`moto`/`fakeredis` 仅属 `examples` extra） |
| 无原生重依赖风险 | ⚠️ **`rpds-py`（Rust 扩展）与 `cryptography`（pyjwt[crypto]）含二进制轮子** → 但均为**纯 wheel 依赖**（有 win_amd64/win_amd64 轮子则无需本地编译）；**须在阶段 2 锁定清单中确认提供 win_amd64 轮子**，否则会触发源码构建（需编译器）→ 若无法获得轮子 → **停止**（不自行引入构建链） |

## 5. 模型与价格核查结果（官方第一方来源）

### 5.1 模型存在性（#9 官方模型页，核验日 2026-10-18）

| 模型 | Claude API ID | 上下文 | 最大输出 | 默认 effort | 退役承诺 |
|---|---|---|---|---|---|
| Claude Haiku 5.5 | **`claude-haiku-5-5`** | 1M | 128K | `medium` | 不早于 **2027-10-07** |
| Claude Sonnet 5.5 | **`claude-sonnet-5-5`** | 1M | 128K | `high` | 不早于 2027-09-28 |
| （参考）Claude Opus 5.5 | `claude-opus-5-5` | 1M | 128K | `medium` | 不早于 2027-09-22 |

官方页明确：**从 4.6 代起，无日期的模型 ID 本身即为固定快照（pinned snapshot）**
（「Every Claude model ID is a pinned snapshot, including the dateless IDs used
from the 4.6 generation on」）→ **J2 推荐的 `claude-haiku-5-5` 存在且为固定快照**
（**满足 J2「使用前重核可用性」的核验要求**；实现可用性仍以阶段 3 首次调用为准）。

### 5.2 价格（#10 官方价格页，USD，Anthropic 第一方 API 费率）

| 模型 | 基础输入 /MTok | 5m 缓存写 | 缓存命中 | 输出 /MTok |
|---|---|---|---|---|
| Claude Haiku 5.5（**≤100,000 tokens 提示**） | **$0.10** | $0.125 | $0.01 | **$0.50** |
| Claude Haiku 5.5（**>100,000 tokens 提示**） | $0.50 | $0.625 | $0.05 | $2.50 |
| Claude Sonnet 5.5 | $2 | $2.50 | $0.10（0.05×） | $10 |
| （参考）Claude Opus 5.5 | $4 | $5 | $0.20（0.05×） | $20 |

其他官方要点：Batch API **50% 折扣**；缓存读取按基础输入的 0.1×（Fable 5.1/
Mythos 5.1 为 0.025×，Opus 5.5/Sonnet 5.5 为 0.05×）；**Claude Haiku 5.5 采用
分段计价**（>100K 提示档为 5× 单价）。

### 5.3 对 J2/J3 的参考含义（**估算性说明，非账单保证**）

- **J2**：`claude-haiku-5-5` 官方存在、固定快照、默认 effort `medium`、
  ≤100K 档输入 $0.10/MTok、输出 $0.50/MTok → 与「最小成本倾向」一致。
- **J3（1 USD）量级参考**：本计划 §D 的合成提示词约数百 token、预期输出量级
  为数十至数百 token，按 ≤100K 档费率估算，**单次调用成本远低于 1 美分**
  → 1 USD 预算对单次烟雾调用**显著宽裕**。**该估算不是账单保证**：
  不含重试、多轮、缓存写、thinking 输出与计价变更；金额控制能力仍如清单 §H
  （**事后核对 + 触顶中止**，非硬上限）。
- 计费归属（API Key vs CLI 登录）仍属 **FV-2**，本记录**不作归属结论**。

## 6. 阶段 2/3 需裁定的网络与风险事项（本阶段发现，如实登记）

| # | 发现 | 依据 | 影响与建议 |
|---|---|---|---|
| 1 | **CLI 获取来源为 `claude.ai`**（构建期从 `https://claude.ai/install.sh` / `install.ps1` 取安装脚本） | #11 | `claude.ai` **不在**阶段 1 白名单，也**不在**阶段 2/3 的「PyPI + api.anthropic.com」范围。若运行期 CLI 触发自动更新/校验 → 命中计划外目的地。**建议**：①阶段 3 前置阻断（C2-e）；②是否需要为 CLI 更新检查单独授权域名，**待裁定** |
| 2 | **运行期 CLI 出站面未核实**（官方 CLI 文档在 `code.claude.com`，**不在白名单**） | — | **未核实** CLI 是否访问更新/遥测端点。**建议**：①申请扩展白名单至 `code.claude.com`；或 ②阶段 2 完成后、阶段 3 前，在**离线**条件下以 `claude --help`/本地配置核实 |
| 3 | **构建期未对下载的 CLI 做哈希校验**（仅对安装脚本体做 shebang/HTML 形状检查） | #11 | 供应链说明：wheel 整体 sha256 可校验，但**内嵌 CLI 的来源未由哈希钉住**。如实登记，**不放大不缩小** |
| 4 | 构建脚本读取的环境变量：`CLAUDE_CLI_VERSION`（默认 `latest`）、`CLAUDE_CLI_INSTALL_VERSION`、`CLAUDE_CLI_INSTALL_SCRIPT`、`LOCALAPPDATA` | #11 | 运行期是否生效**未核实** → 列入阶段 3 前离线核实项（同时提示 CLI 可能写入 `%LOCALAPPDATA%`） |
| 5 | **C2-e 的约束（用户已裁定）**：不允许修改宿主机**全局防火墙规则** | 用户 2026-10-18 | → 候选 **C2-b（Windows 防火墙出站规则）被排除**；候选收缩为 **C2-a（进程级出站代理白名单）**为主，C2-c/C2-d 作纵深叠加；**实际有效性仍待执行前核验**（J9） |
| 6 | `permission_mode` 字面量集合**比既有文档记录的更大** | #8/#17 | 本版为 `["default","acceptEdits","plan","bypassPermissions","dontAsk","auto"]`——**新增 `dontAsk` 与 `auto`**；阶段 3 须**显式设 `"default"`**，并禁用 `auto`/`dontAsk`/`bypassPermissions`/`acceptEdits` |
| 7 | wheel 体积 117 MB 且**分平台** | #5 | 阶段 2 下载量与哈希对象明确（§3.1）；**下载可能耗时**，须记录开始/结束时间与目的地址 |
| 8 | `mcp-types==2.3.0` 为**精确钉版**（`==`） | #14 | 该包版本被 mcp 自身锁死 → 阶段 2 锁定清单中它**不应被解析成其他版本**；出现不一致 → 停止 |

## 7. 参数兼容性检查（P6：按 `main` @ 0.2.168 核验；语义级核实待阶段 2 后离线进行）

> **性质**：本阶段核实的是**字段存在性、类型与默认值**（只读源码 + PyPI 元数据）。
> **语义级行为**（`[]` 的实际效果、CLI 侧执行、beta 头要求、Windows 沙箱可用性）
> **一律未核实**。**因此 P6 仍为「未完成」**，须在阶段 2 安装完成后，对**已安装
> 版本**的 `types.py` 逐字复核（离线 grep，无需网络）。

| 计划项 | 本版（0.2.168 线）是否存在 | 声明原文（`types.py`，摘要来源 #8/#17） | 与计划的兼容性判定 |
|---|---|---|---|
| `tools` | ✅ 存在 | `tools: list[str] \| ToolsPreset \| None = None`；`ToolsPreset = {type: "preset", preset: "claude_code"}` | ✅ 可传 `[]`；**但「`[]`＝真正移除内置工具集」的语义本阶段未核实** → 阶段 3 前必须确认（不得沿用旧结论） |
| `allowed_tools` | ✅ 存在 | `allowed_tools: list[str] = field(default_factory=list)` | ✅ 保持勘误定性：**权限白名单**，非禁用面；本阶段未重核其语义细节 |
| `disallowed_tools` | ✅ 存在 | `disallowed_tools: list[str] = field(default_factory=list)` | ✅ 黑名单面可用 |
| `skills` | ✅ 存在 | `skills: list[str] \| Literal["all"] \| None = None` | ✅ 传 `[]`；注意 `"all"` 为显式值（本计划**不得**使用） |
| `plugins` | ✅ 存在 | `plugins: list[SdkPluginConfig] = field(default_factory=list)` | ✅ 默认即空 |
| `mcp_servers` | ✅ 存在 | `mcp_servers: dict[str, McpServerConfig] \| str \| Path = field(default_factory=dict)` | ✅ 传 `{}`；**类型允许 str/Path → 计划须明确禁止传配置文件路径** |
| `strict_mcp_config` | ✅ 存在 | `strict_mcp_config: bool = False` | ⚠️ **默认 False → 必须显式设 True**（计划已如此要求） |
| `setting_sources` | ✅ 存在 | `setting_sources: list[SettingSource] \| None = None`；`SettingSource = Literal["user","project","local"]` | ⚠️ **默认 None 的语义（是否等价「加载全部」）未核实** → 必须显式传 `[]`；`[]` 语义阶段 3 前确认 |
| `permission_mode` | ✅ 存在 | `permission_mode: PermissionMode \| None = None`；字面量见 §6-6 | ✅ 显式设 `"default"`；**禁用值增加 `auto`/`dontAsk`** |
| `hooks` | ✅ 存在 | `hooks: dict[HookEvent, list[HookMatcher]] \| None = None`；`HookEvent` 含 `PreToolUse` | ✅ 辅助控制面可用（与权限模式同级，非安全边界主体） |
| `env` | ✅ 存在 | `env: dict[str, str] = field(default_factory=dict)` | ⚠️ **仍非环境白名单**（勘误 2 结论不变）；干净环境须在**宿主启动层**建立 |
| `cwd` | ✅ 存在 | `cwd: str \| Path \| None = None` | ✅ 指向净化目录 |
| `max_turns` | ✅ 存在 | `max_turns: int \| None = None` | ✅ 语义＝**会话轮数**（≠API 请求数）保持不变 |
| `max_budget_usd` | ✅ 存在 | `max_budget_usd: float \| None = None` | ⚠️ **强制力仍未核实** → 维持「不得宣称硬上限」 |
| `task_budget` | ✅ **存在（重要修正）** | `task_budget: TaskBudget \| None = None`；`TaskBudget = {total: int}` | ⚠️ **修正此前文档**：清单 §H4 方案①（`task_budget`）在本版**是 SDK 选项字段**，技术可用；但**最低 `total`（API 侧宣称 20,000）、beta 头是否仍需、与 `max_turns` 的交互一律未核实** → 阶段 3 前核实 |
| `max_tokens` | ❌ **ABSENT**（两次核验一致） | 全字段核对无此名 | ✅ 维持既有结论（H4 只能选①/②或走 ADR） |
| `thinking` | ✅ **PRESENT（勘误 2026-10-19）** | `thinking: ThinkingConfig \| None = None`（`ThinkingConfig` = `adaptive`/`enabled`/`disabled` 三态联合） | **勘误**：阶段 1 曾误记「ABSENT/无该字段」；以**已安装 0.2.168 `types.py`**（第 2714 行）更正——与 cryptography 哈希同源，系 WebFetch 摘要**遗漏尾部字段**所致 |
| `max_thinking_tokens` | ⚠️ **存在（逐字整行未取得）** | 仅见片段 `…king_tokens: int \| None = None`（分块边界截断） | 已弃用字段；**阶段 2 后离线逐字确认** |
| `sandbox` | ✅ **存在（新发现）** | `sandbox: SandboxSettings \| None = None`；`SandboxSettings` 字段：`enabled`、`autoAllowBashIfSandboxed`、`excludedCommands`、`allowUnsandboxedCommands`、`network: SandboxNetworkConfig`、`ignoreViolations`、`enableWeakerNestedSandbox` | ⚠️ **与 R2「OS 级隔离为权威」可能直接相关**（CLI 自带沙箱）→ **列为阶段 3 前核实项**（Windows 11 可用性、`network` 子策略语义、`enableWeakerNestedSandbox` 的弱化含义） |
| 其他本版新字段（登记，本计划不使用） | ✅ | `fallback_model`、`betas`、`agents`、`include_hook_events`、`forward_subagent_text`、`verbatim_prompts`、`fork_session`、`resume_session_at`、`resume_drops_turn`、`add_dirs`、`settings`、`extra_args`、`max_buffer_size`、`debug_stderr`、`stderr`、`can_use_tool`、`permission_prompt_tool_name`、`user`、`session_id`、`resume`、`continue_conversation` | 仅登记；使用须另行裁定 |

**P6 结论**：**部分完成**。字段层（存在/类型/默认值）按 0.2.168 线核实完毕；
**语义层与 CLI 侧未核实**（含 `tools=[]`、`setting_sources=[]` 的真实效果、
beta 头、Windows 沙箱）→ **P6 保持 ❌ 未完成**（清单 §I/§J8 状态不变）。

## 8. 许可证核查

| 对象 | 结论 | 来源 |
|---|---|---|
| `claude-agent-sdk`（SDK 代码） | **MIT**（`info.license="MIT"`；classifier `License :: OSI Approved :: MIT License`；`pyproject` `license = {text = "MIT"}`；GitHub `license.spdx_id="MIT"`） | #1/#3/#4 |
| **捆绑 Claude Code CLI** | ⚠️ **未核实**。README 声明「Use of this SDK is governed by Anthropic's Commercial Terms of Service」→ 使用受**商业条款**约束；CLI 自身许可条款页位于 `code.claude.com`（**白名单外**）→ **未取得** | #6 |
| 一级依赖 | `anyio` MIT、`sniffio` MIT OR Apache-2.0、`typing-extensions` PSF-2.0、`mcp` MIT、`jsonschema` MIT | #12–#15 |
| 二级及更深 | **未核查**（待阶段 2 锁定清单逐包核对） | — |

**结论**：**一级依赖无阻塞性许可证冲突**；**CLI 条款与二级依赖许可证为未核实项**，
**不得外推为「全部合规」**。阶段 2 的锁定清单须附带**逐包许可证列**。

## 9. 阶段 2 所需完整安装清单（草案，**待批准**）

| # | 项 | 内容 |
|---|---|---|
| L1 | venv 基础解释器 | **待裁定（D-PY）**：①`D:\wo\python\Python312\python.exe`（3.12.10，满足计划 3.11+）②`D:\wo\miniconda3\python.exe`（3.10.12，PATH 默认） |
| L2 | venv 位置 | 隔离执行根内（**路径经环境配置注入**，AGENTS.md §3：不在代码/文档中硬编码为运行依赖） |
| L3 | **SDK 分发包** | `claude_agent_sdk-0.2.168-py3-none-win_amd64.whl`（**wheel，非 sdist**）sha256 `ed1814b0dd1c113bdaf3e51e6a67aa5b96b8f5c5839a43aeb6ae1e6ed23a5b35` |
| L4 | 一级依赖 | `anyio` ≥4.0.0、`sniffio` ≥1.0.0、`typing-extensions` ≥4.0.0（按标记）、`mcp` ≥1.23.0,<3.0.0、`jsonschema` ≥4.20.0（版本由解析器钉死，参考 §4.2） |
| L5 | 二级及更深依赖 | 按 §4.3 集合，**由解析器确定精确版本**（含 `pywin32`、`rpds-py`、`cryptography`、`pydantic`、`starlette`、`uvicorn`、`httpx2`、`mcp-types==2.3.0` 等） |
| L6 | 排除项 | `dev`/`examples`/`otel` extras；**sdist**；任何锁定清单外包；GitPython/pygit2/Dulwich/ORM/DB（§4.6） |
| L7 | **锁定清单生成（阶段 2 第 0 步）** | `pip install --dry-run --report lock.json "claude-agent-sdk==0.2.168"` → 生成**逐包版本 + `archive_info.hashes.sha256` + 许可证列** → **经批准人确认**后方可安装 |
| L8 | 安装方式 | `pip install --require-hashes -r lock.txt`（或等价哈希强制模式）；**安装前后核验 wheel sha256** |
| L9 | 安装后核验 | `pip freeze` 与锁定清单**逐项核对**；`import claude_agent_sdk; print(__version__)`；**离线**逐字复核 `types.py`（P6 语义项：`tools`/`task_budget`/`setting_sources`/`max_thinking_tokens`/`sandbox`） |
| L10 | 安装期网络范围 | 仅 `pypi.org`、`files.pythonhosted.org`（+ 批准人指定镜像域）；**阻断机制按 C2-e 收缩版（C2-a 为主，禁改全局防火墙）**；**目的地址留证**；计划外目的地 → 立即停 |
| L11 | 计划外目的地预登记 | `claude.ai`（构建期 CLI 来源）、`code.claude.com`（CLI 文档）、以及任何 CLI 更新/遥测端点——**若在安装期出现，一律视为异常并停止** |
| L12 | 失败处置 | 安装失败/哈希不符/出现清单外包/出现计划外网络目的地 → **停止、留证、报告；不自行换源、换版本、重试** |

## 10. 未核实项（不得升格为事实）与遗留风险

| # | 未核实项 | 影响 | 计划核实方式 |
|---|---|---|---|
| 1 | 引用到的若干源文本为 **WebFetch 摘要**（非逐字全文，含 README、download_cli.py、CHANGELOG、CHANGELOG 部分条目） | 措辞可能不等于原文 | 需逐字证据时以官方原文复核（阶段 2 前） |
| 2 | `types.py` **两处分块截断**：`max_thinking_tokens` 整行、部分类型字面量上下文 | §7 相应行标 ⚠️ | 阶段 2 后**离线**逐字复核已安装文件 |
| 3 | `tools=[]`、`setting_sources=[]` 的**真实语义** | 直接关系「功能收窄」有效性 | 阶段 2 后离线 + 阶段 3 前行为核实 |
| 4 | `task_budget` 的 beta 头/最低 `total`/交互 | H4 方案①可行性 | 阶段 3 前按锁定版本核实 |
| 5 | `sandbox`（CLI 沙箱）在 Windows 11 的可用性 | 关系 R2「OS 级隔离为权威」落地 | 阶段 2 后离线核实 |
| 6 | CLI 运行期出站面与自动更新行为 | 阶段 3 网络面安全 | 白名单扩展或离线核实（§6-1/2） |
| 7 | `code.claude.com` 上的 CLI 许可条款与 SDK 文档 | §8 未核实项 | 需用户裁定是否扩展白名单 |
| 8 | 二级依赖许可证、win_amd64 轮子可用性（`rpds-py`/`cryptography`） | 安装可行性与合规 | 阶段 2 锁定清单逐项核对 |
| 9 | 完整解析树 | 安装清单完整性 | 阶段 2 第 0 步（§9-L7） |
| 10 | 「wheel 安装不访问 `claude.ai`」 | 网络范围安全 | 阶段 2 前置阻断 + 目的地址留证实测 |

## 11. 阶段边界声明

1. 本文为**阶段 1**（官方资料核验与版本准备）产物；**阶段 2 安装与阶段 3 调用
   均未授权**，须各自单独审批。
2. §9 安装清单为**草案**，其中的 L1（解释器）与网络阻断机制（C2-a 具体实现）
   仍待裁定；**批准前不得安装**。
3. **未执行**：下载 wheel/CLI/安装包；安装依赖；创建 venv 或 Agent；访问模型 API；
   使用 API Key；修改任何防火墙/网络配置。
4. **未修改**：宪章、spec.md、AGENTS.md、ADLL-Knowledge、任何 FV-0/V2/V2.1/V2.2/FS2
   证据与脚本、既有审批清单的已批准内容（§A 仅追加「阶段 1 核验结果」登记，
   状态列一律保持「**未锁定/待批准**」）；**无 Git Commit/Push**。
5. 版本敏感结论（模型 ID、价格、SDK 字段、依赖版本）**在阶段 2/3 前须按锁定版本
   重新核实**（AGENTS.md §5.6）；本记录不构成对这些事实的长期保证。