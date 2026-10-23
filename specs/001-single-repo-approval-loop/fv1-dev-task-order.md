# ADLL V1.1 开发任务清单 —— 草案（fv1-dev-task-order.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**Date**: 2026-10-19
**性质**: **开发任务顺序草案（未授权实施）**。依 [spec.md](./spec.md)（R2）、[plan.md](./plan.md)、
[ADR-C4（Accepted）](./adr-c4-ai-access-decision-draft.md)、[合约](./contracts/agent-adapter.md)
编制；**优先顺序**：任务管理 → Git 仓库关联 → 方案版本与人工审批 → 百炼 AgentAdapter。
**本轮不授权 /speckit-implement、业务编码、新 API 调用、依赖安装、Git Commit/Push；**
正式 `tasks.md`（/speckit-tasks）生成与实施须**另行授权**。

**技术栈（已批准）**：后端 Python + FastAPI + Pydantic + uvicorn；存储候选 SQLite +
SQLAlchemy 2.0（ADR-C1/C2 待批）；Git 访问候选子进程 `git` + `git archive`（ADR-C3 待批）；
前端 Vue 3 + TypeScript + Vite；测试 pytest（后端）+ Vitest（前端）——宪章/AGENTS.md §2。

## 0. 阻塞前置（进入 Phase 1 前必须就绪/批准）

| # | 前置 | 状态 |
|---|---|---|
| D0 | 正式批准充分：ADR-C1（SQLite）、ADR-C2（SQLAlchemy 2.0）、ADR-C3（子进程 Git + archive，现为 **DRAFT**） | 待人工批准 |
| D1 | 落地 [契约/文档最小适配](./adr-c4-docs-adaptation-suggestions.md)（research/plan/contracts 标注） | 待授权 |
| D2 | 路径经环境配置注入的键名定稿（AGENTS.md §3，禁硬编码绝对路径） | 实现期定 |
| D3 | `task`/`proposal`/`approval`/`audit` 等域模型的 Pydantic schema 定稿（对齐 data-model） | 随 Phase 各步 |

> 说明：若 D0 未在实现启动前完成，Phase 2+ 的存储/Git 层只能以「候选口径 + 适配层」先行，
> 不锁定最终选型（spec「不锁定特定 SDK/隔离工具/执行框架」同样适用于存储/ORM 的候选表述）。

## Phase 1 —— 工程骨架（backend + frontend + 测试基线）

| Task | 内容 | 依赖 | 验收 |
|---|---|---|---|
| T1.1 | 后端 FastAPI 骨架：应用工厂、配置（env 注入，无硬编码路径）、`/api/health`、统一错误 `{code,message,detail?}`、Pydantic v2 | D2 | 服务可启动；配置路径经 env |
| T1.2 | 前端 Vue3+Vite 骨架：路由、API client（按 [api-endpoints](./contracts/api-endpoints.md)）、三状态分栏占位（FR-046） | — | 页面可构建；无 TypeScript 报错 |
| T1.3 | 测试基线：pytest/vitest 空跑 + fixture 约定；CI 风格测试命令 | — | 空测试绿 |

## Phase 2 —— 任务管理（优先）

| Task | 内容 | 依赖 | 验收（FR 引用） |
|---|---|---|---|
| T2.1 | 域模型：Task、TaskRequirementVersion；SQLite 迁移 + 唯一索引/WAL（ADR-C1/C2 候选口径） | T1.1, D0 | FR-007（需求版本） |
| T2.2 | 任务 CRUD API（`POST/GET /api/tasks*`）+ Pydantic 校验 + 前端列表/详情 | T2.1 | FR-008（历史多条）+ api-endpoints §2 |
| T2.3 | 任务/需求版本状态机（非法转移拒绝 + 审计） | T2.1 | FR-027；正常+失败双场景 |

## Phase 3 —— Git 仓库关联（优先）

| Task | 内容 | 依赖 | 验收 |
|---|---|---|---|
| T3.1 | GitRepository 关联模型 + 只读校验（路径有效/非 Git/无授权 → 失败提示，不建任务） | T2.* | FR-001/002/004 + api-endpoints §1 |
| T3.2 | 绑定完整 commit SHA + object_format（sha1/sha256）+ workspace_status；HEAD 变化不改绑定（ADR-C3 git archive 只读快照） | T3.1, D0 | FR-005/048；FR-003/006（不改工作区） |
| T3.3 | 关联/解绑/工作区决定 API + 前端 + 异常路径测试 | T3.2 | api-endpoints §1 + 宪章原则 II |

## Phase 4 —— 方案版本与人工审批（优先，核心门禁）

| Task | 内容 | 依赖 | 验收 |
|---|---|---|---|
| T4.1 | 数据模型：PlanVersion、ApprovalEvent（五要素绑定、append-only、不可变、有效性分离）；核验三态 | T2.* | FR-028/029/045/046 + data-model |
| T4.2 | 审批 API（`approve`/`reject`，**显式版本号**）；服务端同事务三项前置复核；`role=user`+CSRF；**Agent 无审批身份** | T4.1 | FR-031/033、P0-B、api-endpoints §4 |
| T4.3 | 审批有效性判定（新版本不继承、需求/基准变更失效、旧事件保留）；防重复批准 | T4.1 | FR-027~033、SC-003/004 |
| T4.4 | 状态流转/权限/异常测试（正常+失败）；`approval_target_stale`、`idempotency_conflict` 等并发语义 | T4.1–T4.3 | api-endpoints《并发冲突语义表》 |

## Phase 5 —— 百炼 AgentAdapter（最后）

| Task | 内容 | 依赖 | 验收 |
|---|---|---|---|
| T5.1 | 实现 `AgentAdapter` 接口语义（`generate/cancel/capabilities/self_check` + EventSink）——contracts/agent-adapter §4 | T4.* | 契约对齐 |
| T5.2 | 授权载荷组装：L1 send_manifest / L2 物化子集 / L3 入模内容 / L4 出站（dashscope 单点）；SendAuditRecord 记账 | T5.1 | R5、data-model 2.9、FR-015/016 |
| T5.3 | 直连调用器：单次、禁重定向、禁代理、`max_tokens`/`thinking=disabled`/`stream=false`/`timeout`、`usage`/`cost` 三分类、request_id 记录；凭据 env 注入 + 不落明文 | T5.1（复用 smoke 脚本逻辑收敛） | smoke 验收记录 + FR-042 |
| T5.4 | 取消/超时/幂等/actual 终态（async 取消 + 迟到结果丢弃） | T5.3 | FR-034/038/039 |
| T5.5 | AgentAdapter 单元测试（假响应/反例：stop_reason、usage、文本类型等） | T5.3 | 宪章原则 II；复用 smoke 反例 |

## Phase 6 —— 生成执行/审计/端到端（收尾，spec 全量）

| Task | 内容 | 依赖 | 验收 |
|---|---|---|---|
| T6.1 | 生成执行记录（执行 ID/状态/失败/取消历史）+ SSE 进度（EventSink；断线轮询补偿，细节-3） | T5.* | FR-038/039 + api-endpoints §3 |
| T6.2 | usage/cost 双维度展示（usage_basis + cost basis 三分类；未知不显示金额） | T6.1 | P1-05、data-model |
| T6.3 | 出站授权五条件 + 敏感排除 + 撤销后发送 0；`send-audit` 审计（工具返回恒空） | T5.2 | FR-015/016、SC-010、api-endpoints §5 |
| T6.4 | 前后端集成 + SC 验收回归（SC-001~011 相关项） | 全部 | spec §SC |

## 实施顺序依赖图（要点）

```
D0/D1 前置
  └─ Phase1 骨架
       ├─ Phase2 任务管理 ──┐
       ├─ Phase3 Git 关联 ──┤
       └────────────────────┴─ Phase4 方案版本+审批（核心门禁）
                                    └─ Phase5 百炼 AgentAdapter
                                         └─ Phase6 执行/审计/E2E
```

- **优先**：任务管理、Git 关联、方案版本/审批三者先于任何 AI 调用实现——审批门禁
  （FR-033/041）作为**服务端不可绕过**能力，在接入 AI 前必须已可独立测试（可先以
  AgentAdapter Mock 打通，FR-009 自动化 Mock 除外）。
- 候选 C 的直连调用器（T5.3）**最后**接入真实模型；其正确性先以合成反例 + Mock 覆盖。

## 明确不构成 / 待办

- 本清单为**草案**；正式生成 `tasks.md` 与 `/speckit-implement` 实施**须另行授权**。
- 不授权本轮：业务代码修改、新 API 调用、依赖安装、Git Commit/Push、
  `/speckit-implement`；不修改宪章、spec.md、AGENTS.md、ADLL-Knowledge（及批准文档）。