# 首次真实百炼调用最终核对单（不实际调用）

**日期**：2026-10-23　**状态**：待人工执行，本文件不发起任何请求、不读 Key。

## 0. 硬门禁（缺一即 STOP）

| # | 门禁 | 当前 |
|---|---|---|
| G1 | 后端全量 pytest 通过 | 本地 272 passed；CI run 39955948177 success |
| G2 | S9 网络边界 = `verified` | **未配置**（`not_configured`），见部署说明 |
| G3 | `real_ai_enabled=true` + `worker_real_transport=true` | 未启用 |
| G4 | `ADLL_WORKER_PRINCIPAL_SID` 指向专用账户 | 未配置 |
| G5 | 预览后 `preview_digest` 与重算一致（两步确认） | 待操作者 |

## 1. 合成数据（禁止真实业务内容）

- 需求：`用 Python 实现按行去重小工具，输出到 stdout。`
- 源码：`synthetic_dedup.py`（显式标注 synthetic）。

## 2. 固定端点与模型（需人工在控制台确认，不凭空更换）

- 端点：`https://dashscope.aliyuncs.com/apps/anthropic/v1/messages`（华北2 北京，
  官方现有域名仍可用；认证 `Authorization: Bearer`）。
- 模型：配置 `ADLL_DASHSCOPE_MODEL`（默认 `qwen3.7-flash-2026-07-15`）。**该带日期
  快照名需在百炼控制台确认仍可用**；若已下线，改由操作者显式指定一个有效模型，
  不得由本清单臆测替换。

## 3. 完整待发送 JSON 与 SHA-256

- 由 preview 接口返回 `request_body.content`（规范化 JSON）+ `request_body.sha256`；
- 人工复制 `request_body.content` 本地 `sha256` 重算，必须等于 `request_digest`；
- `messages[0].content` 与 `message.content` 一致。

## 4. 一次请求、不自动重试、Token 上限

- Worker 单次请求，无重试；禁代理、禁重定向。
- `max_tokens` 固定（payload 内），触发 `max_tokens` 停止不算异常（标记 truncated）。
- `timeout` 明确（默认 30s，worker 进程超时 = timeout+10）。

## 5. 费用上限

- 仅按量/账单对账；`cost.basis=actual` 且金额缺失时不推断不编造。
- 记录 input/output tokens，与服务商账单对账；设置人工费用上限并核对。

## 6. API Key 本地注入与清理

- 仅环境变量 `DASHSCOPE_API_KEY` 注入；**永不进入聊天、日志、DB、evidence**。
- 调用结束立即清除环境变量，确认无 `Authorization` 头 / Key 字面量残留。

## 7. 核对清单（执行后逐项打勾）

- [ ] S9 边界 `verified`（含 `observed_denial` + 覆盖 IPv4/IPv6/回环/代理 + 无 allow 绕过）
- [ ] `SendAuditRecord`：`prepared` + 终态，`request_digest`/`receiver`/`attempt_id` 一致
- [ ] 真实响应 `ok`，`send_evidence` 非 synthetic
- [ ] 核验 `verified` + `sufficient`
- [ ] 生成方案 `ProposalVersion`（seq 递增）

## 8. 四种结果判定

| 结果 | 判定 |
|---|---|
| 成功 | completed + verified + proposal + confirmed_sent |
| 失败 | failed + not_sent / possibly_sent |
| 超时 | timeout + possibly_sent |
| 取消 | 发送前 cancelled/not_sent；发送后 not_cancelled/possibly_sent + discard |
