# Tasks: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环

**Input**: 设计文档 `specs/001-single-repo-approval-loop/`（spec.md R2、plan.md、data-model.md、contracts/、research.md、quickstart.md、ADR-C1/C2/C3/C4、fv1-dev-task-order.md）

**Prerequisites**: spec.md（R2 定稿）、plan.md、data-model.md、contracts/（agent-adapter、api-endpoints）、research.md、quickstart.md、[adr-c4-ai-access-decision-draft.md](./adr-c4-ai-access-decision-draft.md)（Accepted）

**Tests**: **需要**——宪章原则 II（核心状态流转/审批权限/异常流程正常+失败双场景）；后端 pytest、前端 Vitest；Mock 仅作自动化测试替身（FR-009）。

**技术栈**：后端 Python 3.11+（安装验证 3.12.10）+ FastAPI + Pydantic v2 + uvicorn + SQLAlchemy 2.x + Alembic + SQLite；前端 Vue 3 + TypeScript + Vite；Git 子进程 `git` + `git archive`（ADR-C3）；AI 接入 = 候选 C（Messages API 直连 + 自建编排，ADR-C4）。

**路径约定**：后端 `backend/app/…`、`backend/tests/…`、`backend/alembic/…`；前端 `frontend/src/…`、`frontend/`（vite/ts/package）。

**实施顺序纪律（用户 2026-10-20）**：任务管理 → Git 仓库关联 → 方案版本与人工审批 →
**最后**百炼 AgentAdapter；出站授权/审计/权限门禁**必须先于**真实 Messages API 集成；
真实百炼接入**不在本批授权**（须另行人工授权）。

---

## 格式说明

- `[P]`：可并行（不同文件、无未完成依赖）
- `[USn]`：所属用户故事（US1..US5 对应 spec User Scenarios）
- `[门禁]`：安全/审批门禁任务（阻断，先于任何真实 AI 接入）
- 每个任务含明确文件路径与 FR/SC 引用

---

## Phase 1: Setup（工程骨架）

**Purpose**: 前后端最小工程骨架、配置入口、依赖与测试基线（本批已授权；不接入真实仓库/AI）。

- [ ] T001 创建后端骨架：`backend/pyproject.toml`（依赖意图清单，版本/来源/安装范围**待核验**）、`backend/app/__init__.py`、`backend/app/main.py`（FastAPI 应用工厂 + `GET /api/health`）、`backend/app/config.py`（**路径与凭据经环境配置注入，不硬编码绝对路径**，AGENTS.md §3）
- [ ] T002 [P] 统一错误与日志：`backend/app/core/errors.py`（`{code,message,detail?}` 响应模型，禁用 trace/密钥入日志）
- [ ] T003 [P] 前端骨架：`frontend/package.json`、`frontend/vite.config.ts`、`frontend/tsconfig.json`、`frontend/index.html`、`frontend/src/main.ts`、`frontend/src/App.vue`、`frontend/src/router/`、`frontend/src/api/client.ts`（axios/fetch 封装 + 错误映射 + CSRF 头占位）
- [ ] T004 [P] 测试基线：`backend/tests/conftest.py`、`backend/pytest.ini`；前端 `frontend/src/**/__tests__/` 占位 + Vitest 配置
- [ ] T005 环境与依赖清单：`backend/.env.example`、`frontend/.env.example`；`docs/dependencies.md`（**每项第三方依赖：包名==版本、来源、安装范围、是否已安装**——如实记录；本批不自动在线安装）

**Checkpoint**: `py_compile` 静态通过；`/api/health` 可启动（依赖就位后）；未安装依赖导致的未运行如实记录。

---

## Phase 2: Foundational（阻断前置）

**Purpose**: 全部用户故事共享的存储、认证、并发、门禁与 AgentAdapter 抽象。**未完成不得进入任何用户故事。**

- [ ] T006 持久化底座：`backend/app/db.py`（SQLAlchemy 2.x engine/Session，SQLite 路径经 env；WAL；`BEGIN IMMEDIATE` 语义落点）；`backend/alembic/env.py` + Alembic 初始化（ADR-C2）
- [ ] T007 [P] 基础模型与枚举：`backend/app/models/base.py`（DeclarativeBase、TimestampMixin）、`backend/app/models/enums.py`（task/generation/verification/approval status、`cost.basis` actual|estimated|unknown、`usage_basis` actual|unavailable）——对齐 data-model §2 各字段约束
- [ ] T008 [P] [门禁] 会话身份 + CSRF（P0-B）：`backend/app/security/ident.py`（会话语义 + `role=user`；回环≠已认证）、`backend/app/security/csrf.py`（双提交/SameSite=Strict + 自定义头校验；Origin/Referer 纵深）——**Agent/自动化组件无审批会话身份**（FR-041、api-endpoints §通用约定）
- [ ] T009 [P] [门禁] 幂等与并发语义：`backend/app/core/idempotency.py`（`Idempotency-Key` 重放/冲突 409；唯一索引兜底）——支撑 FR-031/038
- [ ] T010 [P] AgentAdapter 抽象 + Mock：`backend/app/agents/base.py`（`generate/cancel/capabilities/self_check` + EventSink 契约，contracts/agent-adapter §4）、`backend/app/agents/mock.py`（**仅测试替身，FR-009**；固定返回合成方案 + usage/cost 三分类样例）
- [ ] T011 [门禁] 出站授权核心 + 审计数据模型：`backend/app/models/outbound.py`（OutboundAuthorization 五条件、SendAuditRecord append-only，`payload_manifest` 四类〔候选 C 下「工具返回」恒空〕）——先于任何真实发送（FR-015/016，data-model §2.9）

**Checkpoint**: 存储/认证/并发/门禁/Adapter-Mock 就绪——用户故事可开始。

---

## Phase 3: US1 — 关联授权仓库并创建开发任务（P1）🎯 最早交付

**Goal**: 关联本地 Git 仓库（绑定完整 commit SHA + object_format）→ 创建任务/需求版本。

**Independent Test**: 关联合法仓库→建任务→显式需求版本；脏工作区提示（FR-003）；非 Git/无授权→失败不建任务。

- [ ] T012 [P] [US1] 仓库关联模型：`backend/app/models/repository.py`（repo_identity、完整 commit SHA（64 hex，P1-01）、object_format sha1/sha256、workspace_status）——FR-001/002/004
- [ ] T013 [P] [US1] 任务与需求版本模型：`backend/app/models/task.py`（Task、TaskRequirementVersion：不可变、seq 唯一、current=max(seq)）——FR-007/008
- [ ] T014 [US1] Git 只读快照适配器（ADR-C3）：`backend/app/adapters/git.py`（子进程 `git`（数组构造、禁 shell）、`git archive`、`rev-parse HEAD`；固定 commit，不自动回退 HEAD）——FR-005/FR-048，遵守 FV-0 边界
- [ ] T015 [US1] 仓库关联/工作区决定服务：`backend/app/services/repository_service.py`（link 只读校验 + workspace-decision；失败提示不建任务）——FR-003/006
- [ ] T016 [US1] 任务/需求版本服务：`backend/app/services/task_service.py`（建任务绑定 baseline；需求正式保存→不可变新版本；非法流转拒绝）——FR-007/027
- [ ] T017 [US1] 端点：`backend/app/api/repositories.py`、`backend/app/api/tasks.py`（`POST/GET /api/repositories/*`、`POST/GET/PUT /api/tasks*`，Pydantic 校验）——api-endpoints §1/§2
- [ ] T018 [US1] US1 测试：`backend/tests/test_repository.py`、`backend/tests/test_task.py`（正常 + 脏工作区/非 Git/无授权/非法流转失败场景；合成 fixture 仓库）

**Checkpoint**: US1 独立可测。

---

## Phase 4: US4 — 人工批准或驳回方案（P1，先于 AI 接入）🔒门禁

**Goal**: 五要素绑定、不可变、有效性分离的审批事件；服务端强制门禁；Agent 无审批路径。

**Independent Test**: 批准→不可变事件；重复/并发批准唯一；v2 不继承 v1；Agent 直连批准接口被拒（S13）。

- [ ] T019 [P] [US4] 方案版本与审批事件模型：`backend/app/models/proposal.py`（ProposalVersion 不可变、ApprovalEvent append-only、五要素绑定、有效性分离）——FR-028/029
- [ ] T020 [US4] 审批服务（服务端门禁）：`backend/app/services/approval_service.py`（事务内三项前置复核〔{v}=当前方案、需求/基准匹配、最新核验=verified〕；唯一索引防重复；旧审批不自动复用失效）——FR-027~033、P0-D
- [ ] T021 [US4] 审批端点：`backend/app/api/approvals.py`（`POST /api/tasks/{id}/proposals/{v}/approve|reject`、`GET /api/tasks/{id}/approvals`；**role=user + CSRF 必需**）——api-endpoints §4、FR-033/041
- [ ] T022 [US4] US4 测试：`backend/tests/test_approval.py`（正常批准/驳回 + 并发唯一 + `approval_target_stale` + 绕过门禁（无会话/无 CSRF/伪造 Origin）失败 + 幂等）——SC-003/004/005、S13

**Checkpoint**: 审批门禁独立可测；**出站授权/门禁先于 US2 AI 接入**（与 Phase 2 T008/T011 共同构成前置）。

---

## Phase 5: US3 — 审阅方案、提交修改意见、生成新版本（P2）

**Goal**: 方案版本链 + 意见触发新版本；新版本不继承审批。

**Independent Test**: 批准 v1 后反馈生成 v2；v2 无有效审批、v1 事件保留（SC-004）。

- [ ] T023 [US3] 反馈与新版本服务：`backend/app/services/proposal_service.py`（显式版本号；新版本不继承审批；差异摘要）——FR-023/025/029
- [ ] T024 [US3] 端点：`backend/app/api/proposals.py`（`GET /api/tasks/{id}/proposals`、`POST /api/tasks/{id}/proposals/{v}/feedback`）——api-endpoints §4
- [ ] T025 [US3] US3 测试：`backend/tests/test_proposal.py`（版本链 + 不继承 + 非法版本号 + 幂等）

**Checkpoint**: 版本链独立可测。

---

## Phase 6: US2 — 真实 AI 生成技术方案（P1，**集成最后**，门禁在前）

**Goal**: 受控只读快照 → Messages API 直连（候选 C/百炼）生成带源码依据的技术方案；进度/展示。

**Independent Test**: 合成 fixture 仓库生成方案，含源码引用（FR-017）；Mock 替身可离线验证全链路。

- [ ] T026 [P] [US2] 生成执行记录模型：`backend/app/models/generation.py`（GenerationExecution：execution_id、status 机、cancel 语义、LateResultRecord、usage/cost 双维度）——FR-027/034/035/038，data-model §2.5
- [ ] T027 [P] [US2] 完整性核验三态模型：`backend/app/models/verification.py`（VerificationAttempt append-only：verified/unconfirmed/failed；当前=最新 attempt 投影）——FR-013/045/046
- [ ] T028 [US2] 授权载荷组装（L1-L3）：`backend/app/services/outbound_assembly.py`（send_manifest 唯一权威 → 物化授权子集 → 实际入模内容〔需求/反馈/源码/工具返回恒空〕+ 敏感排除）——FR-015/016、R5
- [ ] T029 [门禁] 出站闸门强制（L4）：`backend/app/services/outbound_gate.py`（出站白名单 `dashscope.aliyuncs.com`、AuthorizedReceiver 校验、越权/换接收方/范围扩大→403 重新授权、撤销后发送 0）——FR-015、SC-010、api-endpoints §5
- [ ] T030 [US2] 百炼 AgentAdapter 实现：`backend/app/agents/dashscope.py`（单次 POST、**禁重定向、禁代理（ProxyHandler({}))、`max_tokens`/`thinking=disabled`/`stream=false`/`timeout`、`max_retries=0`**、response.usage→cost 三分类、request_id 记录、凭据 env 注入不落明文）——复用 smoke 脚本逻辑收敛；**真实调用须另行人工授权**
- [ ] T031 [US2] 生成编排服务 + SSE：`backend/app/services/generation_service.py` + `backend/app/api/generations.py`（`POST …/generations` 202+execution_id、`GET …/{id}`、`GET …/events` SSE 断线轮询补偿、`POST …/cancel`、`GET …/evidence`、`GET …/send-audit`）——api-endpoints §3
- [ ] T032 [US2] US2 测试：`backend/tests/test_generation.py`（**Mock-first**：合成 canary 文件/反例 stop_reason/usage/截断/超限；真实百炼调用**不在此批**）——FR-009、SC-007、smoke 反例复用

**Checkpoint**: Mock 下 US2 全链路独立可测；真实接入待授权。

---

## Phase 7: US5 — 失败、取消与恢复追溯（P2）

**Goal**: 真实执行状态与失败/取消历史；重启恢复；不覆盖、无隐式批准。

**Independent Test**: 取消→真实结果；迟到结果入 LateResultRecord；重启后任务/版本/审批/历史 100% 恢复。

- [ ] T033 [US5] 失败/取消/恢复服务：`backend/app/services/execution_history.py`（真实状态、failure_reason、LateResultRecord 不改写终态、失败/取消历史追加）——FR-034/035/038/039
- [ ] T034 [US5] US5 测试：`backend/tests/test_recovery.py`（取消竞态、迟到结果丢弃、重启恢复、未确认不进审批）——SC-006/009、FR-045

**Checkpoint**: US5 独立可测。

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: 收尾与跨故事一致性。

- [ ] T035 [P] 前端审批/任务/生成三栏 UI 接线：`frontend/src/views/`（三状态分栏 FR-046；usage/cost 分栏 P1-05）
- [ ] T036 安全收尾：日志脱敏全量扫描、`self_check()` 边界自检接线、S13/S14/S15 运行时探针骨架
- [ ] T037 quickstart 验证：按 [quickstart.md](./quickstart.md) V1~V13 / S1~S15 清单跑通可离线项并记录
- [ ] T038 依赖/安装范围复核：`docs/dependencies.md` 终稿（版本/来源/安装范围/是否安装）提交核验

---

## Dependencies & Execution Order

### 阶段依赖

- Setup(1) → Foundational(2) → 用户故事(3..7) → Polish(8)
- Foundational **阻断所有用户故事**。

### 用户故事顺序（用户 2026-10-20 裁定，非严格 spec P 值排序）

1. US1（关联仓库+任务，P1）—— 最早
2. US4（人工批准/驳回，P1）—— **先于 AI 接入**（审批门禁 + T008/T009/T011 门禁在前）
3. US3（修改意见版本，P2）
4. US2（AI 生成，P1）—— **最后**；真实百炼接入在出站授权/审计/权限门禁完成且另行授权后
5. US5（失败/取消/恢复，P2）

> 说明：spec 用户故事按 P1→P2 编号 US1/US2/US4/US3/US5，但**实现顺序**由「门禁先于真实 AI」与
> 「AgentAdapter 最后接入」裁定决定——US2 的模型/编排可在 Mock 下先行，**真实调用**排最后。

### 每个用户故事内

- 模型 → 服务 → 端点 → 测试（测试须与实现同轮落地：正常+失败双场景）

### 并行机会

- Setup 内 `[P]` 任务；Foundational 内 `[P]` 任务；每个用户故事内的 `[P]` 模型/测试任务；
- 不同用户故事在 Foundational 完成后可并行（若有序分工）。

---

## Implementation Strategy

### MVP（最小）先 US1

1. Setup + Foundational → 2. US1（关联仓库+任务）→ **STOP 验证** → 3. US4（审批门禁）→
4. US3（版本链）→ 5. US2（Mock 全链路）→ 6. US5 → Polish。
**真实百炼调用在另行授权前不执行**（本批仅脚手架 + 任务清单 + Mock 路径）。

---

## Notes

- `[门禁]` 任务与任何真实 AI 发送互斥：未完成即**禁止**发送。
- Mock 仅测试替身（FR-009），不得作为业务功能暴露。
- 每任务完成后：核心路径留 normal+fail 测试；不删测试/不放松断言（宪章原则 II）。
- 新第三方依赖须**先提交核验**（版本/来源/安装范围），本批**不自动在线安装**；缺依赖无法运行的测试**如实记录**，不得宣称通过。