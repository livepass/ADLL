# Implementation Plan: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环

**Branch**: `001-single-repo-approval-loop`（仅目录名；未创建 Git 分支，
创建分支须用户单独批准） | **Date**: 2026-10-17 | **Spec**: [spec.md](./spec.md)
（Approved R2 — 2026-10-17 人工批准）

**Input**: Feature specification from `specs/001-single-repo-approval-loop/spec.md`

**审批记录**: 技术规划 R2（含最终安全边界修订 P0-A～D/P1 细节 1～4 与
三处勘误）已获**人工批准**（2026-10-18，批准人：用户）作为 V1.1 设计
基线。该批准**不代表**技术可行性已验证（FV 未执行），**不包含**任何
FV 执行、依赖安装、付费调用或编码实施授权；FV-0 执行另待单独批准。

**Revision**: R2 技术设计修订版（2026-10-17，第二轮定向修订 + 最终安全
边界/一致性修订）——修复 P0-01～P0-05 阻断项、P1-01～P1-05 重要项，
以及 P0-A（Windows 读取隔离/安全主体矩阵/探针/Job Object 逃逸）、
P0-B（审批 API 身份与 CSRF）、P0-C（物化授权子集与三面出站）、
P0-D（批准目标版本规则与事务一致性）、P1 细节 1～4（FV-0 归档差异
检查、S12 目标收窄、SSE 续传承诺收窄、费用限制可强制性）；**未修改**
spec.md 与 checklists/requirements.md；候选选型未定稿。

## Summary

在既定技术路线（Python + FastAPI + Pydantic / Vue 3 + TypeScript + Vite）
上构建模块化单体 Web 应用：关联一个授权本地 Git 仓库（绑定完整 commit
SHA 快照，兼容 SHA-1/SHA-256 对象格式）→ 任务与需求版本管理 → 真实 AI
受控只读生成技术方案（证据依据）→ 版本化修改意见 → 服务端强制的人工
审批门禁（五要素绑定、不可变事件、有效性分离）→ 全量持久化与恢复。
配套：出站源码授权（四层强制漏斗 + 复用五条件）、完整性核验三态分离
（核验尝试 append-only）、取消/失败语义、usage/cost 独立双维度展示。

技术关键路径：Agent 接入经 **AgentAdapter 抽象**（**候选 C：Messages API 直连 + 自建
编排，ADR-C4 已批**；不引入 Claude Agent SDK / Claude Code CLI / beta Tool Runner，
候选 A 及既有 FV 证据保留）；存储 SQLite + SQLAlchemy 2.x（部分唯一索引 + WAL +
事务 CAS 支撑幂等与并发收敛，ADR-C1/C2 已批）；Git 快照 `git archive`（worktree 对
原仓库 .git 元数据有写入，默认弃用）；安全边界以 **OS 级隔离为权威**
——读取隔离依赖 **DACL 显式拒绝**（低完整性仅限写、路径不传 ≠ 隔离），
Agent 仅可读物化授权子集（全量归档仅后端证据保管）；审批接口服务端
会话身份 + role=user + CSRF（Agent 无审批身份）；Job Object 纳管并禁用
breakaway；上述机制均为候选配置待 FV/探针实测。工具拒绝规则与 Hook
仅为纵深防御，提示词无效力。

## Technical Context

**Language/Version**: Python 3.11+（安装验证已用 3.12.10；直连方案无 SDK 下限约束）；TypeScript 5.x（Vue 3 + Vite）

**Primary Dependencies**: FastAPI、Pydantic v2、uvicorn、SQLAlchemy 2.x
（ADR-C2 已批）、Alembic（迁移，随 SQLAlchemy）；前端 Vue 3、Vite、
Vitest；Git 访问子进程 `git` + `git archive`（ADR-C3 已批）。AI 接入 =
**候选 C（Messages API 直连 + 自建编排，ADR-C4 已批）**：官方 `anthropic` SDK 或等价
HTTP（Anthropic 兼容端点，默认阿里云百炼 `dashscope.aliyuncs.com/apps/anthropic`）；
**不引入** claude-agent-sdk / Claude Code CLI / beta Tool Runner

**Storage**: SQLite（ADR-C1 候选，单用户本地）+ 证据文件引用存储；
路径经环境配置注入，不硬编码（AGENTS.md §3）

**Testing**: pytest（后端）、Vitest（前端）；核心状态流转/审批权限/异常
流程覆盖正常+失败（宪章原则 II）；Agent Mock 仅限自动化测试（FR-009）

**Target Platform**: Windows 11 本地单用户（运行环境）；Agent SDK 发布物
含 Windows wheel（已核实）但实机行为待 FV-1 验证

**Project Type**: Web 应用（模块化单体：backend + frontend，宪章原则 V）

**Performance Goals**: 生成为分钟级长任务（流式进度）；审批/查询类操作
亚秒级响应；单用户无高并发需求

**Constraints**: 本地功能离线可用；出站仅授权范围内容（四层漏斗强制）；
敏感信息不落日志/方案/费用信息；不执行目标仓库脚本代码；目标仓库
settings/Hooks/MCP/插件零加载；无微服务/分布式；不 Fork OpenHands/Dify、
不引入 LangGraph；Git 对象 ID 兼容 SHA-1（40 hex）/SHA-256（64 hex）；
变更类 API 支持 Idempotency-Key；生成异步（202+SSE）

**Scale/Scope**: 单用户、单活跃关联仓库、单轮最小闭环为主；历史任务/
版本/审批记录多条持久保留

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 宪章原则 | 本规划符合性 | 状态 |
|---|---|---|
| I 闭环体验优先 | 全流程网页操作（SC-001/FR-040）；不复制提示词；非 IDE | ✅ |
| II 测试不可协商 | pytest/Vitest；正常+失败双场景；quickstart 映射 SC/S 清单；禁止删测试 | ✅ |
| III 审批门禁与真实权限边界 | 先方案后编码（本 plan 待人工批准后才编码）；五要素绑定+不可变+服务端门禁（FR-028~033）；三层真实权限约束（FR-012） | ✅ |
| IV 知识真实性与单一事实来源 | V1.1 证据依据（FR-017~023）；知识教学实践属 V1.3（不在本版本，无冲突） | ✅ |
| V 简单架构与可验证工程 | 模块化单体；重要选型全部走 ADR 候选 + 人工批准；Pydantic 全量校验 | ✅ |

- 规则层级核验：constitution（v1.2.0 RATIFIED）> AGENTS.md > CLAUDE.md，
  无冲突；本规划未预锁 Agent SDK/ORM/DB（FR-024/FR-044/AGENTS.md §2）。
- 无违规项，Complexity Tracking 无需填写。

**Post-design re-check（Phase 1 后复评；R2 最终安全修订后复评）**:
data-model/contracts/quickstart/research 均为契约与验证层设计；R2 修订
补强了权限隔离边界（P0-01）、出站强制（P0-02）、状态一致性（P0-03）、
快照证据（P0-04）与 FV 计划（P0-05）；最终安全修订进一步明确：
①读取隔离以 DACL 显式拒绝为准（低完整性仅限写、路径不传 ≠ 隔离），
含安全主体矩阵、运行时权限探针与 Job Object 逃逸测试（P0-A）；
②审批接口服务端身份鉴别/授权/CSRF 三件套 + Agent 直连拒绝（P0-B）；
③Agent 仅读物化授权子集，出站三面（读权限/入模内容/网络目的地）分别
强制，FV-7 合成数据 + 未验证标注（P0-C）；④仅当前有效方案版本可批准，
前置复核与事件写入同事务，过期返回 approval_target_stale（P0-D）；
⑤S12/SSE/费用限制承诺按证据能力收窄（P1 细节 2～4）。全部为收紧而非
放宽；未引入新依赖、未改变技术路线、未越权决策选型（候选均待 ADR +
人工批准）；未发现与 spec.md R2 的需求冲突；门禁结论维持 ✅ 不变。

## Project Structure

### Documentation (this feature)

```text
specs/001-single-repo-approval-loop/
├── spec.md              # 需求规格（Approved R2，2026-10-17）
├── plan.md              # 本文件（/speckit-plan 输出）
├── research.md          # Phase 0：调研/ADR 候选/FV 受控验证计划
├── data-model.md        # Phase 1：实体、状态机、校验规则
├── quickstart.md        # Phase 1：端到端验证与安全验收清单
├── contracts/           # Phase 1
│   ├── api-endpoints.md # REST + UI 契约
│   └── agent-adapter.md # Agent 接入中立边界契约
├── checklists/
│   └── requirements.md  # 规格质量清单（16/16）
└── tasks.md             # Phase 2（/speckit-tasks 输出，本次不创建）
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── main.py              # FastAPI 组装
│   ├── config.py            # 环境配置注入（路径/凭据；不硬编码）
│   ├── api/                 # 路由层（Pydantic 输入/输出模型）
│   ├── domain/              # 实体、状态机、审批有效性判定（单一实现）
│   ├── services/            # 任务/生成/审批/授权服务
│   └── adapters/            # git、agent(AgentAdapter)、storage 适配
└── tests/                   # pytest：unit/integration/contract
    ├── unit/
    ├── integration/
    └── contract/

frontend/
├── src/
│   ├── pages/               # 关联/任务/生成/审批/历史视图
│   ├── components/
│   ├── services/            # API 客户端
│   └── stores/              # 状态管理
└── tests/                   # Vitest
```

**Structure Decision**: 采用 Option 2（web application：backend + frontend）
的模块化单体布局，目录如上。domain 层集中状态机与审批规则以满足
"服务端强制、单一实现"（FR-027/033）；adapters 层隔离 Git 与 Agent
引擎（AgentAdapter，见 contracts/agent-adapter.md），确保选型可替换。

## Complexity Tracking

无违规项，无需填写。
