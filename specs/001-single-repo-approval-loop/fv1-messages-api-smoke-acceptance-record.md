# FV-1（候选 C）—— Messages API Smoke Test 人工验收记录（fv1-messages-api-smoke-acceptance-record.md）

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**Date**: 2026-10-19
**性质**: 人工验收记录（转录用户证言；原始日志为用户侧产物，未落盘本仓库，
**本记录不含 API Key**）。

## 1. 验收结论

**Messages API 真实连通性 Smoke Test = PASS。**

- 服务商：阿里云百炼，北京地域
- 协议：Anthropic 兼容 Messages API
- 模型：`qwen3.7-flash-2026-07-15`
- `stop_reason`：`end_turn`
- `input_tokens`：**22**
- `output_tokens`：**6**
- Python 退出码：**0**
- `request_id`：已由服务端实际返回（**值未转录到本记录**，留存于用户侧原始日志）

**验收边界（用户明确，不得外推）**：该 PASS **不代表** ADLL AgentAdapter 集成、
OS 权限隔离、真实代码分析或人工审批闭环已通过。实际费用尚需**控制台账单确认**，
**不得编造金额**。

## 2. 实际参数（本次固定配置）

| 项 | 值 |
|---|---|
| Provider / 端点 | 阿里云百炼 `https://dashscope.aliyuncs.com/apps/anthropic/v1/messages`（北京地域） |
| 模型 | `qwen3.7-flash-2026-07-15` |
| `max_tokens` | 256 |
| `thinking` | `{"type": "disabled"}` |
| `stream` | false |
| `timeout` | 30 s |
| `max_retries` | 0 |
| 工具 | 未配置（零工具） |
| 提示词 | `请只输出：ADLL_SMOKE_OK`（唯一 user 消息） |

## 3. 观测结果与凭据纪律

| 项 | 记录 |
|---|---|
| `stop_reason` | `end_turn` |
| `usage` | `input_tokens=22`、`output_tokens=6` |
| 退出码 | 0 |
| `request_id` | **由服务端返回（已获得，值未转录）** |
| **API Key** | **未记录**（本仓库任何文件均不含 `DASHSCOPE_API_KEY` 明文） |
| 临时 Key 环境变量 | 用户执行日志显示**已清理** |

## 4. 与 Claude Agent SDK FV-1 阶段 3 的区分（不得混同）

| 测试 | 状态 |
|---|---|
| **本记录（候选 C：Messages API Smoke，阿里云百炼）** | **PASS（2026-10-19，人工验收）** |
| 原 Claude Agent SDK FV-1 **阶段 3**（SDK 真实调用测试） | **暂停、未经执行**（因候选技术路线调整；见 [fv1-messages-api-smoke-plan.md](./fv1-messages-api-smoke-plan.md) §1 状态登记） |

两者为**不同**测试，结果不互相代表。

## 5. 明确不构成 / 后续

- 本记录**不**构成：AgentAdapter 集成通过、OS 权限隔离通过、真实代码分析通过、
  人工审批闭环通过。
- **不再重复调用 API、不再开展相同 SDK 安装或接口连通性测试**（用户指令）。
- 费用以**控制台账单**为准（实际账单/估算/未知三分，FR-051），**不编造**。
- 原始日志与临时 Key 均由用户侧保存/清理；本仓库仅存此转录记录。