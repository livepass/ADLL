# Phase 1 数据模型（data-model.md）— R2 修订版

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**Date**: 2026-10-17（R2 技术设计第二轮定向修订） | **Spec**: [spec.md](./spec.md)（未修改）
**存储候选**: SQLite + SQLAlchemy 2.0（ADR-C1/C2 候选，终选待人工批准）
**通用规则**: 时间戳 UTC ISO-8601；主键 UUID/ULID 字符串；内容摘要 SHA-256。

## 0. 双层一致性模型（P0-03 核心）

```text
历史事件层（append-only；应用层禁止 UPDATE/DELETE，DB 层尽力约束）
  RequirementVersion · ProposalVersion · ApprovalEvent · Feedback ·
  GenerationExecution（终态冻结）· VerificationAttempt · LateResultRecord ·
  SendAuditRecord · SecurityEvent · AuditLog
当前状态层（可变投影；事务内更新；可由历史重算）
  Task.current_* · AnalysisBaseline.availability ·
  OutboundAuthorization.status · GenerationExecution 当前状态投影
```

- **不变式 1**：投影更新与对应事件写入在同一 DB 事务（`BEGIN IMMEDIATE`）。
- **不变式 2**：执行/审批/核验**终态不可改写**；后续事实以新行记录
  （LateResultRecord、VerificationAttempt）。
- **不变式 3**：AuditLog 记录 actor（user/agent/system）、动作、前后状态
  摘要、时间戳；哈希链（prev_hash）为增强候选（ADR 定）。
- 校验：定期/启动时重算投影 vs 事件历史，不一致告警（可验证工程）。

## 1. 实体总览

```text
GitRepository 1─* Task 1─* RequirementVersion
                    │ 1─* AnalysisBaseline 1─* SnapshotArchive
                    │                    └ 1─* MaterializedSubset（每执行一集，用毕销毁）
                    │ 1─* GenerationExecution 1─* VerificationAttempt
                    │ │                    └ 0..* LateResultRecord
                    │ 1─* ProposalVersion 1─* ApprovalEvent
                    │ 1─* Feedback
                    └ 1─* OutboundAuthorization 1─* SendAuditRecord
IdempotencyRecord（独立）· SecurityEvent（独立）· AuditLog（独立）
```

## 2. 实体明细

### 2.1 GitRepository

| 字段 | 类型 | 规则 |
|---|---|---|
| id / repo_identity / local_path | | 路径经环境配置注入（AGENTS.md §3） |
| object_format | enum: sha1/sha256 | 关联时 `git rev-parse --show-object-format` 记录（P1-01） |
| default_branch / workspace_status | | workspace_status ∈ clean/dirty |
| active | bool | 活跃关联唯一（V1.1 单活跃） |

### 2.2 Task 与状态机（不变式：非法转移拒绝+审计）

```text
draft → ready → generating → reviewing → approved ──(用户主动提交修改意见)──→ generating（新一轮，循环同上）
                │              │            │
                ▼              ▼            ▼
             failed ──────→ reviewing   rejected → reviewing
```

- **批准后迭代（明确语义）**：已批准方案经**用户主动提交修改意见**后，
  允许进入新一轮 `generating → reviewing` 流程；由此产生的新
  ProposalVersion **不继承旧审批**（FR-025/029），旧 ApprovalEvent
  保留且仅对其绑定的旧版本有效（V4/SC-004）。

| 字段 | 类型 | 规则 |
|---|---|---|
| current_requirement_version_id / current_baseline_id | FK | 当前指针（投影） |
| current_proposal_version_id | FK? | = max(seq) 的 ProposalVersion（选择规则见 2.7） |
| status | enum | 上图 |

### 2.3 RequirementVersion（不可变）

| 字段 | 类型 | 规则 |
|---|---|---|
| seq | int | 唯一（task_id, seq）；分配在 `BEGIN IMMEDIATE` 事务内 |
| content / content_hash | | 仅正式保存并提交创建（FR-007，Q1）；草稿不落版本 |

### 2.4 AnalysisBaseline + SnapshotArchive（P0-04）

| 字段 | 类型 | 规则 |
|---|---|---|
| full_commit_sha | str(40\|64) | 见 §3 SHA 适配；完整、非缩写（FR-002） |
| object_format | enum | 继承仓库并复核 |
| workspace_decision | text | 脏工作区处理决定（FR-003） |
| availability | enum: available/unavailable | Commit 丢失/不可验证 → unavailable（FR-048） |
| snapshot_method | enum: git_archive/git_clone/local_clone | 默认 git_archive；worktree 仅授权后 |
| origin_metadata | json | 归档命令、时间戳、对象格式 |

**SnapshotArchive（内容寻址证据副本）**：

| 字段 | 类型 | 规则 |
|---|---|---|
| baseline_id | FK | |
| archive_sha256 | str(64) | tar 归档内容寻址 |
| storage_ref | str | 隔离存储位置引用 |
| retained_until | datetime | 终态+核验完成后默认 30 天（可配置） |
| origin_verified | bool | 归档哈希独立复核结果 |

保留策略：引用它的全部执行达终态且核验完成前不得清理；
Commit 丢失后仍可凭归档复盘历史，但新生成/新审批仍被阻止（FR-048）。

**MaterializedSubset（P0-C：Agent 物理可读面）**：

| 字段 | 类型 | 规则 |
|---|---|---|
| execution_id / baseline_id | FK | 每次生成独立一集 |
| manifest | json | 物化文件清单：路径 + SHA-256 + 数据类型（= send_manifest 放行集） |
| storage_ref | str | 物化只读目录引用（DACL 仅授予 Agent 主体 Read） |
| destroyed_at | datetime? | 用毕销毁时间；销毁后 manifest 仍留存为审计证据 |

规则：Agent 进程**仅可读物化子集**；全量归档与未经授权仓库文件对
Agent 主体 Deny Read（非仅"不列入清单"，见 research 2.2/R3.5）；
物化子集生命周期限单次执行，执行终态后销毁。

### 2.5 GenerationExecution（历史行 + 当前状态投影）

| 字段 | 类型 | 规则 |
|---|---|---|
| id（执行 ID，对外可见）/ task_id / baseline_id / requirement_version_id | | |
| status | enum | running/completed/failed/timeout/cancelled/late_result_discarded（FR-027） |
| cancel_requested / cancel_outcome | | 真实取消结果：cancelled/not_cancelled/already_finished（FR-034） |
| failure_reason | text? | 真实原因 |
| outbound_authorization_id | FK? | |
| usage | json? \| null | `{input_tokens?, output_tokens?, cache_read_tokens?, …}`（P1-05） |
| usage_basis | enum: actual/unavailable | 仅"有无实际返回"两类 |
| cost | json? \| null | `{amount?, currency?, basis: actual\|estimated\|unknown, method?}` |
| started_at / finished_at | | |

**约束**：
- 部分唯一索引：`UNIQUE(task_id) WHERE status='running'`（活跃执行唯一）。
- 终态（completed/failed/timeout/cancelled/late_result_discarded）冻结；
  任何后续事实写 LateResultRecord，**不改写终态行**。
- 方案版本创建条件（事务内）：execution.status=completed ∧ 关联
  VerificationAttempt 最新状态=verified ∧ 仍在有效授权窗内。

### 2.6 VerificationAttempt（每次核验一行，append-only）

| 字段 | 类型 | 规则 |
|---|---|---|
| execution_id | FK | 1:N（非 1:0..1——修订 P0-03） |
| attempt_no | int | 唯一（execution_id, attempt_no） |
| status | enum: verified/unconfirmed/failed | |
| pre_baseline_ref / post_compare_ref | str? | 证据引用 |
| coverage_note | text | 检测范围与未覆盖范围声明（FR-013） |
| isolation_evidence | json | OS ACL/令牌/防火墙 + 拒绝规则配置快照引用 |
| evidence_sufficiency | json | 四类证据齐备判定（R3.4；Q2） |
| created_at | | |

当前核验状态 = **最新 attempt 的投影**；历史 attempts 永不覆盖；
「未确认」只能被证据充分的新 attempt 替代（否则保持未确认/failed，
FR-045）；unconfirmed 不得进入审批（US4-8）。

### 2.7 ProposalVersion（不可变）+ 当前版本选择规则

| 字段 | 类型 | 规则 |
|---|---|---|
| seq | int | 唯一（task_id, seq）；版本链 |
| requirement_version_id / baseline_id / execution_id | FK | 生成要素 |
| content / content_hash | | content_hash=SHA-256；审批绑定要素（FR-028） |

**选择规则（P0-03/P0-D）**：任务"当前方案版本"= max(seq)。审批请求携带
**显式版本号**（防误操作/可审计），但服务端**仅允许批准当前有效方案版本**：
目标版本必须 = 当前版本（max seq），且其 requirement_version_id /
baseline_id 分别匹配任务**当前需求版本**与**当前分析基准**，且其关联
最新 VerificationAttempt.status = verified（三项前置，见 2.8 事务）。
过期/不匹配 → 409 approval_target_stale，不写 approved 事件。
生成新版本与批准并发时由唯一索引与事务前置共同收敛。

### 2.8 Feedback / ApprovalEvent / ApprovalValidity

Feedback：驱动新版本（不变）。

ApprovalEvent（不可变）：五要素字段 + decision(approved/rejected) + reason。

**部分唯一索引（P0-03 明确）**：
```sql
CREATE UNIQUE INDEX ux_approval_once
  ON approval_events(proposal_version_id)
  WHERE decision = 'approved';
```
并发批准：`BEGIN IMMEDIATE` + INSERT；唯一约束冲突方 → 409 + 拒绝审计
（FR-031，SC-005）。同版本驳回后再批准：驳回是独立事件；approved 仍至多一条
（语义如需收紧由任务层状态机约束）。

**批准事务与前置（P0-D）**：approve 写入在单个 `BEGIN IMMEDIATE` 事务内
完成——①复核三项前置（目标=当前方案版本 max seq；需求版本/基准匹配
当前指针；最新 VerificationAttempt=verified）→ ②INSERT ApprovalEvent
→ ③更新任务投影（current_approval）。任一前置不成立 → 事务回滚，
返回 **409 approval_target_stale**（或 verification_not_passed），
**不落任何 approved 事件**，历史意图仅记 AuditLog（防"已批准但立即
无效"的误导性记录）。三项前置 + 事件 + 投影保证判断与写入的事务
一致性。

ApprovalValidity（派生）：五要素 vs 任务当前需求版本/基准/方案版本比对；
不符 → invalid；事件本身不改（FR-029）；Agent 不参与判定（FR-030）。

### 2.9 OutboundAuthorization / SendAuditRecord（P0-02）

OutboundAuthorization：receiver、data_types、send_scope、exclusions_applied、
status(active/revoked)、task_id、baseline_id。**复用五条件**：同任务 ∧
同基准 ∧ 同接收方 ∧ 同实际发送范围 ∧ status=active（FR-015，SC-010）。

SendAuditRecord（append-only）：

| 字段 | 类型 | 规则 |
|---|---|---|
| authorization_id / execution_id | FK | |
| payload_manifest | json | **实际入模内容**记账：需求文本/反馈/源码文件（路径+哈希+数据类型）/工具返回内容摘要（P0-02 覆盖四类；**候选 C 下「工具返回」恒空**） |
| model_request_digest | str | 请求侧内容摘要 |
| result | enum: sent/blocked_refused/blocked_out_of_scope/blocked_egress | 越权/未授权端点阻断在此记录 |
| network_observation_ref | str? | FV-7/S9 网络观测引用（审计⊇入模内容比对） |

### 2.10 LateResultRecord / IdempotencyRecord / SecurityEvent / AuditLog

- **LateResultRecord**：execution_id、arrival_at、摘要、处置（discard）；
  不产生方案版本/核验变更/审批（FR-035）。
- **IdempotencyRecord**（P1-03）：`idempotency_key`（客户端头）、
  `request_digest`、`response_snapshot`、`created_at`、TTL；
  唯一（key）；同键同摘要→重放；同键异摘要→409。
- **SecurityEvent**：绕过门禁/提示注入/越权读写/未授权外发（FR-033/043）。
- **AuditLog**：actor、action、before/after 摘要、timestamp；可选哈希链。

## 3. Git 对象 ID 适配（P1-01）

- commit SHA 字段：`^(?:[0-9a-f]{40}|[0-9a-f]{64})$`，并按记录的
  object_format 精确校验长度（sha1→40，sha256→64）。
- 内容摘要（content_hash、archive_sha256）：固定 SHA-256（64 hex），
  与仓库对象格式无关。
- 五要素"完整 commit SHA"语义不变；spec FR-002 无需修改（兼容两种格式）。

## 4. SQLite 事务与约束汇总（P0-03）

| 机制 | 用途 |
|---|---|
| WAL 模式 | 读写并发；单写者队列（后端进程内串行写，候选） |
| `BEGIN IMMEDIATE` | 状态转移、seq 分配、审批插入、执行激活 |
| compare-and-swap | `UPDATE … WHERE status=:expected` 校验非法转移 |
| 部分唯一索引 | ux_approval_once；ux_active_generation（running 唯一） |
| 事务原子性 | 崩溃后半成品不可见；投影与事件同事务 |

## 5. 校验规则映射（Pydantic）

- 公开 API 输入/响应全部 Pydantic 模型显式校验（宪章原则 V）。
- SHA 字段按 §3 正则；状态枚举与转移表集中 domain 层单点实现。
- usage/cost 为独立可空结构（P1-05）；凭据不进入模型（FR-042）。
