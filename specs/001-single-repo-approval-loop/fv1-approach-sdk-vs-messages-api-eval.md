# 技术选型评估：Claude Agent SDK vs 直接调用 Claude Messages API（fv1-approach-sdk-vs-messages-api-eval.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**Date**: 2026-10-19
**性质**: **只读选型建议（草案，未批准）**。据用户 2026-10-19 指示开展的精简技术选型
评估，用于在 **ADR-C4（Agent 接入终选）** 进入正式决策前提供分析依据。
**本文件不修改任何已批准的需求/架构/选型，不将任何候选 ADR 标记为正式批准**；
最终选型须走独立 ADR + 人工批准（AGENTS.md §2）。
**本轮不授权** SDK/CLI 执行、模型 API 调用、API Key 使用、依赖安装、业务开发、Git Commit/Push。

**依据（已批准/已核实）**：[spec.md](./spec.md)（US/FR/SC）、[research.md](./research.md)
（R1/R2/R5、ADR-C3）、[contracts/agent-adapter.md](./contracts/agent-adapter.md) 引用、
[adr-c3-git-access-decision-draft.md](./adr-c3-git-access-decision-draft.md)、
FV-1 各阶段执行记录（本目录 `fv1-*`）。

## 0. 结论先行（推荐，待人工批准）

**推荐 V1.1 采用「直接调用 Claude Messages API + 自建极简编排」（research.md 候选 C）**；
必要时以官方 beta **Tool Runner**（自定义工具 + 每轮 hooks）补足"受控读取/结构化产出"，
**不引入 Claude Agent SDK（候选 A）作为 V1.1 主干**。候选 A 与其已完成核验证据**保留**，
作为 **V2 若需内置 Agent 能力**时的候选。

**一句话理由**：V1.1 的闭环是「读取已绑定的 Git Commit 快照 → 生成**文本**技术方案 →
人工审批」，**不是**自主工具的 agentic 循环；把模型当"受控读入 + 生成文本"用，直连 API
最贴合、最省、权限边界最清晰；Agent SDK 的 harness/内置工具对 V1.1 是**额外攻击面与
运行期负担**，而其对 V1.1 的价值（文件读取工具）恰是我们计划禁用（`tools=[]`）的部分。

> ⚠️ 本结论**推翻/重排** research.md R1 现有「优先 A，对照 B」的默认排序（C 目前被定位为
> 「A/B 验证失败时升级为候选」）。此为**建议重新排序**，不得视为已改；最终以 ADR-C4 人工
> 终选为准。

## 1. 五重点逐项对比

| 关注点 | C：Messages API 直连（推荐） | A：Claude Agent SDK |
|---|---|---|
| **方案生成 + 人工审批闭环** | 天然契合：单次/少次请求 → 文本方案（可配结构化输出 `output_config.format`）；审批门禁全部在 ADLL 服务端（FR-033 服务端强制、FR-041 AI 无批准/写入权），AI 侧零自决 | 可用但过重：`query()` 背后拉起捆绑 CLI 的完整 session/hooks/compaction 机制；为拟合"纯生成"须 `tools=[]` 等大量禁用（正是 FV-1 §5 在做的事），本质是把 agent 退化回单请求，还背上 harness |
| **自主工具调用是否刚性需求** | **非刚性**（见 §2）→ 不需要内置工具 | 其核心卖点即自主工具，V1.1 用不上 |
| **授权代码读取** | 服务端用已定 ADR-C3（子进程 Git + `git archive`）产出快照，经 AgentAdapter manifest 白名单（R2⑧）校验后作为**请求载荷**送入；模型无 Read/Bash 工具 → 文件访问完全在服务端、可审计（FR-015/017） | 若要用它读文件需给 Read/Glob/Grep 工具跑在工作目录上——权限面大；但按 FV-1 计划我们反而不给工具，故其该能力**被弃用** |
| **权限隔离与网络边界** | 出站仅 `api.anthropic.com`（+ 授权内容）一条清晰面；无捆绑 CLI、无 update/feature-flag/telemetry 等额外端点（对比 FV-1 阶段 3 风险清单） | 捆绑原生 CLI：额外出站面（`api.anthropic.com` 还承载 feature-flag 抓取与遥测、`downloads.claude.ai` 更新检查、`raw.githubusercontent.com` changelog 等，见 2A/2B 方案 §0.3-F3/F22/F23）；permission_mode/hooks/sandbox 均需另设且（原生 Windows）沙箱不可用 |
| **实现复杂度 / 维护成本** | 官方 `anthropic` 轻 SDK + 一次请求/流式 + 结构化输出；无 117 MB wheel、无捆绑 CLI、无 session/hooks/MCP/compaction 维护 | 重：需管理 CLI 子进程生命周期、session、权限回调、hook、超时/取消/恢复；安装/签名/供应链核验成本高（FV-0→FV-1 已投入全套验证） |
| **API 费用** | 纯模型 token（可选 prompt caching）；系统提示/工具 schema 由我方最小化，token 更可预期 | 同模型 token 基础 + CLI 注入的默认系统提示与工具定义（即使 `tools=[]` 仍有 harness 开销）；金额同为主观估算非硬上限 |
| **对 V2 Agent 自动化的扩展影响** | **低迁移风险**：直连 API 是所有路径的底座（Agent SDK 内部也这样连）；V2 需自主循环时可在同底座加 **Tool Runner**（`client.beta.messages.tool_runner` + 自定义工具 + 每轮 hooks）或升级 Agent SDK/Managed Agents，**不必返工数据/审批层** | 若 V1.1 已上 A，V2 自然复用它；但对 V1.1 已属"为将来提前背债"；且 A 的权限/网络隔离在原生 Windows 上仍是未闭环（阶段 3 未解） |

## 2. 自主工具调用是否为 V1.1 刚性需求 —— **判定：否**

依据（spec.md 原文语义）：

- 「关联仓库 → 创建任务 → **真实 AI 生成技术方案** → 版本化修改 → 人工审批」；**AI 只生成方案文本**。
- US2「真实 AI 生成技术方案（受控只读 + 证据依据）」：**只读**、**不执行**目标业务代码；
  FR-010/FR-011「分析过程 MUST NOT 执行目标项目的业务代码、构建脚本或测试脚本」「仅读取源码快照」。
- 外延明确排除：**不实现 AI 编码与测试执行（V1.2）**、「不做多 Agent 调度（仅预留可扩展接口）」（输入段）。
- FR-041/FR-033：关键执行受**服务端**权限边界约束，AI 无批准/写入能力。

→ V1.1 对 AI 的期望是"**受控输入 + 生成文本**"，**无任何"自主决定调用工具/写文件/跑命令"的需求**；
"工具调用"若存在，也只能是**受控、只读、服务端代持**的"读取已授权快照"——这一动作完全可由
服务端在请求前完成，无需模型持工具。故**自主工具循环非刚性需求**，是"可延后到 V2"的能力。

## 3. 授权代码读取、权限隔离与网络边界（C 方案落点）

1. **代码读取**：ADLL 后端（FastAPI）用 ADR-C3 子进程 Git CLI + `git archive`，对**绑定的
   完整 commit SHA** 产出只读快照（FR-005）；将任务相关、已授权文件/片段组装为请求内容。
2. **发送面**：FR-015——发送前说明接收方（Anthropic API）、数据类型与范围；范围经 AgentAdapter
   manifest 白名单（R2⑧）校验；范围外/敏感文件按规则排除并受「非绝对保证」约束（FR-016）。
3. **权限隔离**：AI 无文件系统/Bash 能力（不给工具），批准与写入仅在服务端（FR-041），
   与 R2 权限分层对齐——**本方案里"AI 权限面"即"请求内容面"**，最易审计。
4. **网络边界**：仅 `api.anthropic.com` 一站（R5 出站授权）；无捆绑 CLI 附加端点；不涉及
   CLI sandbox（原生 Windows 不受支持的问题随之消失）。**仍需**：出站白名单/独立性核验
   与「不得宣称绝对不可绕过」的既有纪律不变。

## 4. 实现复杂度、维护成本与费用（C 方案落点）

- 依赖：仅官方 `anthropic` SDK（纯 Python，轻；与 R7 依赖红线的适配差异由 ADR 记录）。
- 实现面：单次 `messages.create`/`stream` + `output_config.format`（结构化方案 JSON）+
  我方 prompt/snapshot 组装；取消/超时由 FastAPI 任务层管理（已有状态机 FR-038/039）。
- 维护面：无 CLI 子进程/会话/权限回调/hook 的运维；升级仅限 `anthropic` 版本（ADP 记录）。
- 费用：纯模型 token（可 prompt caching）；无 harness 注入开销；金额控制仍按「估算 + 事后 +
  触顶中止」如实分级（不宣称硬上限）。

## 5. 未决事项 / 风险（如实登记，不掩盖）

1. **本建议与 R1 现有排序不同**（§0 警告）：须经 ADR-C4 人工裁定；本文件不改 R1。
2. **Tool Runner 是否为 V1.1 必需**：若「结构化方案产出 + 证据引用」用 `output_config.format`
   即可满足（FR-017），则连 Tool Runner 都不必上；反之再评估（属 ADR-C4 子项）。
3. **直连 API 的认证/计费归属**= FV-2 范围；候选 C 仍需一轮最小真实调用验证（对应 FV-1 若改为
   直连后的等价 smoke）。
4. **模型选择**（J2 推荐 `claude-haiku-5-5`/`claude-sonnet-5-5`）与直连/Agent SDK 无关，通用。
5. **候选 A 的 FV-0/FV-1 证据不浪费**：仍作为「若 V2 上 Agent SDK」的可行性/供应链基线保留。

## 6. 明确不构成 / 不解锁

- 本文件**不**修改已批准的 spec.md/research.md/plan.md/ADR-C3；**不**将 ADR-C4 或候选 C
  标记为正式批准；**不**授权任何执行动作（SDK/CLI 运行、API 调用、API Key、依赖安装、
  业务编码、Git Commit/Push）。
- 后续路径：ADR-C4 草案定稿（含本评估作为依据）→ 人工批准 → 方可据其锁定实现。