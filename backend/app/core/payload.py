"""请求体规范化与摘要：必须是 HTTP transport 实际发送的同一字节序列。

- UTF-8、键排序、紧凑分隔符；不包含任何 Authorization 头/凭据。
- `payload_digest` 与 `SendAuditRecord.content_digest`（manifest 摘要）分开记录。
"""
from __future__ import annotations

import hashlib
import json


def canonical_payload_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def payload_digest(payload: dict) -> str:
    return hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()