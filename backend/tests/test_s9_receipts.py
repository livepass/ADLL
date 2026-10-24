"""S9-2 收据与审计绑定离线测试（纯逻辑，无网络/VM 依赖，跨平台）。

覆盖：摘要篡改、跨任务替换、重复收据、签名错误、过期、重启、唯一终态、
append-only、迟到证据追加。
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.models.base import utcnow
from app.models.outbound import (
    OutboundAuthorization,
    SendAuditRecord,
    SendReceiptEvidence,
)
from app.services import receipts
from app.services.outbound import finish_attempt
from app.services.receipts import (
    HostAuthorizationReceipt,
    SendReceipt,
    append_receipt_evidence,
    issue_host_receipt,
    issue_send_receipt,
    record_late_receipt,
    verify_host_receipt,
    verify_send_receipt,
)

KEY = b"offline-test-key-do-not-ship"
KEY_ID = "k1"


def _db(app):
    return app.state.db.session()


def _prepared(db, *, attempt_id="a1", auth_id=1, receiver="https://e/v1/messages", digest=None):
    digest = digest or "d" * 64
    # 外键约束：SendAuditRecord.authorization_id 必须命中存在的授权记录。
    if db.get(OutboundAuthorization, auth_id) is None:
        auth = OutboundAuthorization(
            id=auth_id,
            task_id=1,
            baseline_id=1,
            receiver=receiver,
            data_types=["requirement"],
            send_scope={"paths": ["a.txt"]},
            status="approved",
        )
        db.add(auth)
        db.commit()
    record = SendAuditRecord(
        authorization_id=auth_id,
        execution_id="e1",
        attempt_id=attempt_id,
        phase="prepared",
        receiver=receiver,
        payload_manifest={"source": []},
        content_digest="c" * 64,
        request_digest=digest,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _receipt(prepared, *, actual=None, key=KEY, **kw) -> SendReceipt:
    actual = actual or prepared.request_digest
    return issue_send_receipt(
        attempt_id=prepared.attempt_id,
        authorization_id=prepared.authorization_id,
        receiver=prepared.receiver,
        request_digest=prepared.request_digest,
        actual_body_sha256=actual,
        terminal_phase="confirmed_sent",
        http_status=200,
        raw_response_sha256="r" * 64,
        policy_version="v1",
        key_id=KEY_ID,
        key=key,
        **kw,
    )


def test_valid_receipt_verifies(app) -> None:
    db = _db(app)
    try:
        prepared = _prepared(db)
        assert verify_send_receipt(_receipt(prepared), key=KEY, prepared=prepared).ok is True
    finally:
        db.close()


def test_signature_invalid_rejected(app) -> None:
    db = _db(app)
    try:
        prepared = _prepared(db)
        result = verify_send_receipt(_receipt(prepared, key=b"wrong-key"), key=KEY, prepared=prepared)
        assert result.ok is False and result.code == "signature_invalid"
    finally:
        db.close()


def test_body_digest_mismatch_rejected(app) -> None:
    """摘要篡改：出口回显的 actual_body_sha256 与授权摘要不一致 → 拒绝。"""
    db = _db(app)
    try:
        prepared = _prepared(db, digest="a" * 64)
        result = verify_send_receipt(_receipt(prepared, actual="b" * 64), key=KEY, prepared=prepared)
        assert result.ok is False and result.code == "body_digest_mismatch"
    finally:
        db.close()


def test_cross_task_replacement_rejected(app) -> None:
    """跨任务替换：收据 attempt_id/authorization_id 与 prepared 行不一致 → 拒绝。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="a1", auth_id=1)
        # 跨任务替换 attempt_id：构造 attempt_id 与 prepared 不一致的收据。
        wrong_attempt = issue_send_receipt(
            attempt_id="a2",
            authorization_id=prepared.authorization_id,
            receiver=prepared.receiver,
            request_digest=prepared.request_digest,
            actual_body_sha256=prepared.request_digest,
            terminal_phase="confirmed_sent",
            http_status=200,
            raw_response_sha256="r" * 64,
            policy_version="v1",
            key_id=KEY_ID,
            key=KEY,
        )
        assert verify_send_receipt(wrong_attempt, key=KEY, prepared=prepared).code == "attempt_mismatch"

        receipt = issue_send_receipt(
            attempt_id=prepared.attempt_id,
            authorization_id=999,
            receiver=prepared.receiver,
            request_digest=prepared.request_digest,
            actual_body_sha256=prepared.request_digest,
            terminal_phase="confirmed_sent",
            http_status=200,
            raw_response_sha256="r" * 64,
            policy_version="v1",
            key_id=KEY_ID,
            key=KEY,
        )
        assert verify_send_receipt(receipt, key=KEY, prepared=prepared).code == "authorization_mismatch"
    finally:
        db.close()


def test_expired_receipt_rejected(app) -> None:
    """过期收据不能成为信任依据（审计保留与信任判定分离）。"""
    db = _db(app)
    try:
        prepared = _prepared(db)
        past = (utcnow() - timedelta(seconds=60)).isoformat()
        values = {
            "attempt_id": prepared.attempt_id,
            "authorization_id": prepared.authorization_id,
            "receiver": prepared.receiver,
            "request_digest": prepared.request_digest,
            "actual_body_sha256": prepared.request_digest,
            "terminal_phase": "confirmed_sent",
            "http_status": 200,
            "raw_response_sha256": "r" * 64,
            "provider_request_id": None,
            "policy_version": "v1",
            "issuer": "egress",
            "key_id": KEY_ID,
            "issued_at": past,
            "expires_at": past,
        }
        sig = receipts.sign(receipts.SEND_RECEIPT_SIGNED_FIELDS, values, KEY)
        expired = SendReceipt(
            attempt_id=prepared.attempt_id,
            authorization_id=prepared.authorization_id,
            receiver=prepared.receiver,
            request_digest=prepared.request_digest,
            actual_body_sha256=prepared.request_digest,
            terminal_phase="confirmed_sent",
            http_status=200,
            raw_response_sha256="r" * 64,
            policy_version="v1",
            issuer="egress",
            key_id=KEY_ID,
            issued_at=past,
            expires_at=past,
            signature=sig,
        )
        result = verify_send_receipt(expired, key=KEY, prepared=prepared)
        assert result.ok is False and result.code == "expired"
    finally:
        db.close()


def test_host_receipt_verifies_and_rejects_tamper(app) -> None:
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="h1", auth_id=7)
        receipt = issue_host_receipt(
            attempt_id=prepared.attempt_id,
            authorization_id=prepared.authorization_id,
            receiver=prepared.receiver,
            request_digest=prepared.request_digest,
            policy_version="v1",
            key_id=KEY_ID,
            key=KEY,
        )
        assert verify_host_receipt(receipt, key=KEY, prepared=prepared).ok is True

        tampered = HostAuthorizationReceipt(
            attempt_id=receipt.attempt_id,
            authorization_id=receipt.authorization_id,
            receiver=receipt.receiver,
            request_digest="e" * 64,
            authorization_status=receipt.authorization_status,
            policy_version=receipt.policy_version,
            key_id=receipt.key_id,
            issued_at=receipt.issued_at,
            expires_at=receipt.expires_at,
            signature=receipt.signature,
        )
        assert verify_host_receipt(tampered, key=KEY, prepared=prepared).code == "signature_invalid"
    finally:
        db.close()


def test_late_receipt_appends_evidence_not_second_terminal(app) -> None:
    """迟到收据：已有终态 → 追加证据，不写第二条终态。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="late1")
        finish_attempt(db, prepared.attempt_id, phase="possibly_sent", error_code="restart_unconfirmed")

        result = record_late_receipt(db, receipt=_receipt(prepared), key=KEY, prepared=prepared)
        assert result.ok is True and result.reason == "late_receipt_appended"

        terminals = (
            db.query(SendAuditRecord)
            .filter(SendAuditRecord.attempt_id == prepared.attempt_id, SendAuditRecord.phase != "prepared")
            .all()
        )
        assert len(terminals) == 1 and terminals[0].phase == "possibly_sent"

        evidence = db.query(SendReceiptEvidence).filter_by(attempt_id=prepared.attempt_id, kind="late_receipt").all()
        assert len(evidence) == 1 and evidence[0].verification == "verified"
    finally:
        db.close()


def test_late_receipt_expired_not_appended(app) -> None:
    """过期迟到收据：不落任何证据。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="late_exp")
        finish_attempt(db, prepared.attempt_id, phase="possibly_sent", error_code="restart_unconfirmed")

        past = (utcnow() - timedelta(seconds=60)).isoformat()
        values = {
            "attempt_id": prepared.attempt_id,
            "authorization_id": prepared.authorization_id,
            "receiver": prepared.receiver,
            "request_digest": prepared.request_digest,
            "actual_body_sha256": prepared.request_digest,
            "terminal_phase": "confirmed_sent",
            "http_status": 200,
            "raw_response_sha256": "r" * 64,
            "provider_request_id": None,
            "policy_version": "v1",
            "issuer": "egress",
            "key_id": KEY_ID,
            "issued_at": past,
            "expires_at": past,
        }
        sig = receipts.sign(receipts.SEND_RECEIPT_SIGNED_FIELDS, values, KEY)
        expired = SendReceipt(
            attempt_id=prepared.attempt_id,
            authorization_id=prepared.authorization_id,
            receiver=prepared.receiver,
            request_digest=prepared.request_digest,
            actual_body_sha256=prepared.request_digest,
            terminal_phase="confirmed_sent",
            http_status=200,
            raw_response_sha256="r" * 64,
            policy_version="v1",
            issuer="egress",
            key_id=KEY_ID,
            issued_at=past,
            expires_at=past,
            signature=sig,
        )
        result = record_late_receipt(db, receipt=expired, key=KEY, prepared=prepared)
        assert result.ok is False and result.code == "expired"
        assert db.query(SendReceiptEvidence).filter_by(attempt_id=prepared.attempt_id).count() == 0
    finally:
        db.close()


def test_no_terminal_receipt_returns_ok_for_normal_path(app) -> None:
    """无终态时收据走正常路径（由调用方落唯一终态），不追加迟到证据。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="normal1")
        result = record_late_receipt(db, receipt=_receipt(prepared), key=KEY, prepared=prepared)
        assert result.ok is True and result.reason == ""
        assert db.query(SendReceiptEvidence).filter_by(attempt_id=prepared.attempt_id).count() == 0
    finally:
        db.close()


def test_append_receipt_evidence_is_append_only(app) -> None:
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="multi")
        append_receipt_evidence(db, attempt_id=prepared.attempt_id, kind="late_receipt", receipt={"attempt_id": prepared.attempt_id}, verification="verified")
        append_receipt_evidence(db, attempt_id=prepared.attempt_id, kind="late_receipt", receipt={"attempt_id": prepared.attempt_id}, verification="verified")
        assert db.query(SendReceiptEvidence).filter_by(attempt_id=prepared.attempt_id).count() == 2
    finally:
        db.close()


def test_late_receipt_idempotent_on_duplicate(app) -> None:
    """同一迟到收据重复提交幂等：不产生重复可信证据。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="dup1")
        finish_attempt(db, prepared.attempt_id, phase="possibly_sent", error_code="restart_unconfirmed")
        receipt = _receipt(prepared)

        first = record_late_receipt(db, receipt=receipt, key=KEY, prepared=prepared)
        assert first.ok is True and first.reason == "late_receipt_appended"

        second = record_late_receipt(db, receipt=receipt, key=KEY, prepared=prepared)
        assert second.ok is True and second.reason == "late_receipt_already_recorded"

        assert db.query(SendReceiptEvidence).filter_by(attempt_id=prepared.attempt_id, kind="late_receipt").count() == 1
    finally:
        db.close()


def test_provider_request_id_tamper_rejected(app) -> None:
    """provider_request_id 纳入签名：篡改后验签失败。"""
    db = _db(app)
    try:
        prepared = _prepared(db)
        receipt = _receipt(prepared, provider_request_id="req-123")
        # 篡改 provider_request_id（签名未覆盖到新值）→ 验签失败。
        tampered = SendReceipt(
            **{**receipt.to_dict(), "provider_request_id": "req-EVIL"}
        )
        result = verify_send_receipt(tampered, key=KEY, prepared=prepared)
        assert result.ok is False and result.code == "signature_invalid"
    finally:
        db.close()


def test_issued_at_in_future_rejected(app) -> None:
    """签发时间不能晚于当前（防未来时间戳回填）。"""
    db = _db(app)
    try:
        prepared = _prepared(db)
        future = (utcnow() + timedelta(hours=1)).isoformat()
        values = {
            "attempt_id": prepared.attempt_id,
            "authorization_id": prepared.authorization_id,
            "receiver": prepared.receiver,
            "request_digest": prepared.request_digest,
            "actual_body_sha256": prepared.request_digest,
            "terminal_phase": "confirmed_sent",
            "http_status": 200,
            "raw_response_sha256": "r" * 64,
            "provider_request_id": None,
            "policy_version": "v1",
            "issuer": "egress",
            "key_id": KEY_ID,
            "issued_at": future,
            "expires_at": future,
        }
        sig = receipts.sign(receipts.SEND_RECEIPT_SIGNED_FIELDS, values, KEY)
        fut = SendReceipt(
            attempt_id=prepared.attempt_id,
            authorization_id=prepared.authorization_id,
            receiver=prepared.receiver,
            request_digest=prepared.request_digest,
            actual_body_sha256=prepared.request_digest,
            terminal_phase="confirmed_sent",
            http_status=200,
            raw_response_sha256="r" * 64,
            policy_version="v1",
            issuer="egress",
            key_id=KEY_ID,
            issued_at=future,
            expires_at=future,
            signature=sig,
        )
        result = verify_send_receipt(fut, key=KEY, prepared=prepared)
        assert result.ok is False and result.code == "issued_at_invalid"
    finally:
        db.close()


def test_policy_version_mismatch_rejected(app) -> None:
    """策略版本与宿主预期不一致 → 拒绝。"""
    db = _db(app)
    try:
        prepared = _prepared(db)
        receipt = _receipt(prepared)
        result = verify_send_receipt(receipt, key=KEY, prepared=prepared, expected_policy_version="v2")
        assert result.ok is False and result.code == "policy_version_mismatch"
    finally:
        db.close()


def test_receipt_evidence_forbids_update_and_delete(app) -> None:
    """数据库级 UPDATE/DELETE 禁止：触发器阻断改写/删除证据。"""
    from sqlalchemy.exc import IntegrityError

    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="immut1")
        row = append_receipt_evidence(
            db, attempt_id=prepared.attempt_id, kind="late_receipt",
            receipt={"attempt_id": prepared.attempt_id}, verification="verified",
        )
        # UPDATE 应被触发器拒绝。
        with pytest.raises(IntegrityError):
            db.query(SendReceiptEvidence).filter_by(id=row.id).update({"verification": "forged"})
            db.commit()
        db.rollback()
        # DELETE 应被触发器拒绝。
        with pytest.raises(IntegrityError):
            db.query(SendReceiptEvidence).filter_by(id=row.id).delete()
            db.commit()
        db.rollback()
        # 记录仍在且未被改写。
        db.expire_all()
        kept = db.get(SendReceiptEvidence, row.id)
        assert kept is not None and kept.verification == "verified"
    finally:
        db.close()


def test_host_receipt_rejects_non_approved_status(app) -> None:
    """宿主授权收据状态非 approved（如 revoked）→ 拒绝放行。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="host_rev", auth_id=11)
        # 用 revoked 状态签发（签名有效，但状态不合法）。
        issued = receipts._now_iso()
        expires = receipts._expires_after(issued, 300)
        values = {
            "attempt_id": prepared.attempt_id,
            "authorization_id": prepared.authorization_id,
            "receiver": prepared.receiver,
            "request_digest": prepared.request_digest,
            "authorization_status": "revoked",
            "policy_version": "v1",
            "key_id": KEY_ID,
            "issued_at": issued,
            "expires_at": expires,
        }
        sig = receipts.sign(receipts.HOST_RECEIPT_SIGNED_FIELDS, values, KEY)
        revoked = HostAuthorizationReceipt(
            attempt_id=prepared.attempt_id,
            authorization_id=prepared.authorization_id,
            receiver=prepared.receiver,
            request_digest=prepared.request_digest,
            authorization_status="revoked",
            policy_version="v1",
            key_id=KEY_ID,
            issued_at=issued,
            expires_at=expires,
            signature=sig,
        )
        result = verify_host_receipt(revoked, key=KEY, prepared=prepared)
        assert result.ok is False and result.code == "authorization_not_approved"
    finally:
        db.close()


def test_host_receipt_rejects_future_issued_at(app) -> None:
    """宿主授权收据签发时间在未来 → 拒绝。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="host_future", auth_id=12)
        future = (utcnow() + timedelta(hours=1)).isoformat()
        later = (utcnow() + timedelta(hours=2)).isoformat()
        values = {
            "attempt_id": prepared.attempt_id,
            "authorization_id": prepared.authorization_id,
            "receiver": prepared.receiver,
            "request_digest": prepared.request_digest,
            "authorization_status": "approved",
            "policy_version": "v1",
            "key_id": KEY_ID,
            "issued_at": future,
            "expires_at": later,
        }
        sig = receipts.sign(receipts.HOST_RECEIPT_SIGNED_FIELDS, values, KEY)
        fut = HostAuthorizationReceipt(
            attempt_id=prepared.attempt_id,
            authorization_id=prepared.authorization_id,
            receiver=prepared.receiver,
            request_digest=prepared.request_digest,
            authorization_status="approved",
            policy_version="v1",
            key_id=KEY_ID,
            issued_at=future,
            expires_at=later,
            signature=sig,
        )
        result = verify_host_receipt(fut, key=KEY, prepared=prepared)
        assert result.ok is False and result.code == "issued_at_invalid"
    finally:
        db.close()


def test_host_receipt_rejects_unaccepted_policy_version(app) -> None:
    """宿主授权收据的策略版本不在 Launcher 认可集合 → 拒绝。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="host_pol", auth_id=13)
        receipt = issue_host_receipt(
            attempt_id=prepared.attempt_id,
            authorization_id=prepared.authorization_id,
            receiver=prepared.receiver,
            request_digest=prepared.request_digest,
            policy_version="v1",
            key_id=KEY_ID,
            key=KEY,
        )
        result = verify_host_receipt(
            receipt, key=KEY, prepared=prepared, allowed_policy_versions=("v2",)
        )
        assert result.ok is False and result.code == "policy_version_not_accepted"
    finally:
        db.close()


def test_receipt_evidence_unique_index_blocks_concurrent_duplicate(app) -> None:
    """并发兜底：同一 (attempt_id, kind, signature) 第二次插入被唯一索引拒绝。"""
    from sqlalchemy.exc import IntegrityError

    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="race1")
        payload = {"attempt_id": prepared.attempt_id, "signature": "same-sig"}
        append_receipt_evidence(
            db, attempt_id=prepared.attempt_id, kind="late_receipt",
            receipt=payload, verification="verified",
        )
        # 第二次（模拟并发写入者绕过应用层快路径）必须被数据库拒绝。
        with pytest.raises(IntegrityError):
            append_receipt_evidence(
                db, attempt_id=prepared.attempt_id, kind="late_receipt",
                receipt=payload, verification="verified",
            )
        db.rollback()
        assert (
            db.query(SendReceiptEvidence)
            .filter_by(attempt_id=prepared.attempt_id, kind="late_receipt")
            .count()
            == 1
        )
    finally:
        db.close()
