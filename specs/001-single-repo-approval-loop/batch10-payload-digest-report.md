# 批 10 请求体摘要（payload_digest）离线验证报告

**Date**: 2026-10-21
**状态**: **PASS（离线 Fake Transport）**；未进行任何真实网络发送。

## 1. 原有 `content_digest` 的含义（核对结果）

`SendAuditRecord.content_digest` 当前计算的是 **payload_manifest 的 SHA-256**：

```text
manifest = {requirement, feedback, source, tool_return}
content_digest = SHA-256(JSON(manifest, sort_keys=True, ensure_ascii=False))
```

它**不是** HTTP JSON 请求体的摘要，也**不覆盖** `model/max_tokens/thinking/stream`
等请求字段。批 9 核对单已标注该缺口。

## 2. 本批修复

### 2.1 规范化请求体（单一字节序列）

新增 `backend/app/core/payload.py`：

```python
canonical_payload_bytes(payload) = json.dumps(
    payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode("utf-8")

payload_digest(payload) = SHA-256(canonical_payload_bytes(payload))
```

- `outbound_pipeline.prepare()` 的 `request_digest` 改为该摘要；
- `DashscopeAgentAdapter._urllib_transport()` 使用同一 `canonical_payload_bytes`；
- 受限 worker 真实模式：父进程把**同一字节**写入 sandbox `request_body.bin`，
  worker 直接读取该文件发送，不再二次序列化；
- 摘要只覆盖 body，**不包含** `Authorization`/API Key。

### 2.2 审计持久化

- `SendAuditRecord` 新增 `payload_digest`（nullable，兼容历史记录）；
- 迁移 `alembic/versions/0006_payload_digest.py`（`down_revision=0005`）；
- `record_send(..., payload_digest=...)` 写入 `prepared.request_digest`；
- `GET /api/generations/{id}/send-audit` 返回 `payload_digest`；
- 前端 send-audit 展示 `content_digest`（manifest）与 `payload_digest`（请求体）两行。

## 3. 离线测试（Fake Transport，无网络）

`backend/tests/test_payload_digest.py` → **4 passed**：

| 测试 | 验证点 |
|---|---|
| `test_digest_is_stable_and_changes_with_any_field` | 同一 payload 摘要稳定；修改 model / max_tokens / messages 内容 / stream 均改变摘要 |
| `test_urllib_transport_sends_canonical_bytes_without_key` | Fake opener 捕获 `Request.data` == `canonical_payload_bytes`；SHA-256 == `payload_digest`；body 不含 fake Key/Authorization；timeout 传递 |
| `test_worker_real_transport_uses_body_file_bytes` | worker 真实模式读取 `request_body.bin` 原样发送；摘要一致；`sent.marker` 生成；body 无 Key |
| `test_generation_audit_persists_payload_digest` | 生成后 DB 记录 `execution_id`/`authorization_id`/`payload_digest`；`payload_digest != content_digest`；API 返回一致 |

迁移测试：`tests/test_migrations.py` 断言 `send_audit_records.payload_digest` 列存在，
`0001→0006` upgrade/downgrade 通过。

## 4. 可追溯性

审计记录包含：
- `execution_id`（字符串）；
- `authorization_id`；
- `payload_manifest`（四类内容，工具返回空）；
- `content_digest`（manifest 摘要）；
- `payload_digest`（完整 HTTP JSON body 摘要）；
- `created_at`。

因此可追溯：某次执行 → 授权 → manifest 内容 → 实际请求体摘要。  
**限制**：TLS 加密下不提供独立第三方对真实线上请求体的读取；本报告证明
“应用/worker 使用的字节序列与审计摘要一致”，不声称网络中间可见明文。

## 5. 回归

- 后端全量：**162 passed**（新增 4 项；无失败）。
- 前端：`npm test` → 8 passed；`npm run build` → 成功（批 10 变更后复跑）。

## 6. 变更文件

- `backend/app/core/payload.py`（新增）
- `backend/app/services/outbound_pipeline.py`
- `backend/app/agents/dashscope.py`
- `backend/app/isolation/worker_main.py`
- `backend/app/isolation/sandbox.py`
- `backend/app/agents/worker.py`
- `backend/app/models/outbound.py`
- `backend/app/services/outbound.py`
- `backend/app/services/generation_service.py`
- `backend/app/api/generations.py`
- `backend/alembic/versions/0006_payload_digest.py`（新增）
- `backend/tests/test_payload_digest.py`（新增）
- `backend/tests/test_migrations.py`、`tests/test_generation.py`
- `frontend/src/api/index.ts`、`frontend/src/components/GenerationPanel.vue`