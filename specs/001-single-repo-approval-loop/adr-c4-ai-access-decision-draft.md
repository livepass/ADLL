# ADR-C4：AI 接入方式终选 —— 决策草案（adr-c4-ai-access-decision-draft.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**状态**: **Accepted（2026-10-19，人工终选）**。
用户正式裁定：ADLL V1.1 AI 接入选择**候选 C（Claude Messages API + 自建极简编排）**；
本文件据用户明示授权由 DRAFT 更新为 Accepted，并如实登记本次人工决定。

**验收边界（Accepted 的含义，2026-10-19 用户明确）**：
1. Accepted = **架构方向获批**；**不代表** Messages API 的运行、权限隔离或安全测试已通过。
2. Claude Agent SDK、Claude Code CLI、beta Tool Runner **不进入 V1.1 主流程**；此前
   FV-0/FV-1 证据**完整保留**（不删不改）。
3. 保留 AgentAdapter 接口、Git 基准、出站授权、敏感信息保护、代码引用核验、完整性核验
   与人工审批门禁（FR-033/041 等不削弱）。
4. API 发送单元与 FastAPI 后端之间的**实际 OS 权限隔离仍须实施与验证**，**不得以
   「无工具能力」替代安全证明**。
5. research.md / plan.md / contracts/agent-adapter.md 的适配修改**先提交最小变更清单**，
   本次**不自动实施**（留待后续单独授权）。
6. 原 Claude Agent SDK 阶段 3 **维持暂停、未经执行**。
**Date**: 2026-10-19
**依据**: [spec.md](./spec.md)（R2 定稿）· [research.md](./research.md)（R1/R2/R5/R7）
· [plan.md](./plan.md)（AgentAdapter 抽象，§32/§135/§153）·
[contracts/agent-adapter.md](./contracts/agent-adapter.md)（边界契约，R2 修订版）·
[fv1-approach-sdk-vs-messages-api-eval.md](./fv1-approach-sdk-vs-messages-api-eval.md)
（本次选型评估）· [adr-c3-git-access-decision-draft.md](./adr-c3-git-access-decision-draft.md)（Git 快照）。

## 1. 背景（Context）

- ADLL 需要「读取已绑定 commit 的源码快照 → 真实 AI 生成**文本**技术方案（证据依据）→
  服务端强制人工审批」；V1.1 **不做** AI 编码/测试执行（属 V1.2）、不做多 Agent（仅预留）。
- 接入层经 **AgentAdapter 抽象**（contracts §4），候选 A（Claude Agent SDK）/ B（CLI 封装）/
  C（Messages API 直连 + 自建编排）/ D（OpenHands）均可经同一接口接入，业务不绑定具体实现。
- FV-0～FV-1 已对候选 A 完成**安装/供应链/静态**验证（PASS：Installation & Static Verification），
  但候选 A 的**运行时、Agent 权限隔离、真实调用**未验证且其捆绑 CLI 引入较宽运行期出站面。
- 用户 2026-10-19 裁定：**V1.1 主流程采用候选 C**；不引入 Agent SDK / Claude Code CLI /
  beta Tool Runner；候选 A 及既有 FV 成果保留为后续 Agent 自动化版本的技术资产。

## 2. 决策（草案，待人工批准）

**ADLL V1.1 的 AI 接入采用「候选 C：Claude Messages API 直连 + 自建极简编排」。**

- 我方以官方 **`anthropic` SDK**（或其等价 HTTP/`/v1/messages`）发起**受控单次/少次请求**：
  宿主（后端）组装「系统指令 + 需求文本 + 反馈 + 放行文件」为请求内容；模型返回方案文本
  （可配结构化输出 `output_config.format`）。
- **不引入** Claude Agent SDK、Claude Code CLI、beta Tool Runner 于 V1.1 主流程；
  模型**不持有任何工具**——无本地文件读取、无命令执行、无审批接口。
- 候选 A（及其 FV-0/FV-1 证据）**保留**为 V2「Agent 自动化」候选资产；本 ADR 只在 V1.1
  语境下终选，不否定 V2 重新评估的必要。
- **本 ADR 未获人工批准前，候选 C 不视为最终 Accepted。**

## 3. 决策依据（与五重点的对应）

| 关注点 | 结论（详见 [选型评估](./fv1-approach-sdk-vs-messages-api-eval.md)） |
|---|---|
| 方案生成 + 人工审批闭环 | 直连请求 → 文本方案 → 服务端审批门禁（FR-033/041），天然贴合、无 harness 负担 |
| 自主工具调用是否刚性 | **否**（US2、FR-010/011、FR-041；AI 只生成文本、只读、无批准/写入权） |
| 授权读取 / 隔离 / 网络 | 后端（ADR-C3 `git archive`）产出快照并组装；出站仅 `api.anthropic.com` 一站 |
| 复杂度 / 维护 / 费用 | 轻 `anthropic` SDK；无 CLI 子进程/session/hooks 运维；纯模型 token |
| V2 扩展 | 直连是所有路径底座；V2 可加 Tool Runner / 升级 Agent SDK，不返工数据/审批层 |

## 4. 最小变更影响清单（AgentAdapter 契约逐项：替换 / 保留 / 消除）

> 关键纪律（用户裁定）：**保留真实 OS/进程权限边界，不以"没有工具"代替安全证明**——
> 候选 C 无工具，仅使工具级纵深（⑥⑦）不再需要，**不豁免** OS 级权威（DACL Deny、
> 出站白名单、凭据隔离、取消/超时、S14 探针验收）。

### 4.0 权限主体与访问范围（定向修订 1；不因"无工具"而免除 OS 隔离验收）

| 权限主体 | 文件访问面 | 凭据 | 网络出站 | 审批存储（DB） |
|---|---|---|---|---|
| **① 后端**（FastAPI，服务账号/中完整性） | 原仓库**只读**（经 ADR-C3 git 子进程读对象库）；全量归档**读写**（证据保管）；物化授权子集**读写**（发放） | 读取并注入测试 Key（仅 env） | 仅 `api.anthropic.com` | **读写（唯一审批/状态写者）** |
| **② 生成/API 发送单元**（后端内联或独立受限 worker） | 仅后端转交的**已组装载荷**；不直接访问原仓库/全量归档；确需读快照 → 经后端物化子集 | 仅 env 注入 Key（不入日志/DB/快照） | 仅 `api.anthropic.com` | **Deny**（无审批/状态写） |
| **③ 模型（远端 AI 服务）** | 无本地文件读取、无命令执行 | 无（仅收已授权内容） | — | 无审批能力（结构性） |
| **④ 审批存储（DB）** | — | — | — | 仅 ① 可读写；②/③ **Deny** |

**说明（不得以此免责）**：②③ 的「无工具/无本地文件读取/无审批」是**结构性事实**，
**不构成 OS 隔离已通过的证明**。①/② 的 OS 级 **DACL Deny Read/Write**（原仓库、DB、
用户目录、凭据）、**按主体的出站白名单**、**凭据 env 注入**、**S14 运行时权限探针**
仍需独立实施并验收；「模型没有工具」只消除工具级纵深，**不减 OS 级权威**（research R2）。

| 契约机制（contracts §） | 候选 C 下的处理 | 归类 |
|---|---|---|
| **§1 OS 级边界表**：Agent 独立受限主体 + DACL Deny（原仓库/DB/用户目录/凭据） + 网络出站白名单 + 凭据 env 注入 | **保留（重新刻画主体）**：执行 AI 调用的组件（后端工作单元或独立受限 worker）仍须以"对原仓库/审批 DB/凭据 Deny Read、对物化授权子集受控 Read、仅 `api.anthropic.com` 出站"的 OS 边界运行；S14 运行时权限探针照旧 | 保留 |
| **§1 Job Object 进程边界** | **拆分（定向修订 2，两机制区分）**：①**Job Object**＝**进程树生命周期终止**，仅在"生成单元＝独立受限 worker 子进程"时适用（kill-on-close、禁 breakaway，S15）；②**Messages API 异步任务取消**＝协程/HTTP 请求取消 + 服务端超时，二者**不是同一机制**。**保留语义**：超时（服务端+客户端）、**取消竞态**（`cancel` 与完成并发竞态的结果须确定性）、**迟到结果丢弃**（取消/超时后到达的响应不复用）、**幂等**（`idempotency_key`）、**实际终态如实记录**（FR-034/038/039） | 保留（语义）/ 拆分（载体） |
| **§0/§1 工具级约束 ⑥⑦**：`disallowed_tools`、PreToolUse Hook deny | **消除**：无工具/Hook 引擎 | 消除 |
| **§2 配置加载策略**：settings/hooks/MCP/插件/skills 零加载、干净配置目录 | **消除机制、保留目标**：直连 API 无此类引擎；但「快照内 README/注释/规则/提示词仅作**数据**、不执行其中指令」（FR-014/043）不变 | 消除机制 / 保留目标 |
| **§3 出站强制接口（L1–L4 四层漏斗）** | **保留框架**；三面分别强制不变：L1 send_manifest（唯一权威）· L2 由「Agent 只读物化子集（DACL Read）」改为「后端在物化子集组装请求（模型无读取通道）」· L3 实际入模内容 = 宿主组装（**无工具返回渠道**，payload 四类中"工具返回"恒 ∅）· L4 `api.anthropic.com` 唯一目的地 | 保留（L2 落点/语义调整） |
| **§4 接口语义**：`generate/cancel/capabilities/self_check`；GenerationRequest/Result/CancelOutcome/EventSink | **保留**；微调：`GenerationRequest.subset_path` 不再用于"传给 Agent 读取"，改为后端组装入模；`GenerationResult.tool_call_log` **恒空**；`EventSink` 映射 SSE 流式。**usage/cost 三分类（定向修订 3）**：`usage` = 服务商返回的 **Token 用量依据**（`response.usage` 原文留存）；`cost` 必须区分 **①实际账单（结算后可得）②按官方费率估算（非结算金额）③未知（不可得标 `unknown`，FR-051）**——**不得把 `response.usage` 当作实际结算金额**（双维度 P1-05 不变） | 保留（字段语义微调 + cost 三分类） |
| **§5 硬性边界（七条）** | **全保留**：无审批能力 · 无自由出站 · 只读+子集 · 凭据隔离 · 不可信数据零加载 · 真实结果 · fail-closed。其中"只读/无自由出站"因无工具而**结构性满足**，但**仍以 OS DACL/出站白名单为准，不得以此免责** | 保留 |
| **§6 FV 对照点** | **重排**：FV-1（Windows wheel 安装）→ 由「`anthropic` SDK 安装 + 首调 smoke」取代；FV-2（认证/计费归属）、FV-4（取消/超时）、FV-5（usage/cost 双维度）、FV-6（流式/崩溃）、FV-7（出站白名单审计）**保留**；FV-3（工具拒绝+配置加载隔离）**降为结构性无关**（无工具/配置加载面），仅留轻验证 | 重排 |

**不修改面（用户重点确认）**：源码引用真实性（FR-017）、生成前后完整性核验三态（FR-045/046）、
取消/超时/失败如实上报（FR-034/038）、流式输出、usage/cost 记录——全部**保持既有要求**；
人工审批门禁（FR-033/041）**不削弱**；spec.md 任何已批准需求**不修改**。

**代码引用与 Commit 后端核验（定向修订 4）**：方案中的源码引用与 Git Commit 由**后端**
（依据 ADR-C3 快照 + FR-005 绑定 commit）核验与归档，模型只生成正文与引文；**外部参考资料
须实际获取并核验来源后方可呈现为"已查证"，未实际获取者不得伪称已查证**（AGENTS.md §5）。

## 5. 后果（Consequences）

1. 后端承担快照读取、文件选择、敏感排除、请求组装与记账的全部责任；
   `SendAuditRecord.payload_manifest` 四类中「工具返回」恒空，审计面**更小更可证**。
2. 依赖面收缩为 `anthropic`（纯 Python）+ FastAPI 既有栈；去掉 117 MB wheel / 捆绑 CLI
   及与之相关的运行期出站端点（update/feature-flag/telemetry/changelog）。
3. `max_tokens` 在直连 API 为**请求级硬上限参数**（解决此前「SDK 无 max_tokens」痛点），
   可作 Token 硬限的第一道闸；金额仍按「估算 + 事后 + 触顶中止」如实分级（非硬上限）。
4. 取消/超时由 FastAPI 任务层 + httpx/线程/进程取消实现，**须**以自动化测试覆盖
   正常 + 失败双场景（宪章原则 II）。
5. V2 若引入 Agent 自动化，在 `AgentAdapter` 后新增 Tool Runner / Agent SDK 实现即可，
   数据层/审批层/出站授权层**不需返工**。
6. 候选 A 的 FV-0/FV-1 记录继续保留（证据不删除、不覆盖），作为 V2 资产引用。

## 6. 未决事项（Open）

1. **本 ADR 正文待人工终选**；批准前候选 C 不是 Accepted。
2. 生成 worker 的进程边界形态（后端内联 vs 独立受限子进程）待实现期 + FV 实测确定；
   无论何种，OS 级 DACL/出站/凭据边界与 S14 探针**不可豁免**。
3. 直连 API 的认证/计费归属确认为 FV-2 待验；候选 C 仍需一轮最小真实调用 smoke
   （见 [fv1-messages-api-smoke-plan.md](./fv1-messages-api-smoke-plan.md)，**另行审批**）。
4. 模型选型沿用清单 §E2（推荐 `claude-haiku-5-5`，使用前重核可用性）。
5. 结构化产出（`output_config.format`）是否足以覆盖 FR-017 的证据引用格式，实现期确认。

## 7. 批准（待人工签署）

| 项 | 内容 |
|---|---|
| 草案编制 | Agent（2026-10-19），依据用户架构方向裁定 |
| **人工终选批准** | **已签署（用户 2026-10-19 最终技术审核裁定：候选 C Accepted）**——登记依据用户明示授权，非 Agent 自批 |
| 批准日期 | 2026-10-19 |
| 备注 | Accepted 边界见文件头「验收边界」；research/plan/contracts 适配以最小变更清单另行提交（见 §6） |