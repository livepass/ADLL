# 首次真实百炼端到端调用最终核对单（未授权执行）

**Date**: 2026-10-21
**状态**: **NOT AUTHORIZED / NOT RUN**。本文件仅为一次性授权前的核对单，
**不得复用**此前 Messages API Smoke Test 的授权；Smoke Test 只证明连通性，
不覆盖 ADLL 集成、隔离、出站审计或费用。

## 1. 固定配置（与 Accepted ADR-C4 一致）

| 项 | 值 |
|---|---|
| 提供方 | 阿里云百炼（Model Studio），北京地域 |
| Endpoint | `https://dashscope.aliyuncs.com/apps/anthropic/v1/messages` |
| Model | `qwen3.7-flash-2026-07-15` |
| 请求 | 单次 `POST`；`max_tokens=256`；`thinking={"type":"disabled"}`；`stream=false`；`max_retries=0`；`timeout=30s` |
| 工具 | 无（候选 C 不持有工具；`tool_return` 恒空） |
| 调用次数上限 | **1 次**（失败也不得自动重试；是否允许第二次须重新授权） |

## 2. 待发送 JSON 的人工确认

1. 在隔离测试模式（Mock）下，用**合成仓库/合成需求**走完
   `outbound_pipeline.prepare`，把 `prepared.payload` 以 UTF-8、键排序的规范 JSON
   写入临时审阅文件（不发送）。
2. 输出：
   - 完整 JSON 文本（逐字审阅）；
   - `payload_sha256 = SHA-256(canonical_json)`；
   - `SendAuditRecord.payload_manifest` 四类：需求、反馈、源码（path+sha256）、
     工具返回（空）。
3. 人工逐字确认：来源文件、需求文本、反馈、模型、`max_tokens`、无额外字段。
4. 执行时，仅在**当前 payload 哈希仍等于已签署哈希**时才允许发送；任何差异 →
   停止，不发送。
   - 批 10 已实现 `SendAuditRecord.payload_digest`（迁移 0006）：它是完整 HTTP JSON
     body 的 SHA-256；`content_digest` 仍是 manifest 摘要，两者分别记录。
   - 首次调用仍须用 harness 记录实际发送前字节的 SHA-256，并与已签署的 payload 哈希
     和审计 `payload_digest` 三方比对。

## 3. 临时测试 Key 的安全注入

- 仅在执行前由用户把**临时** `DASHSCOPE_API_KEY` 注入一个专用进程环境；
  **不写入**项目文件、`.env`、数据库、日志、命令历史、截图或提交。
- 不使用长期主 Key；调用后立即在百炼控制台禁用/删除临时 Key。
- 记录 Key 的**指纹**（如 SHA-256 前 12 位）用于证据，不记录 Key 本身。
- worker 环境块只含该 Key 与最小系统变量；backend/协议/审计输出不得出现 Key。

## 4. 费用、额度与账单

- 执行前由用户重新核实当前百炼免费额度/计费规则（版本敏感，不沿用旧结论）。
- 本核对单**不设金额硬上限**：`max_tokens` 只能限制单次输出，不能保证账单金额。
- 调用后以控制台账单/用量为准；响应 `usage` 不是账单金额。无法取得账单时
  `cost.basis=unknown`、不显示金额。
- 记录 `request_id`、`input_tokens`、`output_tokens`、时间、模型、endpoint。
- 若免费额度已变化或账单不可核对 → 停止，不进行第二次调用。

## 5. S9 网络观测与审计证据

执行前确认以下观测同时就绪（均为一次性、最小化）：

1. **OS 出站边界**：按批 9 方案 B/C 已批准并生效；只允许 provider 端点/本地
   allowlist 代理；非授权目标（例如 `203.0.113.1:443` TEST-NET）被拒绝。
2. **网络观测**：
   - 允许：本地 allowlist 代理的 CONNECT 主机/端口日志；
   - 或：Windows `pktmon` 仅记录五元组/时间/字节数（不抓取 TLS 载荷）；
   - 记录实际目的 IP/域名、端口、时间，与唯一一次调用对齐。
3. **请求内容核对**：
   - 已签署 payload 哈希 == 执行时 payload 哈希；
   - `SendAuditRecord.payload_manifest` 的需求/反馈/源码哈希 ⊇ 实际入模内容；
   - `tool_return` 为空；
   - 响应 `request_id`/usage 与调用记录一致。
4. **限制**：TLS 加密下无法由网络观测独立读取正文；不得声称“已解密核对”。
   残余风险（worker 伪造哈希）通过受限进程/代码审计与本核对单降低，不作为
   密码学证明。

## 6. 失败停止与清理

出现任一情况立即停止（不重试）：

- provider 非 200、重定向、TLS/证书异常、超时、`stop_reason != end_turn`、
  `max_tokens` 截断、响应超大/非 JSON；
- payload 哈希与已签署不一致、审计 manifest 不匹配、发送范围/授权五项不成立；
- 目标 IP/域名不是唯一授权端点、代理记录出现额外目的地；
- Key 出现在日志/输出/数据库/截图；
- 额度/费用不可核对或超出用户授权。

停止动作：
1. 终止 worker Job（kill-on-close）；
2. 不保存/不展示响应正文（除必要审计摘要）；
3. 保留请求摘要、payload 哈希、manifest、destination 观测、错误类型；
4. 立即禁用/删除临时 Key；
5. 记录事故与未覆盖范围，等待人工决定是否重试（需重新授权）。

## 7. 一次性授权签署项（待用户填写）

- [ ] 授权编号/日期：
- [ ] 允许调用次数：1
- [ ] 接收方/模型/endpoint（逐字确认）：
- [ ] 已审阅 payload 的 SHA-256：
- [ ] 临时 Key 指纹（非 Key 本身）：
- [ ] 额度/费用核对结果：
- [ ] 网络观测方式（代理日志 / pktmon）：
- [ ] 失败停止/清理负责人：

**未完成以上签署前，不得设置 `ADLL_REAL_AI_ENABLED=1`、
`ADLL_WORKER_REAL_TRANSPORT=1`，不得读取 `DASHSCOPE_API_KEY`。**