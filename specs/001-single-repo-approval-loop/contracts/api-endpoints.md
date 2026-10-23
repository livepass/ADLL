# 接口契约（contracts/api-endpoints.md）— R2 修订版（含最终安全边界修订）

**Feature**: ADLL V1.1 | **Date**: 2026-10-17（R2 + 最终安全边界/一致性修订：P0-B/D、P1 细节-3）
**风格**: REST + JSON；全部请求/响应经 Pydantic 校验（宪章原则 V）；
状态机服务端强制（FR-027/033）。契约级定义，非实现代码。

## 通用约定（P1-03 修订）

### 身份与跨站防护（P0-B，全站强制）

- **会话身份**：全部状态变更接口要求已认证用户会话（HttpOnly+Secure
  Cookie 或等价本地会话令牌）；回环地址（127.0.0.1）**不等于**已认证
  ——本地进程身份不因来源地址可信。
- **授权**：审批写入类接口（approve/reject）要求会话 `role=user`；
  Agent/自动化组件**不存在**可调用审批接口的会话身份，主体类别校验
  拒绝非用户会话（401/403 + 安全事件）。
- **CSRF**：状态变更接口要求 CSRF 令牌（双提交或 SameSite=Strict 会话 +
  自定义请求头校验）；Origin/Referer 校验作纵深。**不得仅依靠 CORS、
  Origin 或前端按钮**作为身份验证（S13 验收覆盖）。

- 前缀 `/api`；错误响应 `{code, message, detail?, conflict_object_id?}`。
- **幂等键**：变更类接口（生成/批准/驳回/正式保存需求/更换基准/授权）
  支持 `Idempotency-Key` 头（客户端生成 UUID）：
  - 同键 + 同请求摘要 → **重放原响应**（含原状态码）；
  - 同键 + 异请求摘要 → **409 idempotency_conflict**；
  - 无键重复请求由状态锁/唯一约束兜底（FR-031/038）。
- **重试语义**：仅带幂等键的重试安全；网络错误/5xx 后重试返回原执行；
  4xx 为真实语义结果，不得盲目重试。
- **费用/用量结构（P1-05 独立双维度）**：

```json
{
  "usage": {"input_tokens": 0, "output_tokens": 0, "…": "可选"},
  "usage_basis": "actual | unavailable",
  "cost": {"amount": null, "currency": null,
           "basis": "actual | estimated | unknown", "method": "估算方法说明(仅 estimated)"}
}
```

  usage 与 cost 互不推断；unknown 显示"不可用"不显示金额；
  凭据永不出现（FR-042/050/051）。

## 并发冲突语义表（P0-03/P1-03）

| 场景 | HTTP | code | 效果 |
|---|---|---|---|
| 已存在运行中生成，再次发起 | 202 | （幂等） | 返回既有 execution_id |
| 基准 unavailable 发起生成/审批 | 423 | baseline_unavailable | 阻止（FR-048） |
| 授权五条件不满足/范围扩大 | 403 | outbound_auth_required | 进入重新授权流程 |
| 核验状态非 verified 提交审批 | 409 | verification_not_passed | 拒绝（US4-8） |
| 批准目标非当前有效方案版本（过期版本/需求或基准已变更） | 409 | **approval_target_stale** | 拒绝；**不写 approved 事件**；提示重新审阅当前版本（P0-D） |
| 重复/并发批准（唯一索引落败） | 409 | approval_exists | 返回既有批准记录 + 拒绝审计 |
| 同幂等键异摘要 | 409 | idempotency_conflict | 无副作用 |
| 需求保存并发（seq 分配） | 200/201 | — | `BEGIN IMMEDIATE` 内分配，序号唯一 |
| 非法状态转移 | 409 | invalid_transition | 拒绝并审计（FR-027） |
| 绕过审批门禁（Agent 写审批） | 403 | forbidden | 安全事件（FR-033） |

## 1. 仓库关联

| 方法/路径 | 语义 | 关键约束 |
|---|---|---|
| `POST /api/repositories/link` | 授权关联本地仓库 | 返回 repo_identity、完整 commit SHA、**object_format**（sha1/sha256，P1-01）、工作区状态（FR-001/002/004） |
| `GET /api/repositories/active` | 当前活跃关联 | 含 workspace_status |
| `POST /api/repositories/active/workspace-decision` | 脏工作区处理决定 | 未处理不得建任务（FR-003）；不改工作区文件（FR-006） |

## 2. 任务与需求版本

| 方法/路径 | 语义 | 关键约束 |
|---|---|---|
| `POST /api/tasks` | 创建任务（绑定 baseline） | 幂等键可选；记录完整 SHA + object_format |
| `GET /api/tasks` / `GET /api/tasks/{id}` | 列表/详情 | 历史多条（FR-008）；含 current_proposal_version（max(seq)） |
| `PUT /api/tasks/{id}/requirement` | 正式保存并提交需求修改 | 不可变新需求版本；草稿不产生版本；旧审批失效（FR-007，Q1）；支持幂等键 |
| `POST /api/tasks/{id}/baseline` | 主动更换分析基准 | 新 baseline 记录 + 重新分析；不继承审批（FR-029，Q3）；支持幂等键 |

## 3. 方案生成与执行（P1-03 异步语义）

| 方法/路径 | 语义 | 关键约束 |
|---|---|---|
| `POST /api/tasks/{id}/generations` | 发起生成 | **202 + execution_id**；幂等键强推荐；活跃执行唯一（返回既有）；baseline unavailable→423；授权闸门校验（L1 复用五条件） |
| `GET /api/generations/{id}` | 执行详情（轮询兜底） | 真实状态、失败/取消原因、usage/cost 双维度、核验状态、证据引用 |
| `GET /api/generations/{id}/events` | **SSE 流式进度** | 进度/文本流事件；**仅连接存续期内实时增量**——V1.1 不持久化事件、不支持 Last-Event-ID 断线续传（细节-3）；断线后客户端改用 `GET /api/generations/{id}` 轮询补偿 |
| `POST /api/generations/{id}/cancel` | 请求取消 | 真实取消结果 cancelled/not_cancelled/already_finished（FR-034）；幂等 |
| `GET /api/generations/{id}/evidence` | 完整性证据 | 前后比对、覆盖/未覆盖声明、隔离证据、归档哈希复核（FR-013/045） |
| `GET /api/generations/{id}/send-audit` | 出站审计 | payload_manifest 四类内容（需求/反馈/源码/工具返回）、授权引用、阻断结果（P0-02） |

> **2026-10-20 适配（候选 C）**：候选 C 无工具 → `payload_manifest` 四类中「工具返回」**恒空**（字段保留）；
> 出站授权默认 receiver=阿里云百炼（北京地域，`dashscope.aliyuncs.com/apps/anthropic`）。

## 4. 方案版本、意见与审批

| 方法/路径 | 语义 | 关键约束 |
|---|---|---|
| `GET /api/tasks/{id}/proposals` | 版本链 | 差异摘要、状态；标注当前版本（max seq） |
| `POST /api/tasks/{id}/proposals/{v}/feedback` | 提交意见并触发新版本 | 显式版本号 `{v}`；新版本不继承审批（FR-025/029）；支持幂等键 |
| `POST /api/tasks/{id}/proposals/{v}/approve` | 人工批准 | **显式版本号**（不隐式绑定"当前"）；服务端同事务复核三项前置（{v}=当前方案版本、需求版本/基准匹配当前指针、最新核验=verified）后才写 approved 事件——过期/不匹配→**409 approval_target_stale** 且不落事件（P0-D）；五要素绑定、唯一批准；幂等键 + 唯一索引双保险；**会话 role=user + CSRF 必需**，Agent/非会话主体→401/403+安全事件（FR-028/031/033，P0-B） |
| `POST /api/tasks/{id}/proposals/{v}/reject` | 人工驳回 | 理由记录；任务回可迭代（FR-032）；支持幂等键；**会话 role=user + CSRF 必需**（P0-B） |
| `GET /api/tasks/{id}/approvals` | 审批事件与有效性 | 历史不可变 + 有效性独立判定（FR-028/029） |

## 5. 出站授权

| 方法/路径 | 语义 | 关键约束 |
|---|---|---|
| `GET /api/tasks/{id}/outbound-authorizations` | 授权列表 | 范围、接收方、状态、复用资格（五条件当前值） |
| `POST /api/tasks/{id}/outbound-authorizations` | 明确确认授权 | receiver/data_types/send_scope；返回排除规则命中摘要；幂等键 |
| `POST /api/outbound-authorizations/{id}/revoke` | 撤销 | 之后发送 0（SC-010）；幂等 |
| （内部）发送闸门 | L1→L4 校验 | 越权/换接收方/范围扩大→403 重新确认；取消/拒绝→不发送+受阻原因 |

## 6. 前端 UI 契约（要点）

- 全流程网页（SC-001）；三状态分栏（执行/核验/审批，FR-046）。
- usage（Token 实际用量/不可用）与 cost（实际/估算/未知）**分栏展示**
 （P1-05）；未知不显示金额。
- 授权确认展示接收方、数据类型、范围、默认排除、**拟发送内容预览**
 （含需求文本与反馈，P0-02）。
- SSE 进度 + 取消按钮（真实结果反馈）。
