# ADR-C4（Accepted）→ 既有文档 最小契约适配建议（adr-c4-docs-adaptation-suggestions.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**Date**: 2026-10-19
**性质**: **只读适配差异分析与最小变更建议（未实施）**。
[ADR-C4](./adr-c4-ai-access-decision-draft.md) 已 **Accepted（候选 C：Messages API 直连 + 自建
极简编排；供应商=阿里云百炼，Anthropic 兼容）**。据用户裁定：research/plan/contracts 等
适配**先提交最小变更清单**，**本次不自动实施**。下列差异点均为**建议**，待人工授权后落地；
**不得据此修改已批准的 spec.md、宪章、AGENTS.md、research.md、plan.md、contracts、data-model.md**。

## 1. research.md

| 位置 | 现状（与候选 C 的差异） | 最小建议（待授权） |
|---|---|---|
| R1 §候选表 + §决策（L17–24、L44–50） | 「候选优先 A，对照 B」；C 定位为「A/B 失败时升级」 | 追加状态标注：**候选 C 已于 2026-10-19 Accepted**；A/B/C/D 保留为历史候选；「优先 A」字句失效（不改删，追加日期性批注） |
| R2 §2.2 主体矩阵 / §2.3 自动加载 | 以「Agent 工作进程 + 工具/Claude Code 系引擎」为对象 | 追加批注：「候选 C 下生成/API 发送单元**无工具面**；§2.3 的 settings/Hooks/MCP/插件自动加载风险对 C **结构性不适用**（保留『快照内不可信数据仅作数据、不执行其指令』目标）」；OS 级 DACL/出站白名单/凭据/S14 探针**不因无工具而豁免** |
| **附录 A FV 阶梯**（L456–490） | 围绕 SDK wheel/CLI/工具/Hook/Job Object/流式崩溃设计 | 重排（见下表），保留已完成证据；标注 FV-1 已由「Messages API smoke」替代完成 |
| L506「候选 A 不得写死」、L516 | — | 追加「候选 C = Accepted，V1.1 主流程」批注 |

**附录 A 重排建议（FV，候选 C 口径）**：

| FV | 原（候选 A/SDK） | 候选 C 口径调整（建议） |
|---|---|---|
| FV-0 | 纯离线 Git 预检 | **不变**（Git 侧，ADR-C3） |
| FV-1 | SDK 安装 + 最小调用 | **已完成并由「Messages API smoke」替代**（本次 PASS） |
| FV-2 | API Key + CLI 登录 / 计费归属 | 仅 `DASHSCOPE` Bearer Key（CLI 登录 N/A）；计费=阿里云账单（实际/估算/未知三分类） |
| FV-3 | 工具拒绝 + 配置加载隔离 | **结构性无关**（无工具/无引擎），降为「无工具面核验」 |
| FV-4 | 取消/超时 + Job Object | async 请求/coop 取消 + 超时 + 幂等 + actual 终态（Job Object 不再绑定 CLI 进程树） |
| FV-5 | usage/cost 盘点 | 直接 `response.usage`（已实测 in22/out6）+ cost 三分类 |
| FV-6 | 流式/崩溃 | 直连非流式（`stream=false`）+ 请求/进程崩溃恢复（重定位） |
| FV-7 | 出站白名单 + 审计 | 单端点 `dashscope.aliyuncs.com` + SendAuditRecord；加密请求体/提供方留存残留「未验证」不变 |

## 2. plan.md

| 位置 | 现状 | 最小建议（待授权） |
|---|---|---|
| §32–36、§50–51 Primary Dependencies | 「Agent 接入候选 claude-agent-sdk（**未安装**；安装须 ADR+批准）」 | 改为「候选 C：官方 `anthropic` SDK 或等价 HTTP（Anthropic 兼容端点，默认 阿里云百炼 `dashscope.aliyuncs.com/apps/anthropic`）；**不引入** claude-agent-sdk / Claude Code CLI / beta Tool Runner」 |
| §38–41 OS 隔离 / Job Object / 工具拒绝 | 以 SDK/CLI 口径描述 | 追加 C 口径：无工具面；取消=async + 超时 + 幂等；OS 隔离（DACL/出站白名单/凭据/S14）不变 |
| §43 语言版本 | Python 3.11+ | 不变（D-PY 已裁定 3.12.10） |

## 3. contracts/agent-adapter.md

| 位置 | 现状 | 最小建议（待授权） |
|---|---|---|
| §1 边界表 / §2 配置加载 / §0 工具级纵深 | 以 SDK 工具/Hook/引擎为对象 | 追加「候选 C 下结构性不适用」批注；OS 级权威照旧 |
| §4 `GenerationResult` | `usage/cost` 采用 SDK 响应；`tool_call_log` | 追加：`tool_call_log` **恒空**；`usage`=`response.usage`；`cost` 三分类（actual/estimated/unknown） |
| **§6 对照点表**（候选 A vs 对照 B） | 缺候选 C 行 | **新增「候选 C（Messages API 直连）」行**：Windows 实机=标准库直连 · 认证=`DASHSCOPE` Bearer · 工具拒绝=N/A · 取消/超时=async · usage/cost=`response.usage` 三分 · 流式=非流式 · 出站=`dashscope` 单点 |

## 4. contracts/api-endpoints.md

| 位置 | 现状 | 最小建议（待授权） |
|---|---|---|
| §3 send-audit「payload_manifest 四类（需求/反馈/源码/工具返回）」 | 含「工具返回」类 | 追加批注：候选 C 下「工具返回」**恒空**（字段保留） |
| §5 出站授权 `receiver` | 泛化 receiver | 不改结构；运营默认 receiver=阿里云百炼（北京地域）为运行时数据 |

## 5. data-model.md

| 位置 | 现状 | 最小建议（待授权） |
|---|---|---|
| `SendAuditRecord.payload_manifest`（L209） | 四类含「工具返回」 | 追加「候选 C 下工具返回恒空」批注（不删字段） |
| `usage` 字段（L125）与 `cost` basis enum（L127） | `input/output/cache` + actual/estimated/unknown | **已兼容**（直接响应 `usage` 落在 input/output；cost 三分类已具备）——无需改 |

## 6. quickstart.md

| 位置 | 现状 | 最小建议（待授权） |
|---|---|---|
| L16、L70–80（FV 阶梯 / 依赖安装 / max_tokens 说明） | 以 SDK wheel/CLI 安装与 FV 阶梯为口径 | 对齐候选 C：去 wheel/CLI 安装步骤；FV-1 记「Messages API smoke 已 PASS」 |

## 7. 明确不构成 / 待办

- 以上均为**最小适配建议**，**未实施**；实施须**单独人工授权**。
- 不修改 spec.md（需求）、宪章、AGENTS.md、ADLL-Knowledge；spec 为最高需求基线，不因
  实现选型改动（其「不锁定特定 SDK/隔离工具/执行框架」条款本身支持候选 C）。
- 建议落地顺序：先 research 附录 A 与 R1 状态标注，再 plan Primary Dependencies 与
  contracts/agent-adapter §6，随后 data-model/quickstart/api-endpoints 的批注。