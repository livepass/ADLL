"""出站授权评估与发送审计（T011 修正：任务/基准/接收方/范围/active 五项同时满足）。

- 未批准 / 已撤销 / 过期 → 拒绝（active 条件）。
- task_id / baseline_id 必须与请求一致（不得以数据类型或有效期替代任务/基准检查）。
- 接收方、数据类型、发送范围匹配；关键字段缺失（无法核验）→ 拒绝。
- 审计记录仅在有效授权 + 绑定匹配下写入；四类 manifest，候选 C 下工具返回恒空。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from ..models.base import utcnow
from ..models.enums import OutboundStatus
from ..models.outbound import OutboundAuthorization, SendAuditRecord


@dataclass(frozen=True)
class Decision:
    allowed: bool
    code: str


def _active(auth: OutboundAuthorization | None, now: datetime) -> Decision | None:
    if auth is None:
        return Decision(False, "no_authorization")
    if auth.status != OutboundStatus.APPROVED.value:
        return Decision(False, "not_approved")
    if auth.revoked_at is not None:
        return Decision(False, "revoked")
    if auth.expires_at is not None and auth.expires_at <= now:
        return Decision(False, "expired")
    return None


def evaluate(
    auth: OutboundAuthorization | None,
    *,
    task_id: int | None,
    baseline_id: int | None,
    receiver: str,
    data_types: list[str],
    scope: dict,
    now: datetime | None = None,
) -> Decision:
    now = now or utcnow()
    inactive = _active(auth, now)
    if inactive is not None:
        return inactive
    assert auth is not None
    if auth.task_id is None or auth.baseline_id is None:
        return Decision(False, "unverifiable")
    if auth.task_id != task_id:
        return Decision(False, "task_mismatch")
    if auth.baseline_id != baseline_id:
        return Decision(False, "baseline_mismatch")
    if not auth.receiver or auth.data_types is None or auth.send_scope is None:
        return Decision(False, "unverifiable")
    if auth.receiver != receiver:
        return Decision(False, "receiver_mismatch")
    if not set(data_types or []).issubset(set(auth.data_types or [])):
        return Decision(False, "data_type_not_authorized")
    if (auth.send_scope or {}) != (scope or {}):
        return Decision(False, "scope_mismatch")
    return Decision(True, "ok")


def record_send(
    db,
    auth: OutboundAuthorization,
    *,
    task_id: int | None,
    baseline_id: int | None,
    execution_id: str | None,
    requirement: list | None,
    feedback: list | None,
    source: list | None,
    payload_digest: str | None = None,
) -> SendAuditRecord:
    if auth is None:
        raise PermissionError("outbound authorization missing")
    inactive = _active(auth, utcnow())
    if inactive is not None:
        raise PermissionError(f"outbound authorization invalid: {inactive.code}")
    if (
        auth.task_id is None
        or auth.baseline_id is None
        or auth.task_id != task_id
        or auth.baseline_id != baseline_id
    ):
        raise PermissionError("outbound authorization binding mismatch")
    manifest = {
        "requirement": requirement or [],
        "feedback": feedback or [],
        "source": source or [],
        "tool_return": [],
    }
    digest = hashlib.sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    rec = SendAuditRecord(
        authorization_id=auth.id,
        execution_id=execution_id,
        payload_manifest=manifest,
        content_digest=digest,
        payload_digest=payload_digest,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec