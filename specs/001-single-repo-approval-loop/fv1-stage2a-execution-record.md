# FV-1 阶段 2A —— 受限执行记录（fv1-stage2a-execution-record.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**Date**: 2026-10-18
**性质**: **阶段 2A 受限执行记录**（作者：Agent，依用户 2026-10-18 阶段 2A 审批裁定）。
**本次执行范围**：只读公开元数据核查 + 依赖解析准备 + 锁定清单**草案**编制 +
P-2 授权的三个文件只读获取与签名核验。
**明确未执行**：pip `--dry-run/--report`（见 §3）· 任何 Wheel/sdist/CLI/安装器下载 ·
venv 创建 · SDK 安装 · CLI 运行（含 `doctor`）· AI 调用 · API Key 使用 · FV-2～FV-7 ·
网络或防火墙配置修改。

**执行根（全新、经安全验证的 TEMP 目录）**：
`%TEMP%/adll-fv0/run-20261018-fv1-2a`（`C:/Users/焦嘉鑫/AppData/Local/Temp/adll-fv0/run-20261018-fv1-2a`）
——TEMP 白名单校验通过、ReparsePoint 探针为普通目录、`realpath` 位于 TEMP 之内；
总规模 109 KB（**零分发物字节**）。

## 1. 用户裁定的落实情况（逐条）

| 裁定 | 落实 |
|---|---|
| P-1 只允许包索引与独立元数据；**不授权下载完整 Wheel/sdist/CLI/安装器** | ✅ 仅访问 PyPI JSON 元数据端点；**未取任何分发物字节**（`fetch/` 仅含 P-2 三文件，共 4.4 KB） |
| P-1 **pip --dry-run 不保证只取元数据**；无法在网络层阻断完整分发物下载时**不得执行该命令** | ✅ **未执行**（技术判定见 §3）；改为以 PyPI 元数据编制候选清单，并**明确标记「解析未完成」** |
| P-1 不得为凑齐完整锁文件而绕过下载限制 | ✅ 未绕过；缺失项以「未完成项」如实登记（未用 PEP 658 元数据、未访问 `files.pythonhosted.org`） |
| P-2 仅授权 3 个文件；不得跟随白名单外重定向；独立 TEMP GPG 密钥目录；不修改用户默认密钥环 | ✅ 逐字 URL 获取 3 个文件（§2）；**零重定向**；`GNUPGHOME` 设于执行根内 `gpg-home/`；用户密钥环未触碰 |
| P-2 如 GPG 存在则核验指纹/签名/校验和 | ✅ GPG 2.4.7 存在 → **签名核验通过**（§2） |
| P-3 参数（`--dry-run --only-binary=:all: --no-cache-dir --isolated --ignore-installed --retries 0`）**设计认可 ≠ 授权下载** | ✅ 已核实 pip 26.2.1 支持全部参数（`00-2a-pip-install-help.txt`）；**未执行任何安装/下载** |
| P-3 若解析器要求完整分发物 → 停止并报告下载清单 | ✅ 未运行解析器；候选清单给出**将需获取的 31 个分发物**（§4），供下一步审批 |
| P-4/P-5 不批准 2B；不得建 venv/装 SDK/运行 CLI/doctor/Agent | ✅ 均未执行 |
| P-6（阶段 3 隔离优先研究 W1 独立虚拟机，WSL2 备选；仅登记不实施）+ **P6 勘误** | ✅ 已登记于 [2A/2B 方案](./fv1-stage2a-2b-execution-plan.md) §4.4；**勘误已修正**（见 §6） |
| 证据与停止规则（全新 TEMP 根；记录 URL/目的地址/元数据/版本约束/候选哈希/许可证/签名结果/未完成项；异常即停） | ✅ 见 §5；**未触发任何停止条件** |

## 2. P-2 结果：CLI 签名证据（**核验通过**）

| 项 | 结果 |
|---|---|
| 三文件获取 | `manifest.json` 1897 B / `manifest.json.sig` 833 B / `claude-code.asc` 1688 B，**全部 `HTTP/1.1 200 OK`，零重定向** |
| 本地哈希 | manifest `8517444f…ce40`；sig `d98450e2…6d5f`；key `bd70a5e4…81c6` |
| 后端（登记为发现） | 响应头含 `x-goog-*`、`via: 1.1 google`（Google Cloud Storage 提供下载域；**目的域未跳出白名单**） |
| 公钥指纹 | `31DD DE24 DDFA B679 F42D 7BD2 BAA9 29FF 1A7E CACE`（`security@anthropic.com`）——**与官方文档公布值逐字一致** |
| 签名核验 | `gpg --verify` → `GOODSIG` + `VALIDSIG`，**exit 0**；签名时间 2026-10-15 22:02:55（本地时区） |
| 信任状态 | `TRUST_UNDEFINED`（新导入密钥未被本地认证）——**如实登记**：指纹比对已独立完成，故完整性结论成立，但**本地"信任链"未建立** |

**CLI 2.1.301 官方声明校验和（供 2B 比对）**

| 平台 | 二进制 | 大小 | sha256 |
|---|---|---|---|
| **win32-x64（本机相关）** | `claude.exe` | **271,840,416 B（≈272 MB）** | **`84d61feeb1a07e5a5b3354d68432591cac18a5d38a419a30d86d0f3ad8cba397`** |

manifest 其他字段：`version=2.1.301`、`commit=12a1baed117fbcc7e0695ab8aa6d2a4c6bd00cbb`、
`buildDate=2026-10-15T14:01:03Z`、`manifestSignatureEnforcement=flag`、
`harnessSchema=1`。

**⚠️ 登记为观察（不作判定）**：`sdkCompat.testedWrapperVersions` 列出 **18 项
`0.3.267`–`0.3.285`，其中不含 `0.2.168`**。同时 GitHub releases 核实：SDK **不存在
0.3.x 发行版**（最近 12 个发行版均为 0.2.156–0.2.168，全部 `prerelease=false`）。
→ 「wrapper」一词的**确切所指未核实**（可能是 TS SDK 或内部 wrapper 版本线）。
**本记录不将其解释为兼容性失败**；登记为后续核实项（§7-3）。

## 3. 为何**未执行** pip `--dry-run/--report`（技术判定 + 用户裁定）

用户裁定：只有能在**网络请求层**阻止未授权完整分发物下载时，才允许尝试在线 dry-run。

**本机判定：不具备该能力**，理由如实列出：

1. PyPI 分发物经 **HTTPS** 获取；普通正向代理只能看到 `CONNECT host:443`，
   **无法按 URL 路径**区分「元数据」与「完整 wheel」→ 无法在请求层阻断。
2. 要做到按路径拦截须**中间人解密（MITM）**或自建镜像索引——两者都超出本次授权，
   且引入新的信任面（自签 CA / 自建索引），**未被批准**。
3. 用户明确**不得修改宿主机全局防火墙**（P-6/阶段 2 裁定），故也不能用防火墙规则
   在 OS 层按目的地/大小阻断。
4. 因此**不满足**允许条件 → **不执行**；改以 PyPI 元数据编制候选清单。

**由此产生的诚实结论**：本次**未运行解析器**，传递闭包由**元数据人工追索**得出，
**未经解析器校验可满足性**。候选清单**不是锁文件**，**明确标记「解析未完成」**。

## 4. 依赖闭包 —— 候选清单（**31 个分发包**；详见执行根内 `01-2a-candidate-lock.md`）

- 顶层：`claude-agent-sdk==0.2.168`（win_amd64 wheel `ed1814b0…`）。
- 一级（5）：`anyio 4.15.1`、`sniffio 1.3.1`、`typing-extensions 4.16.0`、
  `mcp 2.3.0`、`jsonschema 4.26.0`（与阶段 1 核验一致）。
- 二级及更深（25）：`httpx2 2.13.1`、**`httpcore2 2.13.1`（`==` 钉版）**、`mcp-types 2.3.0`、
  `opentelemetry-api 1.45.1`、`pydantic 2.14.1`、**`pydantic-core 2.50.1`（`==` 钉版）**、
  `annotated-types 0.8.0`、`typing-inspection 0.4.4`、`pyjwt 2.15.1`、`cryptography 50.0.2`、
  `cffi 2.1.1`、`pycparser 3.11`、`python-multipart 0.0.32`、`pywin32 312`、
  `sse-starlette 3.5.0`、`starlette 1.8.0`、`uvicorn 0.54.0`、`click 8.5.0`、`h11 0.16.0`、
  `truststore 0.10.5`、`attrs 26.1.0`、`jsonschema-specifications 2025.9.1`、
  `referencing 0.37.0`、`rpds-py 2026.9.1`、`idna 3.20`。

**关键发现（对 2B/3 有直接影响）**

| # | 发现 | 影响 |
|---|---|---|
| 1 | **6 个包为 CPython 特定轮子**（SDK、pydantic-core、cryptography、cffi、pywin32、rpds-py） | 均**已确认存在** win_amd64/cp312 轮子；获取阶段若缺失 → **必须停止**（禁 sdist） |
| 2 | `mcp` 将 `opentelemetry-api` 列为**核心依赖**（非 `otel` extra） | 即使不装 extras 也会入树（与阶段 1 的假设需据此更新） |
| 3 | `pyjwt[crypto]` 的 **extra 会被安装**（依赖方的 extra 属于正常解析结果） | 因此 `cryptography`→`cffi`→`pycparser` 入树；**这是唯一"extra"路径**，与"本清单不含 extras"不矛盾（区别：**顶层**不装 extras） |
| 4 | `starlette 1.8.0` 与 `rpds-py 2026.9.1` 要求 **Python ≥3.11** | 与 D-PY（3.12.10）一致；**本候选清单仅适用于 3.12** |
| 5 | `click 8.5.0` 的 `requires_dist` 为 **null**（无 `colorama` Windows 依赖） | Windows 上**不需要** colorama |
| 6 | `httpcore2` 依赖 **`truststore`** 而非 `certifi` | **`certifi` 不入树**（与常见假设不同，已核实） |
| 7 | CLI 官方 win32-x64 二进制 **272 MB** > SDK wheel **117 MB** | 2B 中「wheel 内嵌 CLI 与独立二进制是否字节相同」**不可预设**；比对结果无论一致与否均须如实登记（见 §7-4） |

**红线核对**：闭包内**无** GitPython / pygit2 / Dulwich / ORM / DB 驱动。
**排除项**：全部 extras（含 mcp `cli`/`rich`、httpx2 `cli`/`http2`/`socks`/`brotli`、
uvicorn `standard`、starlette `full`、pydantic `email`/`timezone` 等）、sdist、任何未列明包。

## 5. 证据清单（执行根 `%TEMP%/adll-fv0/run-20261018-fv1-2a`）

| 证据 | 相对路径 | sha256 |
|---|---|---|
| 前置检查（64 位/路径/pip/托管设置/gpg） | `evidence/00-2a-preflight.txt` | `8fd626b9…4d077f4b` |
| `pip install --help` 全文（参数核实） | `evidence/00-2a-pip-install-help.txt` | `8b3e1624…a1dd9f7` |
| P-2 获取记录（URL/HTTP/哈希） | `evidence/00-2a-p2-fetch.txt` | `4cf3b1c3…78bcce64` |
| P-2 签名核验（隔离密钥环 + 指纹） | `evidence/00-2a-p2-gpg.txt` | `f9102a67…a61290f2` |
| manifest 逐平台摘要 + sdkCompat | `evidence/00-2a-p2-manifest-detail.txt` | `e01e5b1e…0f600a43` |
| **网络访问记录（全 URL）** | `evidence/01-2a-access-log.md` | `6c418bd6…e4598fdbe` |
| **候选依赖清单（31 包 + 哈希 + 许可证 + 未完成项）** | `evidence/01-2a-candidate-lock.md` | `33b13e41…368a5f26` |
| 汇总（SCOPE/判定/状态行） | `evidence/99-2a-summary.txt` | `c8cd6d8f…621940eac` |
| 文件夹清单与全量哈希 | `evidence/99-2a-inventory.txt` | `bf5b4f6d…08cdbe5e1` |
| P-2 授权工件 | `fetch/{manifest.json, manifest.json.sig, claude-code.asc}` + `.headers` | `8517444f…` / `d98450e2…` / `bd70a5e4…` |

**汇总状态行（原文要旨）**：`SCOPE = 2A RESTRICTED`；`PIP_DRYRUN_EXECUTED = NO`；
`LOCK_STATUS = CANDIDATE LIST ONLY; RESOLUTION_INCOMPLETE`；`SDIST_INCLUDED = none`；
`EXTRAS_INCLUDED = none`；`UNPLANNED_NETWORK = none`；`UNAUTHORIZED_DOWNLOAD = none`；
`STOP = not triggered`；`EXIT_STATUS = 2A_RESTRICTED_EXECUTION_COMPLETE`。

## 6. P6 勘误落实（用户 2026-10-18 裁定）

**勘误内容**：SDK **0.2.168 的 `SandboxSettings` 类型中没有直接定义
`failIfUnavailable`**；不得假定 Python 字段已支持；须核实通过 settings/CLI 传递该
安全设置的有效方式。

**修正动作**：已在 [2A/2B 方案](./fv1-stage2a-2b-execution-plan.md) §0.3 **F-8** 行与
§5 **R9** 行改写为：官方文档出现「Set `"failIfUnavailable": True` in your sandbox
settings / The SDK forwards `failIfUnavailable` to Claude Code along with the declared
`SandboxSettings` fields」的**表述**，但**SDK 0.2.168 的 `SandboxSettings` TypedDict
未声明该键**（本阶段源码核验的字段为：`enabled`、`autoAllowBashIfSandboxed`、
`excludedCommands`、`allowUnsandboxedCommands`、`network`、`ignoreViolations`、
`enableWeakerNestedSandbox`）→ **传递机制未核实**，列为阶段 2B 后/阶段 3 前的
离线核实项；**在核实前不得依赖该设置**，也不得宣称"沙箱不可用时会停止"。

## 7. 未完成项与遗留风险（**不得升格为事实**）

| # | 项 | 状态 |
|---|---|---|
| 1 | **依赖解析未完成**（解析器未运行） | 候选清单已标记；锁文件未生成 |
| 2 | 锁文件（`name==version --hash=sha256:…`）未产出 | 待 Wheel 获取阶段生成并人工审核 |
| 3 | `sdkCompat.testedWrapperVersions`（0.3.267–0.3.285，**不含 0.2.168**）的**确切所指未核实** | 登记为观察，**未解释为兼容性失败**；列入后续核实 |
| 4 | wheel 内嵌 CLI 与官方独立二进制（272 MB / `84d61fee…`）是否同字节 | **不可预设**；2B 比对，无论结果如何如实登记 |
| 5 | `failIfUnavailable` 的传递机制（§6） | 未核实 |
| 6 | 未获取任何分发物 → 索引哈希**未经实际工件复核** | 获取阶段逐包复核 |
| 7 | `pydantic`/`pydantic-core` 的 license 与 `requires_python`、`h11`/`idna` wheel 文件名未逐字取得 | 获取阶段补齐 |
| 8 | 二级依赖许可证完整性 | 已尽量填写；`lock-manifest` 阶段逐项补齐 |
| 9 | 是否存在元数据未揭示的依赖（平台条件分支等） | 待解析器（或人工再核）确认 |
| 10 | C2-e 收缩后的阶段 3 边界（W1 独立虚拟机优先，WSL2 备选） | **仅登记，未实施**；隔离验证另行 |

## 8. 阶段边界声明与下一步

1. 本文为**阶段 2A 受限执行**记录；**阶段 2B 离线安装未获批准**，阶段 3 未获批准。
2. 本次**未创建 venv、未安装或运行 SDK/CLI、未发起 AI 调用、未使用 API Key**；
   未修改真实仓库与 ADLL-Knowledge；未清理既有证据；**无 Git Commit/Push**；
   未修改任何网络/防火墙配置。
3. **未触发停止条件**（无未授权下载、无计划外联网、无签名异常、无哈希不符、
   无源码构建尝试）。
4. **下一步需人工批准其一**：
   - **(a) 2A 后续：真实 Wheel 获取**（31 个分发物，逐包哈希强制；含 `downloads.claude.ai`
     已在 P-2 内用完，无需再扩展）；
   - **(b) 阶段 2B 离线安装**（须先审核锁文件——而锁文件需先由 (a) 或经批准的解析步骤生成）；
   - **(c) 阶段 3 隔离环境研究**（W1 独立虚拟机优先 / WSL2 备选；仅研究不实施）。
5. 版本敏感事实（候选版本、哈希、模型/价格、CLI 校验和）**在执行下一步前须重新核实**
   （AGENTS.md §5.6）；本记录不构成长期保证。