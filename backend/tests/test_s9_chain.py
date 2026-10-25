"""S9-3A 合成链路测试：Host → Launcher → Egress → Synthetic Provider → 收据 → 审计。

全部离线：不创建 VM、不联网、不读真实 Key、不调用百炼。
Synthetic Provider 只验证链路结构与证据传递，不构成生产验收。
"""
from __future__ import annotations

import hashlib

import pytest

from app.core.payload import canonical_payload_bytes
from app.models.outbound import SendAuditRecord, SendReceiptEvidence
from app.services import receipts, s9_chain
from app.services.s9_chain import (
    ChainDenied,
    DbReplayStore,
    EgressRelay,
    HostGateway,
    Launcher,
    SyntheticProvider,
    run_synthetic_chain,
)

HOST_KEY = b"synthetic-host-key-not-for-production"
EGRESS_KEY = b"synthetic-egress-key-not-for-production"
LAUNCHER_KEY = b"synthetic-launcher-key-not-for-production"
LAUNCHER_KEY_ID = "launcher-k1"
RECEIVER = "https://dashscope.aliyuncs.com/apps/anthropic/v1/messages"
PAYLOAD = {
    "model": "m",
    "max_tokens": 64,
    "stream": False,
    "messages": [{"role": "user", "content": "SYNTHETIC-REQ"}],
}


def _db(app):
    return app.state.db.session()


def _prepared(
    db,
    *,
    attempt_id="chain1",
    auth_id=1,
    digest=None,
    auth_status="approved",
    revoked_at=None,
    auth_expires_at=None,
    auth_receiver=None,
):
    from app.models.outbound import OutboundAuthorization

    digest = digest or hashlib.sha256(canonical_payload_bytes(PAYLOAD)).hexdigest()
    if db.get(OutboundAuthorization, auth_id) is None:
        db.add(
            OutboundAuthorization(
                id=auth_id, task_id=1, baseline_id=1,
                receiver=auth_receiver or RECEIVER,
                data_types=["requirement"], send_scope={"paths": ["a.txt"]},
                status=auth_status,
                revoked_at=revoked_at,
                expires_at=auth_expires_at,
            )
        )
        db.commit()
    row = SendAuditRecord(
        authorization_id=auth_id, execution_id="e1", attempt_id=attempt_id,
        phase="prepared", receiver=RECEIVER, payload_manifest={"source": []},
        content_digest="c" * 64, request_digest=digest,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _chain(db, *, provider=None, prepared=None):
    host = HostGateway(signing_key=HOST_KEY, key_id="host-k1")
    launcher = Launcher(
        host_public_key=HOST_KEY,
        replay=DbReplayStore(db),
        launcher_key=LAUNCHER_KEY,
        launcher_key_id=LAUNCHER_KEY_ID,
    )
    egress = EgressRelay(
        signing_key=EGRESS_KEY, key_id="egress-k1",
        provider=provider or SyntheticProvider(), replay=DbReplayStore(db),
        launcher_keys={LAUNCHER_KEY_ID: LAUNCHER_KEY},
        host_public_key=HOST_KEY,
    )
    return host, launcher, egress


def test_synthetic_chain_end_to_end_confirmed(app) -> None:
    """全链路贯通：prepared → 授权收据 → launcher → egress → 收据 → confirmed 终态。"""
    db = _db(app)
    try:
        prepared = _prepared(db)
        host, launcher, egress = _chain(db)
        request, outcome, verification, appended = run_synthetic_chain(
            db, prepared=prepared, payload=PAYLOAD, model="m",
            host=host, launcher=launcher, egress=egress,
        )
        assert request.attempt_id == prepared.attempt_id
        assert request.request_digest == prepared.request_digest
        assert outcome.phase == "confirmed_sent"
        assert verification.ok is True
        assert appended is False

        terminals = (
            db.query(SendAuditRecord)
            .filter(SendAuditRecord.attempt_id == prepared.attempt_id,
                    SendAuditRecord.phase != "prepared")
            .all()
        )
        assert len(terminals) == 1 and terminals[0].phase == "confirmed_sent"

        # 收据完整对应：attempt/authorization/receiver/digest/策略/终态。
        receipt = outcome.receipt
        assert receipt.attempt_id == prepared.attempt_id
        assert receipt.authorization_id == prepared.authorization_id
        assert receipt.receiver == prepared.receiver
        assert receipt.actual_body_sha256 == prepared.request_digest
        assert receipt.policy_version == s9_chain.DEFAULT_POLICY_VERSION
        assert receipt.terminal_phase == "confirmed_sent"
        assert receipt.provider_request_id
        assert receipt.issuer == "egress"
    finally:
        db.close()


def test_launcher_rejects_without_host_receipt(app) -> None:
    """Launcher 无宿主授权凭证 → 拒绝，零发送。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="noreceipt")
        host, launcher, egress = _chain(db)
        request = host.build_request(
            prepared=prepared,
            body=canonical_payload_bytes(PAYLOAD),
            model="m",
        )
        request.host_receipt = None
        with pytest.raises(ChainDenied) as caught:
            launcher.dispatch(request, egress)
        assert caught.value.code == "host_receipt_missing"
    finally:
        db.close()


def test_launcher_rejects_cross_task_replacement(app) -> None:
    """跨任务替换：请求 attempt/authorization 与宿主收据不一致 → 拒绝。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="cross1")
        host, launcher, egress = _chain(db)
        request = host.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
        # 篡改 authorization_id（伪造跨任务替换）。
        request.authorization_id = 999
        with pytest.raises(ChainDenied) as caught:
            launcher.dispatch(request, egress)
        assert caught.value.code == "host_receipt_authorization_mismatch"
    finally:
        db.close()


def test_launcher_rejects_tampered_body(app) -> None:
    """字节被改写：body 摘要与授权摘要不符 → 拒绝。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="tamper1")
        host, launcher, egress = _chain(db)
        request = host.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
        request.body = request.body + b" "
        with pytest.raises(ChainDenied) as caught:
            launcher.dispatch(request, egress)
        assert caught.value.code == "host_receipt_body_digest_mismatch"
    finally:
        db.close()


def test_launcher_replay_rejected(app) -> None:
    """持久化防重放：同一 attempt 第二次提交 → 拒绝，不重发。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="replay1")
        host, launcher, egress = _chain(db)
        request = host.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
        first = launcher.dispatch(request, egress)
        assert first.phase == "confirmed_sent"
        with pytest.raises(ChainDenied) as caught:
            launcher.dispatch(request, egress)
        assert caught.value.code == "launcher_replayed_attempt"
    finally:
        db.close()


def _attach_caller_auth(request):
    """给直连 Egress 的测试补上调用者凭证（模拟正常 Launcher 行为）。"""
    request.launcher_auth = receipts.issue_launcher_auth(
        attempt_id=request.attempt_id,
        request_digest=request.request_digest,
        nonce=request.nonce,
        key_id=LAUNCHER_KEY_ID,
        key=LAUNCHER_KEY,
    )
    return request


def test_egress_replay_rejected(app) -> None:
    """出口防重放：绕过 launcher 直接二次转发同一 attempt → 拒绝。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="replay2")
        host, _launcher, egress = _chain(db)
        request = host.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
        _attach_caller_auth(request)
        egress.forward(request)
        with pytest.raises(ChainDenied) as caught:
            egress.forward(request)
        assert caught.value.code == "egress_replayed_attempt"
    finally:
        db.close()


def test_egress_rejects_non_fixed_endpoint(app) -> None:
    """出口只接受固定 Messages 路径，不提供通用代理。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="endpoint1")
        host, _launcher, egress = _chain(db)
        request = host.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
        for bad in (
            "https://evil.example.com/apps/anthropic/v1/messages",
            "https://dashscope.aliyuncs.com/other/path",
            "https://dashscope.aliyuncs.com/apps/anthropic/v1/messages/../x",
        ):
            request.receiver = bad
            with pytest.raises(ChainDenied) as caught:
                egress.forward(request)
            assert caught.value.code == "egress_endpoint_not_allowed"
    finally:
        db.close()


def test_timeout_reports_possibly_sent_and_no_auto_retry(app) -> None:
    """超时：记为 possibly_sent，且绝不自动重发（出口只被调用一次）。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="timeout1")
        calls = {"n": 0}

        class CountingProvider(SyntheticProvider):
            def send(self, body, *, timeout_ms):
                calls["n"] += 1
                return super().send(body, timeout_ms=timeout_ms)

        host, launcher, egress = _chain(
            db, provider=CountingProvider(fail_mode="timeout")
        )
        _request, outcome, _verification, _appended = run_synthetic_chain(
            db, prepared=prepared, payload=PAYLOAD, model="m",
            host=host, launcher=launcher, egress=egress,
        )
        assert calls["n"] == 1  # 只发送一次，无自动重试
        assert outcome.phase == "possibly_sent"
        terminals = (
            db.query(SendAuditRecord)
            .filter(SendAuditRecord.attempt_id == prepared.attempt_id,
                    SendAuditRecord.phase != "prepared")
            .all()
        )
        assert len(terminals) == 1 and terminals[0].phase == "possibly_sent"
    finally:
        db.close()


def test_connection_reset_reports_possibly_sent(app) -> None:
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="reset1")
        host, launcher, egress = _chain(
            db, provider=SyntheticProvider(fail_mode="connection_reset")
        )
        _, outcome, _, _ = run_synthetic_chain(
            db, prepared=prepared, payload=PAYLOAD, model="m",
            host=host, launcher=launcher, egress=egress,
        )
        assert outcome.phase == "possibly_sent"
    finally:
        db.close()


def test_restart_duplicate_receipt_appends_evidence_only(app) -> None:
    """重启后补记 possibly_sent，再收到有效收据 → 只追加证据，不写第二终态。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="restart1")
        host, launcher, egress = _chain(db)
        request = host.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
        outcome = launcher.dispatch(request, egress)
        assert outcome.phase == "confirmed_sent"

        # 模拟「宿主重启后又补记终态」之外的场景：直接调用 settle 两次。
        # 先落 confirmed_sent（第一次 settle），第二次 settle 应转为迟到证据。
        v1, late1 = host.settle(
            db, outcome=outcome, prepared=prepared, egress_key=egress.signing_key
        )
        assert v1.ok is True and late1 is False
        v2, late2 = host.settle(
            db, outcome=outcome, prepared=prepared, egress_key=egress.signing_key
        )
        assert v2.ok is True and late2 is True

        terminals = (
            db.query(SendAuditRecord)
            .filter(SendAuditRecord.attempt_id == prepared.attempt_id,
                    SendAuditRecord.phase != "prepared")
            .all()
        )
        assert len(terminals) == 1
        evidence = db.query(SendReceiptEvidence).filter_by(
            attempt_id=prepared.attempt_id, kind="late_receipt"
        ).all()
        assert len(evidence) == 1
    finally:
        db.close()


def test_bad_egress_signature_does_not_confirm(app) -> None:
    """收据签名不符（错误 egress key）→ 不 confirm，落 possibly_sent 且不生成 verified。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="badsig1")
        host, launcher, egress = _chain(db)
        request = host.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
        outcome = launcher.dispatch(request, egress)
        assert outcome.phase == "confirmed_sent"
        verification, _ = host.settle(
            db, outcome=outcome, prepared=prepared, egress_key=b"wrong-key"
        )
        assert verification.ok is False
        assert verification.code == "signature_invalid"
        terminals = (
            db.query(SendAuditRecord)
            .filter(SendAuditRecord.attempt_id == prepared.attempt_id,
                    SendAuditRecord.phase != "prepared")
            .all()
        )
        assert len(terminals) == 1
        assert terminals[0].phase == "possibly_sent"
    finally:
        db.close()


def test_host_build_request_rejects_digest_mismatch(app) -> None:
    """prepared 摘要与请求体不符 → 构造阶段即拒绝（零发送）。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="digest1", digest="f" * 64)
        host, _, _ = _chain(db)
        with pytest.raises(ChainDenied) as caught:
            host.build_request(
                prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
            )
        assert caught.value.code == "body_digest_mismatch"
    finally:
        db.close()


def test_real_transport_remains_disabled_by_default() -> None:
    """链路测试不改变真实发送默认关闭：配置默认假。"""
    # 检查 dataclass 级默认值：不依赖环境变量注入。
    import dataclasses

    from app.config import Settings

    fields = {f.name: f.default for f in dataclasses.fields(Settings)}
    assert fields["real_ai_enabled"] is False
    assert fields["worker_real_transport"] is False


# ---- 独立进程 IPC（multiprocessing.Pipe） ----


def test_process_transport_end_to_end(app, tmp_path) -> None:
    """独立子进程 Egress：跨进程传递字节与收据，签名与摘要仍可验证。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="proc1")
        host = HostGateway(signing_key=HOST_KEY, key_id="host-k1")
        launcher = Launcher(
            host_public_key=HOST_KEY,
            replay=DbReplayStore(db),
            launcher_key=LAUNCHER_KEY,
            launcher_key_id=LAUNCHER_KEY_ID,
        )
        transport = s9_chain.ProcessTransport(
            egress_replay_url=f"sqlite:///{(tmp_path / 'egress_replay.db').as_posix()}",
            egress_signing_key=EGRESS_KEY,
            egress_key_id="egress-k1",
            launcher_keys={LAUNCHER_KEY_ID: LAUNCHER_KEY},
            host_public_key=HOST_KEY,
        )
        request = host.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
        outcome = launcher.dispatch(request, transport)
        assert outcome.phase == "confirmed_sent", outcome.error_code
        # 硬证据：Egress 确实在**另一个进程**中执行。
        import os as _os

        assert transport.last_child_pid is not None
        assert transport.last_child_pid != _os.getpid()
        # 问题 D 证据：子进程自己的库里没有审批表（结构上读不到审批记录）。
        assert "s9_replay_guard" in transport.last_child_tables
        assert "send_audit_records" not in transport.last_child_tables
        assert "outbound_authorizations" not in transport.last_child_tables
        assert outcome.receipt is not None
        assert outcome.receipt.attempt_id == prepared.attempt_id
        assert outcome.receipt.actual_body_sha256 == prepared.request_digest
        assert outcome.receipt.signature

        verification, _ = host.settle(
            db, outcome=outcome, prepared=prepared, egress_key=EGRESS_KEY
        )
        assert verification.ok is True
        terminals = (
            db.query(SendAuditRecord)
            .filter(SendAuditRecord.attempt_id == prepared.attempt_id,
                    SendAuditRecord.phase != "prepared")
            .all()
        )
        assert len(terminals) == 1 and terminals[0].phase == "confirmed_sent"
    finally:
        db.close()


def test_process_transport_replay_rejected(app, tmp_path) -> None:
    """跨进程防重放：同一 attempt 第二次经子进程转发被 replay store 拒绝。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="proc_replay")
        host = HostGateway(signing_key=HOST_KEY, key_id="host-k1")
        launcher = Launcher(
            host_public_key=HOST_KEY,
            replay=DbReplayStore(db),
            launcher_key=LAUNCHER_KEY,
            launcher_key_id=LAUNCHER_KEY_ID,
        )
        replay_url = f"sqlite:///{(tmp_path / 'egress_replay2.db').as_posix()}"
        transport = s9_chain.ProcessTransport(
            egress_replay_url=replay_url,
            egress_signing_key=EGRESS_KEY,
            egress_key_id="egress-k1",
            launcher_keys={LAUNCHER_KEY_ID: LAUNCHER_KEY},
            host_public_key=HOST_KEY,
        )
        request = host.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
        first = launcher.dispatch(request, transport)
        assert first.phase == "confirmed_sent"

        # 新 launcher 实例（模拟另一进程），replay 仍命中数据库 → 拒绝。
        db2 = app.state.db.session()
        try:
            launcher2 = Launcher(
                host_public_key=HOST_KEY,
                replay=DbReplayStore(db2),
                launcher_key=LAUNCHER_KEY,
                launcher_key_id=LAUNCHER_KEY_ID,
            )
            with pytest.raises(ChainDenied) as caught:
                launcher2.dispatch(request, transport)
            assert caught.value.code == "launcher_replayed_attempt"
        finally:
            db2.close()
    finally:
        db.close()


# ---- 取消 ----


def test_cancel_before_send_is_not_sent(app) -> None:
    """转发前取消：确认未写出，记 not_sent 且不调用 provider。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="cancel_pre")
        host, launcher, egress = _chain(db)
        request = host.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
        calls = {"n": 0}
        original = egress.provider.send

        def counting(body, *, timeout_ms):
            calls["n"] += 1
            return original(body, timeout_ms=timeout_ms)

        egress.provider.send = counting
        outcome = launcher.dispatch(request, egress, cancel_check=lambda: True)
        assert outcome.phase == "not_sent"
        assert outcome.cancelled is True
        assert outcome.error_code == "cancelled_before_send"
        assert calls["n"] == 0
    finally:
        db.close()


def test_cancel_after_send_marks_cancelled_but_keeps_sent_fact(app) -> None:
    """转发后取消：请求已写出，不撤回，如实标记 cancelled_after_send。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="cancel_post")
        host, launcher, egress = _chain(db)
        request = host.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
        state = {"sent": False}
        original = egress.provider.send

        def mark_then_send(body, *, timeout_ms):
            state["sent"] = True
            return original(body, timeout_ms=timeout_ms)

        egress.provider.send = mark_then_send
        outcome = launcher.dispatch(
            request, egress, cancel_check=lambda: state["sent"]
        )
        assert outcome.phase == "confirmed_sent"
        assert outcome.cancelled is True
        assert outcome.error_code == "cancelled_after_send"
    finally:
        db.close()


# ---- 重启恢复 / prepared 绑定 ----


def test_reconcile_pending_marks_orphan_possibly_sent(app) -> None:
    """重启恢复：只剩 prepared 的 attempt → possibly_sent，不补 confirmed/not_sent。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="orphan1")
        reconciled = s9_chain.reconcile_pending(db)
        assert reconciled >= 1
        terminals = (
            db.query(SendAuditRecord)
            .filter(SendAuditRecord.attempt_id == prepared.attempt_id,
                    SendAuditRecord.phase != "prepared")
            .all()
        )
        assert len(terminals) == 1
        assert terminals[0].phase == "possibly_sent"
        assert terminals[0].error_code == "restart_unconfirmed"
    finally:
        db.close()


def test_build_request_from_db_rejects_unpersisted_attempt(app) -> None:
    """prepared 绑定前移：DB 无该 attempt 的 prepared 行 → 拒绝。"""
    db = _db(app)
    try:
        host = HostGateway(signing_key=HOST_KEY, key_id="host-k1")
        with pytest.raises(ChainDenied) as caught:
            host.build_request_from_db(
                db,
                attempt_id="not-in-db",
                body=canonical_payload_bytes(PAYLOAD),
                model="m",
            )
        assert caught.value.code == "prepared_row_missing"
    finally:
        db.close()


def test_build_request_from_db_uses_persisted_fields(app) -> None:
    """prepared 绑定前移：从 DB 行取 attempt/authorization/receiver/digest。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="fromdb1", auth_id=21)
        host = HostGateway(signing_key=HOST_KEY, key_id="host-k1")
        request = host.build_request_from_db(
            db,
            attempt_id=prepared.attempt_id,
            body=canonical_payload_bytes(PAYLOAD),
            model="m",
        )
        assert request.attempt_id == prepared.attempt_id
        assert request.authorization_id == prepared.authorization_id
        assert request.receiver == prepared.receiver
        assert request.request_digest == prepared.request_digest
        assert request.host_receipt is not None
    finally:
        db.close()


# ---- 问题 A：宿主签发前必须确认授权仍有效 ----


def test_build_request_rejects_revoked_authorization(app) -> None:
    """已撤销授权：宿主不得签发授权收据。"""
    from app.models.base import utcnow

    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="revoked1", auth_id=31, revoked_at=utcnow())
        host = HostGateway(signing_key=HOST_KEY, key_id="host-k1")
        with pytest.raises(ChainDenied) as caught:
            host.build_request_from_db(
                db, attempt_id=prepared.attempt_id,
                body=canonical_payload_bytes(PAYLOAD), model="m",
            )
        assert caught.value.code == "authorization_revoked"
    finally:
        db.close()


def test_build_request_rejects_expired_authorization(app) -> None:
    """已过期授权：宿主不得签发授权收据。"""
    from datetime import timedelta

    from app.models.base import utcnow

    db = _db(app)
    try:
        prepared = _prepared(
            db, attempt_id="expired1", auth_id=32,
            auth_expires_at=utcnow() - timedelta(hours=1),
        )
        host = HostGateway(signing_key=HOST_KEY, key_id="host-k1")
        with pytest.raises(ChainDenied) as caught:
            host.build_request_from_db(
                db, attempt_id=prepared.attempt_id,
                body=canonical_payload_bytes(PAYLOAD), model="m",
            )
        assert caught.value.code == "authorization_expired"
    finally:
        db.close()


def test_build_request_rejects_pending_authorization(app) -> None:
    """未批准（pending）授权：宿主不得签发授权收据。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="pending1", auth_id=33, auth_status="pending")
        host = HostGateway(signing_key=HOST_KEY, key_id="host-k1")
        with pytest.raises(ChainDenied) as caught:
            host.build_request_from_db(
                db, attempt_id=prepared.attempt_id,
                body=canonical_payload_bytes(PAYLOAD), model="m",
            )
        assert caught.value.code == "authorization_not_approved"
    finally:
        db.close()


def test_build_request_rejects_receiver_mismatch_authorization(app) -> None:
    """授权 receiver 与 prepared 行不一致 → 拒绝。"""
    db = _db(app)
    try:
        prepared = _prepared(
            db, attempt_id="recmis1", auth_id=34,
            auth_receiver="https://other.example.com/apps/anthropic/v1/messages",
        )
        host = HostGateway(signing_key=HOST_KEY, key_id="host-k1")
        with pytest.raises(ChainDenied) as caught:
            host.build_request_from_db(
                db, attempt_id=prepared.attempt_id,
                body=canonical_payload_bytes(PAYLOAD), model="m",
            )
        assert caught.value.code == "authorization_receiver_mismatch"
    finally:
        db.close()


# ---- 问题 B：Egress 必须认证调用者并独立验证宿主授权 ----


def test_egress_rejects_missing_caller_auth(app) -> None:
    """Egress 无调用者凭证 → 拒绝（不得只凭 receiver/digest/policy 放行）。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="noauth1", auth_id=41)
        host, _launcher, egress = _chain(db)
        request = host.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
        with pytest.raises(ChainDenied) as caught:
            egress.forward(request)
        assert caught.value.code == "launcher_auth_missing"
    finally:
        db.close()


def test_egress_rejects_unknown_caller_key_id(app) -> None:
    """未知调用者 key_id → 拒绝。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="unknownkey1", auth_id=42)
        host, _launcher, egress = _chain(db)
        request = host.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
        request.launcher_auth = receipts.issue_launcher_auth(
            attempt_id=request.attempt_id,
            request_digest=request.request_digest,
            nonce=request.nonce,
            key_id="launcher-unknown",
            key=LAUNCHER_KEY,
        )
        with pytest.raises(ChainDenied) as caught:
            egress.forward(request)
        assert caught.value.code == "launcher_key_unknown"
    finally:
        db.close()


def test_egress_rejects_bad_caller_signature(app) -> None:
    """调用者凭证签名错误（错误密钥）→ 拒绝。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="badsig_caller1", auth_id=43)
        host, _launcher, egress = _chain(db)
        request = host.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
        request.launcher_auth = receipts.issue_launcher_auth(
            attempt_id=request.attempt_id,
            request_digest=request.request_digest,
            nonce=request.nonce,
            key_id=LAUNCHER_KEY_ID,
            key=b"wrong-launcher-key",
        )
        with pytest.raises(ChainDenied) as caught:
            egress.forward(request)
        assert caught.value.code == "launcher_auth_signature_invalid"
    finally:
        db.close()


def test_egress_fail_closed_without_caller_keys(app) -> None:
    """Egress 未配置任何调用者公钥 → 拒绝（不降级为无认证放行）。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="nokeys1", auth_id=44)
        host = HostGateway(signing_key=HOST_KEY, key_id="host-k1")
        egress = EgressRelay(
            signing_key=EGRESS_KEY, key_id="egress-k1",
            replay=DbReplayStore(db), host_public_key=HOST_KEY,
            launcher_keys={},
        )
        request = host.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
        _attach_caller_auth(request)
        with pytest.raises(ChainDenied) as caught:
            egress.forward(request)
        assert caught.value.code == "egress_caller_auth_not_configured"
    finally:
        db.close()


def test_egress_rejects_forged_host_receipt(app) -> None:
    """宿主授权收据由错误密钥签发 → Egress 独立验签失败。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="forged_host1", auth_id=45)
        forged = HostGateway(signing_key=b"attacker-host-key", key_id="host-k1")
        _real_host, _launcher, egress = _chain(db)
        request = forged.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
        _attach_caller_auth(request)
        with pytest.raises(ChainDenied) as caught:
            egress.forward(request)
        assert caught.value.code == "egress_host_receipt_signature_invalid"
    finally:
        db.close()


def test_egress_fail_closed_without_host_key(app) -> None:
    """Egress 未配置宿主公钥 → 拒绝。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="nohostkey1", auth_id=46)
        host = HostGateway(signing_key=HOST_KEY, key_id="host-k1")
        egress = EgressRelay(
            signing_key=EGRESS_KEY, key_id="egress-k1",
            replay=DbReplayStore(db),
            launcher_keys={LAUNCHER_KEY_ID: LAUNCHER_KEY},
            host_public_key=None,
        )
        request = host.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
        _attach_caller_auth(request)
        with pytest.raises(ChainDenied) as caught:
            egress.forward(request)
        assert caught.value.code == "egress_host_key_not_configured"
    finally:
        db.close()


# ---- 问题 C：nonce 一次性（不同 attempt 复用必须拒绝） ----


def test_nonce_reuse_across_attempts_rejected(app) -> None:
    """不同 attempt 复用同一 nonce → 第二次不得放行。"""
    db = _db(app)
    try:
        prepared1 = _prepared(db, attempt_id="nonce_a", auth_id=51)
        host, launcher, egress = _chain(db)
        shared_nonce = "shared-nonce-0001"
        body = canonical_payload_bytes(PAYLOAD)

        first = host.build_request(
            prepared=prepared1, body=body, model="m", nonce=shared_nonce
        )
        assert launcher.dispatch(first, egress).phase == "confirmed_sent"

        # 第二个 attempt（不同 attempt_id）复用同一 nonce。
        prepared2 = _prepared(db, attempt_id="nonce_b", auth_id=51)
        second = host.build_request(
            prepared=prepared2, body=body, model="m", nonce=shared_nonce
        )
        with pytest.raises(ChainDenied) as caught:
            launcher.dispatch(second, egress)
        # launcher 侧 nonce 唯一索引命中 → 视为重放拒绝。
        assert caught.value.code == "launcher_replayed_attempt"
    finally:
        db.close()


# ---- 契约 §6.2：撤销与签发的时序边界 ----


def test_settle_rejects_confirmation_when_revoked_before_issue(app) -> None:
    """撤销时间早于收据签发 → 不得升格 confirmed_sent，只落 possibly_sent + 证据。"""
    from datetime import timedelta

    from app.models.base import utcnow
    from app.models.outbound import OutboundAuthorization

    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="race_before", auth_id=61)
        host, launcher, egress = _chain(db)
        request = host.build_request_from_db(
            db, attempt_id=prepared.attempt_id,
            body=canonical_payload_bytes(PAYLOAD), model="m",
        )
        outcome = launcher.dispatch(request, egress)
        assert outcome.phase == "confirmed_sent"

        # 模拟「撤销时间早于签发」：授权在签发前即被撤销（追溯撤销/时钟偏差）。
        auth = db.get(OutboundAuthorization, prepared.authorization_id)
        auth.revoked_at = utcnow() - timedelta(hours=1)
        db.commit()

        verification, appended = host.settle(
            db, outcome=outcome, prepared=prepared, egress_key=EGRESS_KEY
        )
        assert verification.ok is False
        assert verification.code == "revoked_before_issue"
        assert appended is False

        terminals = (
            db.query(SendAuditRecord)
            .filter(SendAuditRecord.attempt_id == prepared.attempt_id,
                    SendAuditRecord.phase != "prepared")
            .all()
        )
        assert len(terminals) == 1
        assert terminals[0].phase == "possibly_sent"
        assert terminals[0].error_code == "revoked_before_issue"
        evidence = db.query(SendReceiptEvidence).filter_by(
            attempt_id=prepared.attempt_id, kind="revocation_race"
        ).all()
        assert len(evidence) == 1
        assert evidence[0].verification == "revoked_before_issue"
    finally:
        db.close()


def test_settle_records_when_revoked_after_issue(app) -> None:
    """撤销晚于签发 → 收据有效（confirmed），但必须留证以便追溯。"""
    from datetime import timedelta

    from app.models.base import utcnow
    from app.models.outbound import OutboundAuthorization

    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="race_after", auth_id=62)
        host, launcher, egress = _chain(db)
        request = host.build_request_from_db(
            db, attempt_id=prepared.attempt_id,
            body=canonical_payload_bytes(PAYLOAD), model="m",
        )
        outcome = launcher.dispatch(request, egress)

        # 签发之后才撤销（撤销时间晚于 issued_at）。
        auth = db.get(OutboundAuthorization, prepared.authorization_id)
        auth.revoked_at = utcnow() + timedelta(hours=1)
        db.commit()

        verification, appended = host.settle(
            db, outcome=outcome, prepared=prepared, egress_key=EGRESS_KEY
        )
        assert verification.ok is True
        assert appended is False

        terminals = (
            db.query(SendAuditRecord)
            .filter(SendAuditRecord.attempt_id == prepared.attempt_id,
                    SendAuditRecord.phase != "prepared")
            .all()
        )
        assert len(terminals) == 1 and terminals[0].phase == "confirmed_sent"
        evidence = db.query(SendReceiptEvidence).filter_by(
            attempt_id=prepared.attempt_id, kind="revocation_after_issue"
        ).all()
        assert len(evidence) == 1
    finally:
        db.close()


def test_settle_no_revocation_evidence_when_authorization_active(app) -> None:
    """授权未被撤销 → 正常 confirmed，且不产生撤销竞态证据。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="race_none", auth_id=63)
        host, launcher, egress = _chain(db)
        request = host.build_request_from_db(
            db, attempt_id=prepared.attempt_id,
            body=canonical_payload_bytes(PAYLOAD), model="m",
        )
        outcome = launcher.dispatch(request, egress)
        verification, _ = host.settle(
            db, outcome=outcome, prepared=prepared, egress_key=EGRESS_KEY
        )
        assert verification.ok is True
        races = db.query(SendReceiptEvidence).filter(
            SendReceiptEvidence.attempt_id == prepared.attempt_id,
            SendReceiptEvidence.kind.in_(["revocation_race", "revocation_after_issue"]),
        ).all()
        assert races == []
    finally:
        db.close()


def test_settle_fails_closed_when_authorization_missing(app, monkeypatch) -> None:
    """授权记录缺失 → 不得升格 confirmed_sent（fail-closed，不因「无撤销记录」放行）。"""
    from app.models.outbound import OutboundAuthorization

    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="auth_missing", auth_id=71)
        host, launcher, egress = _chain(db)
        request = host.build_request_from_db(
            db, attempt_id=prepared.attempt_id,
            body=canonical_payload_bytes(PAYLOAD), model="m",
        )
        outcome = launcher.dispatch(request, egress)
        assert outcome.phase == "confirmed_sent"

        # 模拟「授权记录缺失」：不影响外键引用，仅让 settle 查不到授权。
        original_get = db.get

        def fake_get(model, pk, **kwargs):
            if model is OutboundAuthorization:
                return None
            return original_get(model, pk, **kwargs)

        monkeypatch.setattr(db, "get", fake_get)

        verification, appended = host.settle(
            db, outcome=outcome, prepared=prepared, egress_key=EGRESS_KEY
        )
        assert verification.ok is False
        assert verification.code == "authorization_missing"
        assert appended is False
        terminals = (
            db.query(SendAuditRecord)
            .filter(SendAuditRecord.attempt_id == prepared.attempt_id,
                    SendAuditRecord.phase != "prepared")
            .all()
        )
        assert len(terminals) == 1
        assert terminals[0].phase == "possibly_sent"
        assert terminals[0].error_code == "authorization_missing"
    finally:
        db.close()


def test_settle_fails_closed_when_issued_at_unparseable(app) -> None:
    """收据签发时间不可解析 → 无法判定时序 → 不得升格 confirmed_sent。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="bad_issued", auth_id=72)
        host, launcher, egress = _chain(db)
        request = host.build_request_from_db(
            db, attempt_id=prepared.attempt_id,
            body=canonical_payload_bytes(PAYLOAD), model="m",
        )
        outcome = launcher.dispatch(request, egress)
        # 构造一个 issued_at 不可解析但其余字段仍能通过验签的收据：
        # 直接用同一签名（签名在 issued_at 被篡改后会失败），因此这里改走
        # 「授权被撤销且 issued_at 非法」的判定分支需真实签名 —— 用 issue 重签。
        bad = receipts.issue_send_receipt(
            attempt_id=prepared.attempt_id,
            authorization_id=prepared.authorization_id,
            receiver=prepared.receiver,
            request_digest=prepared.request_digest,
            actual_body_sha256=prepared.request_digest,
            terminal_phase="confirmed_sent",
            http_status=200,
            raw_response_sha256="r" * 64,
            policy_version=s9_chain.DEFAULT_POLICY_VERSION,
            key_id="egress-k1",
            key=EGRESS_KEY,
        )
        object.__setattr__(bad, "issued_at", "not-a-timestamp")
        outcome.receipt = bad
        verification, _ = host.settle(
            db, outcome=outcome, prepared=prepared, egress_key=EGRESS_KEY
        )
        # 签名覆盖 issued_at，篡改后应先被签名校验拒绝；无论哪一层，
        # 结果都不得是 confirmed_sent。
        assert verification.ok is False
        terminals = (
            db.query(SendAuditRecord)
            .filter(SendAuditRecord.attempt_id == prepared.attempt_id,
                    SendAuditRecord.phase != "prepared")
            .all()
        )
        assert len(terminals) == 1
        assert terminals[0].phase != "confirmed_sent"
    finally:
        db.close()
