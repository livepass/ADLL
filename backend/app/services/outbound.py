"""出站授权评估与发送审计（T011 修正：任务/基准/接收方/范围/active 五项同时满足）。

- 未批准 / 已撤销 / 过期 → 拒绝（active 条件）。
- task_id / baseline_id 必须与请求一致（不得以数据类型或有效期替代任务/基准检查）。
- 接收方必须等于**实际端点**（由适配器在发送时提供），不接受授权记录自证。
- `send_scope` 必须是显式路径白名单；空 scope 不再表示“全部源码”。
- 实际数据类型由最终请求计算后传入；未在授权中的类型 → 拒绝。
- 审计按尝试记录：`prepared` 在发送前落库，之后追加
  `confirmed_sent` / `possibly_sent` / `not_sent`，不更新既有行。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from ..models.base import utcnow
from ..models.enums import OutboundStatus
from ..models.outbound import SEND_PHASES, OutboundAuthorization, SendAuditRecord

ALLOWED_DATA_TYPES = ("requirement", "feedback", "source", "tool_return")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    code: str


def _active(auth: OutboundAuthorization | None, now: datetime) -> Decision | None:
    if auth is None:
        return Decision(False, "no_authorization")
    # 先判撤销：撤销同时会改 status 与 revoked_at，取更精确的原因。
    if auth.revoked_at is not None:
        return Decision(False, "revoked")
    if auth.status != OutboundStatus.APPROVED.value:
        return Decision(False, "not_approved")
    if auth.expires_at is not None and auth.expires_at <= now:
        return Decision(False, "expired")
    return None


def inactive_reason(
    auth: OutboundAuthorization | None, now: datetime | None = None
) -> str | None:
    """Return the reason an authorization cannot be used right now, else None.

    Used for the last check immediately before a send, because an authorization
    may be revoked between request preparation and the actual network call.
    """
    decision = _active(auth, now or utcnow())
    return decision.code if decision is not None else None


def scope_paths(value: object) -> list[str] | None:
    """Normalize `{"paths": [...]}`; return None when the shape is invalid.

    Relative, non-escaping paths only. `[]` is valid but authorizes nothing.
    """
    if not isinstance(value, dict):
        return None
    # 缺少 paths 键视为空白名单（而不是“全部源码”）；类型不对才算无法核验。
    paths = value.get("paths", [])
    if not isinstance(paths, list):
        return None
    normalized: list[str] = []
    for item in paths:
        if not isinstance(item, str) or not item.strip():
            return None
        name = item.strip().replace("\\", "/")
        if name.startswith("/") or name.startswith("../") or "/../" in name or name == "..":
            return None
        if ":" in name.split("/")[0]:
            return None
        normalized.append(name)
    return sorted(set(normalized))


def valid_receiver(receiver: object) -> bool:
    """A confirmed receiver must be an absolute endpoint, not a bare label."""
    if not isinstance(receiver, str) or not receiver.strip():
        return False
    return "://" in receiver and len(receiver) <= 200


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
    if not valid_receiver(receiver):
        return Decision(False, "receiver_unverifiable")
    if auth.receiver != receiver:
        return Decision(False, "receiver_mismatch")

    authorized_paths = scope_paths(auth.send_scope)
    if authorized_paths is None:
        return Decision(False, "unverifiable")
    if not authorized_paths:
        return Decision(False, "scope_required")

    requested_types = [t for t in (data_types or []) if t]
    if not requested_types:
        return Decision(False, "data_type_required")
    if not set(requested_types).issubset(set(auth.data_types or [])):
        return Decision(False, "data_type_not_authorized")

    actual_paths = scope_paths(scope)
    if actual_paths is None:
        return Decision(False, "scope_unverifiable")
    if not set(actual_paths).issubset(set(authorized_paths)):
        return Decision(False, "scope_mismatch")
    if "source" in requested_types and not actual_paths:
        return Decision(False, "source_scope_required")
    if "source" not in requested_types and actual_paths:
        return Decision(False, "scope_mismatch")
    return Decision(True, "ok")


def manifest_digest(manifest: dict) -> str:
    return hashlib.sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _assert_binding(auth: OutboundAuthorization, *, task_id, baseline_id, receiver) -> None:
    if auth is None:
        raise PermissionError("outbound authorization missing")
    inactive = _active(auth, utcnow())
    if inactive is not None:
        raise PermissionError(f"outbound authorization invalid: {inactive.code}")
    if auth.task_id is None or auth.baseline_id is None:
        raise PermissionError("outbound authorization binding unverifiable")
    if auth.task_id != task_id or auth.baseline_id != baseline_id:
        raise PermissionError("outbound authorization binding mismatch")
    if auth.receiver != receiver:
        raise PermissionError("outbound authorization receiver mismatch")


def begin_attempt(
    db,
    auth: OutboundAuthorization,
    *,
    task_id: int | None,
    baseline_id: int | None,
    execution_id: str | None,
    receiver: str,
    manifest: dict,
    request_digest: str,
    payload_digest: str | None = None,
) -> str:
    """Persist the request summary **before** any network call. Append-only."""
    _assert_binding(auth, task_id=task_id, baseline_id=baseline_id, receiver=receiver)
    attempt_id = uuid.uuid4().hex
    record = SendAuditRecord(
        authorization_id=auth.id,
        execution_id=execution_id,
        attempt_id=attempt_id,
        phase="prepared",
        receiver=receiver,
        payload_manifest=manifest,
        content_digest=manifest_digest(manifest),
        payload_digest=payload_digest,
        request_digest=request_digest,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return attempt_id


def finish_attempt(
    db,
    attempt_id: str,
    *,
    phase: str,
    error_code: str | None = None,
) -> SendAuditRecord:
    """Append a terminal phase for an attempt; never mutate the prepared row."""
    if phase not in SEND_PHASES or phase == "prepared":
        raise ValueError(f"invalid send phase: {phase}")
    prepared = (
        db.query(SendAuditRecord)
        .filter_by(attempt_id=attempt_id, phase="prepared")
        .one_or_none()
    )
    if prepared is None:
        raise PermissionError("send attempt not prepared")
    if (
        db.query(SendAuditRecord)
        .filter(SendAuditRecord.attempt_id == attempt_id, SendAuditRecord.phase != "prepared")
        .count()
    ):
        raise PermissionError("send attempt already finalized")
    record = SendAuditRecord(
        authorization_id=prepared.authorization_id,
        execution_id=prepared.execution_id,
        attempt_id=attempt_id,
        phase=phase,
        receiver=prepared.receiver,
        payload_manifest=prepared.payload_manifest,
        content_digest=prepared.content_digest,
        payload_digest=prepared.payload_digest,
        request_digest=prepared.request_digest,
        error_code=error_code,
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        # 并发终结：另一个写入者已先落终态，唯一索引拒绝第二个。
        db.rollback()
        raise PermissionError("send attempt already finalized") from None
    db.refresh(record)
    return record


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
    """Compatibility wrapper: prepare + confirm in one call (confirmed send)."""
    manifest = {
        "requirement": requirement or [],
        "feedback": feedback or [],
        "source": source or [],
        "tool_return": [],
    }
    attempt_id = begin_attempt(
        db,
        auth,
        task_id=task_id,
        baseline_id=baseline_id,
        execution_id=execution_id,
        receiver=auth.receiver,
        manifest=manifest,
        request_digest=payload_digest or manifest_digest(manifest),
        payload_digest=payload_digest,
    )
    return finish_attempt(db, attempt_id, phase="confirmed_sent")
