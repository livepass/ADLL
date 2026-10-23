# 首次真实 AI 调用——一次性核对单（不实际调用）

本单用于将来**由人工在真实环境执行一次且仅一次**百炼调用前的逐项确认。
这里只生成核对单与合成数据，**不发起任何真实请求、不读取 API Key**。

## 0. 触发前必须满足的硬门禁（缺一即 STOP）

| # | 门禁 | 现状 |
|---|---|---|
| G1 | 后端全量 pytest 通过 | 见本轮 §1/§5 |
| G2 | S9 网络边界 = `verified` | 本轮为 `not_configured`，**未通过** |
| G3 | `real_ai_enabled=true` 且 `testing=false` | 未启用 |
| G4 | 出站授权 APPROVED 且未撤销 | 由操作者创建 |
| G5 | 预览后 `preview_digest` 与重算一致 | 前端两步确认 |

## 1. 合成需求与合成源码（示例）

- 合成需求：`用 Python 实现一个按行去重的小工具，输出到 stdout。`
- 合成源码 `synthetic_dedup.py`（内容随意、明确标注 synthetic，不涉及真实业务）。

## 2. 完整待发送 JSON（将由 preview 接口给出，人工复核）

核对要点：
- `request_body.content` 是规范化 JSON（键排序、紧凑分隔符、UTF-8）；
- `request_body.sha256` 必须等于 `request_digest`；
- `messages[0].content` 必须等于 `message.content`；
- 复制 `request_body.content` 到本地 `sha256` 工具重算，与 `request_digest` 一致。

## 3. 关键参数确认

| 项 | 期望 |
|---|---|
| 接收端点 | `https://dashscope.aliyuncs.com/apps/anthropic/v1/messages`（仅此一个允许） |
| 模型 | 配置 `dashscope_model` |
| 单次请求 | 是；worker 无自动重试 |
| Token 上限 | `max_tokens` 固定（payload 中），触发 `max_tokens` 停止不算异常 |
| 禁代理/禁重定向 | worker `_opener()` 已强制 |

## 4. Key 本地注入与清理

- 只经环境变量 `DASHSCOPE_API_KEY` 注入；不在代码/日志/DB 落盘。
- 调用结束立即 `unset`/移除；确认 `SendAuditRecord`、日志、evidence 中无 `Authorization` 头或 Key 字面量。

## 5. 费用核对

- 依赖服务商返回的 usage/账单；`cost.basis=actual` 且金额缺失时不推断、不编造。
- 记录 input/output tokens 与服务商账单对账。

## 6. S9 网络观测与 SendAuditRecord 对账

- 观测：Worker 进程对非授权目的地的出站被 OS 阻断（`observed_denial=true`）；
- 对账：`SendAuditRecord` 终态、`request_digest`、`receiver`、`attempt_id` 与
  实际请求字节一致（worker 发送前 `body_digest_error` 已复核）。

## 7. 四种结果的判定

| 结果 | 判定 |
|---|---|
| 成功 | `status=completed` + 核验 `verified` + 方案 + 审计 `confirmed_sent` |
| 失败 | `status=failed` + 审计 `not_sent`（发送前）或 `possibly_sent`（未知） |
| 超时 | `status=timeout` + 审计 `possibly_sent` |
| 取消 | 发送前 `cancelled/not_sent`；发送后 `not_cancelled/possibly_sent` + LateResult discard |

## 8. 明确不做的

- 不自动重试、不自动放宽门禁、不因失败而把 `possibly_sent` 改成 `confirmed_sent`。
