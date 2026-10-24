"""S9-2 收据：宿主授权收据与出口发送收据的离线数据结构、验签与防重放。

本模块只承载离线可验证逻辑：数据规范化、签名/验签、字段比对、防重放判定、
迟到证据追加。**不含**任何真实网络/密钥读取/VM 依赖。

签名采用 HMAC-SHA256（共享密钥）作为离线阶段的「签名」实现占位；生产若改用
非对称签名（Ed25519 等），只需替换 `sign`/`verify` 内部实现，字段契约不变。
密钥一律由调用方注入，绝不硬编码、不落日志、不进仓库。

关键不变量：
- 出口收据的 `actual_body_sha256` 是出口对**实际转发字节**重算的摘要，禁止回显
  调用方填写的 `request_digest`；宿主验签后必须比对
  `actual_body_sha256 == prepared.request_digest`。
- 迟到收据（attempt 已有终态）只追加 `SendReceiptEvidence`，绝不写第二条终态。
- 过期收据不能成为新发送授权；审计保留与信任判定分离。
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..models.base import utcnow
from ..models.outbound import SendAuditRecord, SendReceiptEvidence

# 出口收据签名覆盖的字段（固定顺序规范化）：任一缺失即签名不符。
SEND_RECEIPT_SIGNED_FIELDS = (
    "attempt_id",
    "authorization_id",
    "receiver",
    "request_digest",
    "actual_body_sha256",
    "terminal_phase",
    "http_status",
    "raw_response_sha256",
    "policy_version",
    "issuer",
    "key_id",
    "issued_at",
    "expires_at",
)

# 宿主授权收据签名覆盖字段（供 Launcher 验签确认 prepared 绑定）。
HOST_RECEIPT_SIGNED_FIELDS = (
    "attempt_id",
    "authorization_id",
    "receiver",
    "request_digest",
    "authorization_status",
    "policy_version",
    "key_id",
    "issued_at",
    "expires_at",
)


def _canonical(obj: dict[str, Any]) -> bytes:
    """与 core.payload.canonical_payload_bytes 同源的规范化字节串。"""
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _signed_payload(fields: tuple[str, ...], values: dict[str, Any]) -> dict[str, Any]:
    return {k: values.get(k) for k in fields if k in values}


def sign(fields: tuple[str, ...], values: dict[str, Any], key: bytes) -> str:
    """HMAC-SHA256 签名（覆盖 fields 列出的字段，规范化后）。"""
    payload = _canonical(_signed_payload(fields, values))
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def verify(fields: tuple[str, ...], values: dict[str, Any], key: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign(fields, values, key), signature)


def _now_iso() -> str:
    return utcnow().isoformat()


def _expired(expires_at: str | None, now: datetime) -> bool:
    if not expires_at:
        return True
    try:
        parsed = datetime.fromisoformat(expires_at)
    except ValueError:
        return True
    # 统一为 naive UTC 比较：utcnow() 返回 naive UTC，避免 aware/naive 混比。
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    if now.tzinfo is not None:
        now = now.astimezone(UTC).replace(tzinfo=None)
    return parsed <= now


@dataclass(frozen=True)
class HostAuthorizationReceipt:
    """宿主签发，供 Launcher 验签确认 prepared 行绑定（§2.1）。"""

    attempt_id: str
    authorization_id: int
    receiver: str
    request_digest: str
    authorization_status: str  # "approved"
    policy_version: str
    key_id: str
    issued_at: str
    expires_at: str
    signature: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "authorization_id": self.authorization_id,
            "receiver": self.receiver,
            "request_digest": self.request_digest,
            "authorization_status": self.authorization_status,
            "policy_version": self.policy_version,
            "key_id": self.key_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "signature": self.signature,
        }


@dataclass(frozen=True)
class SendReceipt:
    """Egress 签发，供宿主验签后落唯一终态（§5.1）。"""

    attempt_id: str
    authorization_id: int
    receiver: str
    request_digest: str
    actual_body_sha256: str
    terminal_phase: str  # confirmed_sent | possibly_sent | not_sent
    http_status: int | None
    raw_response_sha256: str | None
    policy_version: str
    issuer: str  # "egress"
    key_id: str
    issued_at: str
    expires_at: str
    signature: str
    provider_request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "authorization_id": self.authorization_id,
            "receiver": self.receiver,
            "request_digest": self.request_digest,
            "actual_body_sha256": self.actual_body_sha256,
            "terminal_phase": self.terminal_phase,
            "http_status": self.http_status,
            "raw_response_sha256": self.raw_response_sha256,
            "policy_version": self.policy_version,
            "issuer": self.issuer,
            "key_id": self.key_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "signature": self.signature,
            "provider_request_id": self.provider_request_id,
        }


def issue_host_receipt(
    *,
    attempt_id: str,
    authorization_id: int,
    receiver: str,
    request_digest: str,
    policy_version: str,
    key_id: str,
    key: bytes,
    ttl_seconds: int = 300,
) -> HostAuthorizationReceipt:
    """签发宿主授权收据（§2.1）：签名覆盖 prepared 绑定字段。"""
    issued = _now_iso()
    expires = _expires_after(issued, ttl_seconds)
    values = {
        "attempt_id": attempt_id,
        "authorization_id": authorization_id,
        "receiver": receiver,
        "request_digest": request_digest,
        "authorization_status": "approved",
        "policy_version": policy_version,
        "key_id": key_id,
        "issued_at": issued,
        "expires_at": expires,
    }
    signature = sign(HOST_RECEIPT_SIGNED_FIELDS, values, key)
    return HostAuthorizationReceipt(
        attempt_id=attempt_id,
        authorization_id=authorization_id,
        receiver=receiver,
        request_digest=request_digest,
        authorization_status="approved",
        policy_version=policy_version,
        key_id=key_id,
        issued_at=issued,
        expires_at=expires,
        signature=signature,
    )


def issue_send_receipt(
    *,
    attempt_id: str,
    authorization_id: int,
    receiver: str,
    request_digest: str,
    actual_body_sha256: str,
    terminal_phase: str,
    http_status: int | None,
    raw_response_sha256: str | None,
    policy_version: str,
    key_id: str,
    key: bytes,
    provider_request_id: str | None = None,
    ttl_seconds: int = 300,
) -> SendReceipt:
    """签发出口收据：签名覆盖所有影响发送事实的字段（§5.1）。"""
    issued = _now_iso()
    expires = _expires_after(issued, ttl_seconds)
    values = {
        "attempt_id": attempt_id,
        "authorization_id": authorization_id,
        "receiver": receiver,
        "request_digest": request_digest,
        "actual_body_sha256": actual_body_sha256,
        "terminal_phase": terminal_phase,
        "http_status": http_status,
        "raw_response_sha256": raw_response_sha256,
        "policy_version": policy_version,
        "issuer": "egress",
        "key_id": key_id,
        "issued_at": issued,
        "expires_at": expires,
    }
    signature = sign(SEND_RECEIPT_SIGNED_FIELDS, values, key)
    return SendReceipt(
        attempt_id=attempt_id,
        authorization_id=authorization_id,
        receiver=receiver,
        request_digest=request_digest,
        actual_body_sha256=actual_body_sha256,
        terminal_phase=terminal_phase,
        http_status=http_status,
        raw_response_sha256=raw_response_sha256,
        policy_version=policy_version,
        issuer="egress",
        key_id=key_id,
        issued_at=issued,
        expires_at=expires,
        signature=signature,
        provider_request_id=provider_request_id,
    )


def _expires_after(issued_iso: str, ttl_seconds: int) -> str:
    try:
        parsed = datetime.fromisoformat(issued_iso)
    except ValueError:
        parsed = utcnow()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    from datetime import timedelta

    return (parsed + timedelta(seconds=ttl_seconds)).isoformat()


@dataclass(frozen=True)
class ReceiptVerification:
    ok: bool
    code: str
    reason: str = ""


def verify_send_receipt(
    receipt: SendReceipt,
    *,
    key: bytes,
    prepared: SendAuditRecord,
    now: datetime | None = None,
) -> ReceiptVerification:
    """宿主验签出口收据：签名 + 绑定 + 字节摘要 + 有效期。

    失败码区分：signature_invalid / attempt_mismatch / authorization_mismatch /
    receiver_mismatch / body_digest_mismatch / expired / already_finalized。
    """
    now = now or utcnow()
    values = receipt.to_dict()
    if not verify(SEND_RECEIPT_SIGNED_FIELDS, values, key, receipt.signature):
        return ReceiptVerification(False, "signature_invalid")
    if receipt.attempt_id != prepared.attempt_id:
        return ReceiptVerification(False, "attempt_mismatch")
    if receipt.authorization_id != prepared.authorization_id:
        return ReceiptVerification(False, "authorization_mismatch")
    if receipt.receiver != prepared.receiver:
        return ReceiptVerification(False, "receiver_mismatch")
    # 出口对实际字节重算的摘要必须与持久化授权摘要一致，否则字节被改写。
    if receipt.actual_body_sha256 != prepared.request_digest:
        return ReceiptVerification(False, "body_digest_mismatch")
    if _expired(receipt.expires_at, now):
        return ReceiptVerification(False, "expired")
    if receipt.issuer != "egress":
        return ReceiptVerification(False, "issuer_invalid")
    return ReceiptVerification(True, "ok")


def verify_host_receipt(
    receipt: HostAuthorizationReceipt,
    *,
    key: bytes,
    prepared: SendAuditRecord,
    now: datetime | None = None,
) -> ReceiptVerification:
    """Launcher 验签宿主授权收据：确认 prepared 行绑定，不信任调用方填写的值。"""
    now = now or utcnow()
    values = receipt.to_dict()
    if not verify(HOST_RECEIPT_SIGNED_FIELDS, values, key, receipt.signature):
        return ReceiptVerification(False, "signature_invalid")
    if receipt.attempt_id != prepared.attempt_id:
        return ReceiptVerification(False, "attempt_mismatch")
    if receipt.authorization_id != prepared.authorization_id:
        return ReceiptVerification(False, "authorization_mismatch")
    if receipt.receiver != prepared.receiver:
        return ReceiptVerification(False, "receiver_mismatch")
    if receipt.request_digest != prepared.request_digest:
        return ReceiptVerification(False, "request_digest_mismatch")
    if _expired(receipt.expires_at, now):
        return ReceiptVerification(False, "expired")
    return ReceiptVerification(True, "ok")


def has_terminal(db, attempt_id: str) -> bool:
    return (
        db.query(SendAuditRecord)
        .filter(
            SendAuditRecord.attempt_id == attempt_id,
            SendAuditRecord.phase != "prepared",
        )
        .count()
        > 0
    )


def append_receipt_evidence(
    db,
    *,
    attempt_id: str,
    kind: str,
    receipt: dict[str, Any],
    verification: str,
) -> SendReceiptEvidence:
    """追加一条收据证据（append-only），不触碰终态唯一索引。"""
    record = SendReceiptEvidence(
        attempt_id=attempt_id,
        kind=kind,
        receipt=receipt,
        verification=verification,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def record_late_receipt(
    db,
    *,
    receipt: SendReceipt,
    key: bytes,
    prepared: SendAuditRecord,
) -> ReceiptVerification:
    """处理宿主重启后收到的迟到收据（§6.1）。

    - 若 attempt 尚无终态 → 交由调用方按正常收据落唯一终态（此处返回 ok）。
    - 若已有终态 → 只追加证据，绝不写第二条终态；过期/签名不符不落任何证据。
    """
    now = utcnow()
    # 过期收据不能成为信任依据，也不落证据。
    if _expired(receipt.expires_at, now):
        return ReceiptVerification(False, "expired")
    verification = verify_send_receipt(receipt, key=key, prepared=prepared, now=now)
    if not verification.ok:
        return verification
    if not has_terminal(db, receipt.attempt_id):
        # 无终态：正常路径，由调用方落唯一终态。
        return ReceiptVerification(True, "ok")
    # 已有终态：迟到收据 → 追加证据，不改写历史。
    append_receipt_evidence(
        db,
        attempt_id=receipt.attempt_id,
        kind="late_receipt",
        receipt=receipt.to_dict(),
        verification="verified",
    )
    return ReceiptVerification(True, "ok", reason="late_receipt_appended")
