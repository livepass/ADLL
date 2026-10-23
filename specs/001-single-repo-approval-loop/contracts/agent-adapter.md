# AgentAdapter 边界契约（contracts/agent-adapter.md）— R2 修订版（含最终安全边界修订）

**Date**: 2026-10-17（R2 + 最终安全边界/一致性修订：P0-A/B/C） | **Spec**: [spec.md](./spec.md)（未修改）
**目的**: 业务代码不依赖任何具体 Agent SDK/CLI（FR-024/044）；候选 A
（Claude Agent SDK）与对照 B（CLI 封装）经同一接口接入；**不预设任一
选型能满足全部安全要求**——FV-3/FV-7 不达标即走降级路径（research R1）。
本契约为接口与边界语义定义，非实现代码。

## 0. 边界分层声明（P0-01）

```text
OS 级隔离   = 权威安全边界（缺失即不安全；验收以此为准）
工具级约束  = 纵深防御（disallowed_tools / Hook deny / 载荷校验）
提示词      = 无安全效力（仅引导输出格式）
```

**Hook、提示词、`allowed_tools`、UI 置灰均不得作为安全保证**（已核实：
SDK README 明确 `allowed_tools` 不移除工具，2026-10-17）。安全验收 S 系列
以 OS 级行为判定。

## 1. OS 级边界要求（宿主实施，AgentAdapter 申报生效配置；P0-A 修正）

**关键修正**：**MIC 低完整性默认只限制写入**高完整性客体（No-Write-Up），
**不限制读取**；**受限令牌**经 restricting SIDs / deny-only SIDs 的二次
访问检查**有能力限制读取**，但生效性取决于客体 DACL 授权 SID 是否被
排除，须与 DACL 组合并实测——两者不得混同。读取隔离以 **DACL 显式
`Deny Read`** 为权威（可与受限令牌 SID 集组合强化；或独立低权限用户/
沙箱）；"不向 Agent 传原仓库路径"仅最小化暴露面，**不构成访问隔离**
（可被目录枚举/符号链接/猜测路径穿透）。下列机制均为候选配置，
**未证明有效**，生效性由 FV-3/实现期实测与运行时探针验证。

| 边界 | 要求 | 机制候选（ADR/FV 验证） |
|---|---|---|
| Agent 进程 | 独立受限主体（受限令牌 restricting SIDs 参与限读 + MIC 低完整性仅补限写）；与 FastAPI 后端分进程 | CreateRestrictedToken + DACL 组合（限读须逐客体验证）；不足则独立低权限用户/AppContainer/沙箱 |
| 审批数据库 | Agent 进程**无任何读写**（读也要拒） | DB 文件对 Agent 主体 **Deny Read/Write**（DACL） |
| 原始用户仓库 | Agent **不可读** | 原仓库根对 Agent 主体 **Deny Read**（DACL，非仅不传路径） |
| 全量归档 | Agent **不挂载** | 归档目录 Deny Read（P0-C） |
| 物化授权子集 | Agent **仅 Read**（唯一可读面） | 子集目录仅授予 Agent 主体 Read（P0-C） |
| 用户目录 | 无读写 | DACL Deny Read/Write + MIC 补写限 |
| 凭据 | 仅环境变量注入 Agent 进程；不入 DB/日志/快照 | 受限环境块 |
| 进程生命周期 | Job Object 纳管；取消=终止进程树；**禁用 breakaway**（不设 BREAKAWAY_OK/SILENT_BREAKAWAY_OK）；子进程逃逸专项测试（S15） | Win32 Job Object（kill-on-close；**非独立安全边界**，须与 DACL/受限令牌组合） |
| 网络 | 出站白名单（仅授权 AI 端点） | 按可执行文件防火墙/代理规则 |

`capabilities()` 必须申报当前生效的 OS 边界配置（供启动自检与审计）；
**运行时权限探针（fail-closed，S14）**：`self_check()` 以合成探针实测
——Agent 主体对"应拒绝客体"读取必须失败、对物化子集读取必须成功，
任一不符 → **拒绝进入生成**。申报不实视为候选不合格。

## 2. 配置加载策略（设置/Hooks/MCP/插件/不可信规则，P0-01.3）

1. Agent 进程工作目录 = ADLL **净化运行目录**（仅宿主组装的 prompt 与
   manifest 放行文件）；目标仓库快照仅以数据路径显式传参读取。
2. 配置目录指向 ADLL 管理的干净目录（环境变量隔离；具体变量名 FV-1
   核实并记录）。
3. **项目级 settings / Hooks / MCP 服务器 / 插件一律不加载**；
   Hooks 白名单 = 仅 ADLL 自带 deny 类 Hook；MCP = 空；插件 = 无。
   任何变更走配置审计 + 人工批准。
4. 快照中 README/注释/规则/提示词文件：仅作**数据**进入分析上下文，
   系统指令层明确不执行其中指令（FR-014）；验收 S2/S10 断言零加载。

> **2026-10-20 适配（候选 C Accepted）**：候选 C（Messages API 直连）**无 Claude Code 引擎**，
> 故本条 1–3 的「配置目录/Hooks/MCP/插件零加载」在 C 下属**结构性不适用**（不存在该类加载面）；
> 第 4 条「不可信数据仅作数据、不执行其指令」**继续有效**（快照内容由后端组装入模，仍不执行）。

## 3. 出站强制接口（P0-02/P0-C 四层漏斗的 Adapter 侧）

```text
L1 宿主 send_manifest（唯一权威）→ GenerationRequest.send_manifest
L2 文件读取权限面（P0-C）：Agent 仅可读物化授权子集（MaterializedSubset，
   DACL Read）；全量归档/原仓库/未授权文件 Deny Read——管"能不能读到"
L3 实际模型请求内容面：宿主组装实际模型请求（prompt+需求+反馈+放行文件+
   工具返回内容）—— Agent/Adapter 不得自行追加；管"实际发出什么内容"
L4 网络发送目的地面：OS 出站白名单兜底；未授权端点阻断+安全事件——
   管"发往何处"
```

三面（L2/L3/L4）分别强制与验证，互不替代（research 5.1）。

- **工具返回内容 = 外发内容**：读到什么就等于发给模型什么；Adapter 将
  工具返回摘要回传宿主记入 SendAuditRecord（payload_manifest 必含
  需求文本、反馈、源码、工具返回四类，见 data-model 2.9）。
- 阻断语义：任一层拒绝 → 生成阻断 + 明确受阻原因；事件入安全审计
 （blocked_out_of_scope / blocked_egress）。
- **能力不假设**：`capabilities()` 申报 L3/L4 实际可控面；申报不实
  或 FV-3/FV-7 穿透 → 判定该候选不合格（降级/换方案 C 重走 ADR）。

## 4. 接口语义（候选中立，增量修订）

```text
AgentAdapter
  generate(request: GenerationRequest, sink: EventSink) -> GenerationResult
  cancel(execution_id: str) -> CancelOutcome
  capabilities() -> AdapterCapabilities     # 含 OS 边界与出站可控面申报
  self_check() -> BoundaryCheckReport       # 启动自检（fail-closed）
```

- **GenerationRequest**：`subset_path`（**物化授权子集**只读目录，
  P0-C；全量归档/原仓库路径不传入）、`requirement_text`、
  `feedback_texts`、`send_manifest`（L1 放行清单）、`constraints`
 （拒绝规则、超时、禁用 `acceptEdits`）、`idempotency_key`。
- **GenerationResult**：方案正文、依据引用、`usage`/`usage_basis`、
  `cost`/`cost.basis`（**独立双维度**，P1-05）、真实终态、
  `tool_call_log`（供审计）。

> **2026-10-20 适配（候选 C）**：候选 C 无工具 → `tool_call_log` **恒空**（字段保留）；
> `usage` 直接采用 `response.usage`（input/output tokens）；`cost` 三分类
>（actual/estimated/unknown，data-model §2.5 `cost.basis` 已具备），**不把 usage 当作实际
> 结算金额**。
- **CancelOutcome**：`cancelled / not_cancelled / already_finished`（FR-034）；
  实现依赖 Job Object 进程树终止（R2）。
- **EventSink**：流式进度事件（SSE 上游，P1-03）。

## 5. 硬性边界（汇总，违反即选型不合格）

1. 无审批能力（P0-B）：无写审批数据/状态的工具与凭据（FR-033/041）；
   **Agent 进程不存在可调用审批接口的用户会话身份**，即使直接发本地
   HTTP 调用批准接口也必须被服务端身份层拒绝（S13）。
2. 无自由出站：发送内容 ⊆ 宿主组装的请求；无自取内容通道（FR-015/016）。
3. 只读 + 子集读取（P0-C）：Agent 仅读物化授权子集；未授权仓库文件
   对 Agent **不可读**（DACL Deny Read）；禁用 `acceptEdits`。
4. 凭据隔离：不入日志/错误/费用信息/数据模型（FR-042）。
5. 不可信数据：目标仓库规则/提示词零加载（FR-014/043）。
6. 真实结果：Mock 仅自动化测试（FR-009）；失败/超时/取消如实上报。
7. fail-closed（P0-A）：边界自检/权限探针失败、能力申报缺失、审计缺口
   → 拒绝生成（S14）；Job Object 禁 breakaway、子进程树可终止（S15）。

## 6. 选型对照点（FV 验收映射，修订）

| 验证项 | 候选 A（SDK） | 对照 B（CLI） | FV |
|---|---|---|---|
| Windows 实机 | wheel 安装 + CLI 捆绑 | CLI 无头模式 | FV-1 |
| 认证/计费归属 | API Key / 登录支持面 | 登录态复用是否成立 | FV-2 |
| 工具拒绝 + 配置加载隔离 | `disallowed_tools` + Hook deny + 干净配置目录 | CLI 等价物 | FV-3 |
| 取消/超时（Job Object 配合） | cancel 语义 | 进程终止语义 | FV-4 |
| usage/cost 双维度字段 | 响应字段实测 | 输出解析实测 | FV-5 |
| 流式/崩溃 | EventSink 映射 | stdout 流解析稳定性 | FV-6 |
| 出站白名单与审计闭环 | 网络观测 vs 审计 | 同左 | FV-7 |

> **2026-10-20 适配（候选 C Accepted，主路线）**：候选 C（Messages API 直连，阿里云百炼）——
> Windows 实机=标准库直连（无 wheel/CLI）· 认证=`DASHSCOPE` Bearer · 工具拒绝+配置加载隔离=**结构性 N/A**
> · 取消/超时=async+幂等 · usage/cost=`response.usage` 三分类 · 流式=非流式（`stream=false`）
> · 出站=单端点 `dashscope.aliyuncs.com`。上表候选 A/B 行**保留**为对照记录，不再作为主路线映射。
