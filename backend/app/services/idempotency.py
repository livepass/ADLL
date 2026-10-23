"""幂等执行（持久化 + 并发安全）。

语义（contracts/api-endpoints.md 通用约定）：
- 同键 + 同请求摘要 + 已完成 → 重放原状态码/响应（`replayed=True`）；
- 同键 + 异请求摘要 → 409 `idempotency_conflict`；
- 同键 + 同摘要但仍在处理中 → 409 `idempotency_in_progress`（不重复执行）；
- 无键 → 直接执行。
记录持久化于数据库，重启后仍可重放。
"""
from __future__ import annotations

import hashlib
import json
from typing import Callable

from sqlalchemy.exc import IntegrityError

from ..models.base import utcnow
from ..models.enums import IdempotencyState
from ..models.idempotency import IdempotencyRecord


def fingerprint(scope: str, payload: bytes) -> str:
    return hashlib.sha256(scope.encode("utf-8") + b"|" + payload).hexdigest()


def execute(
    db,
    key: str | None,
    scope: str,
    payload: bytes,
    handler: Callable[[], tuple[int, dict]],
) -> tuple[int, dict, bool]:
    if not key:
        status, body = handler()
        return status, body, False

    request_hash = fingerprint(scope, payload)
    record = IdempotencyRecord(
        key=key, request_hash=request_hash, state=IdempotencyState.PENDING.value
    )
    db.add(record)
    try:
        db.commit()  # 唯一键抢占（并发下仅一个成功）
    except IntegrityError:
        db.rollback()
        existing = db.query(IdempotencyRecord).filter_by(key=key).one()
        if existing.request_hash != request_hash:
            return 409, {"code": "idempotency_conflict", "message": "同键不同请求"}, False
        if existing.state == IdempotencyState.COMPLETED.value:
            body = json.loads(existing.response_json or "{}")
            return existing.status_code or 200, body, True
        return 409, {"code": "idempotency_in_progress", "message": "同键请求处理中"}, False

    try:
        status, body = handler()
    except Exception:
        # 释放占位，避免半成品阻塞后续重试
        db.delete(record)
        db.commit()
        raise

    record.state = IdempotencyState.COMPLETED.value
    record.status_code = status
    record.response_json = json.dumps(body, ensure_ascii=False, sort_keys=True)
    record.completed_at = utcnow()
    db.commit()
    return status, body, False