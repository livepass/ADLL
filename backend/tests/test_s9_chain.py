"""S9-3A 合成链路测试：Host → Launcher → Egress → Synthetic Provider → 收据 → 审计。

全部离线：不创建 VM、不联网、不读真实 Key、不调用百炼。
Synthetic Provider 只验证链路结构与证据传递，不构成生产验收。
"""
from __future__ import annotations

import hashlib

import pytest

from app.core.payload import canonical_payload_bytes
from app.models.outbound import SendAuditRecord, SendReceiptEvidence
from app.services import s9_chain
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
RECEIVER = "https://dashscope.aliyuncs.com/apps/anthropic/v1/messages"
PAYLOAD = {
    "model": "m",
    "max_tokens": 64,
    "stream": False,
    "messages": [{"role": "user", "content": "SYNTHETIC-REQ"}],
}


def _db(app):
    return app.state.db.session()


def _prepared(db, *, attempt_id="chain1", auth_id=1, digest=None):
    from app.models.outbound import OutboundAuthorization

    digest = digest or hashlib.sha256(canonical_payload_bytes(PAYLOAD)).hexdigest()
    if db.get(OutboundAuthorization, auth_id) is None:
        db.add(
            OutboundAuthorization(
                id=auth_id, task_id=1, baseline_id=1, receiver=RECEIVER,
                data_types=["requirement"], send_scope={"paths": ["a.txt"]},
                status="approved",
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
    launcher = Launcher(host_public_key=HOST_KEY, replay=DbReplayStore(db))
    egress = EgressRelay(
        signing_key=EGRESS_KEY, key_id="egress-k1",
        provider=provider or SyntheticProvider(), replay=DbReplayStore(db),
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


def test_egress_replay_rejected(app) -> None:
    """出口防重放：绕过 launcher 直接二次转发同一 attempt → 拒绝。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="replay2")
        host, _launcher, egress = _chain(db)
        request = host.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
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


def test_process_transport_end_to_end(app) -> None:
    """独立子进程 Egress：跨进程传递字节与收据，签名与摘要仍可验证。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="proc1")
        host = HostGateway(signing_key=HOST_KEY, key_id="host-k1")
        launcher = Launcher(
            host_public_key=HOST_KEY, replay=DbReplayStore(db)
        )
        transport = s9_chain.ProcessTransport(
            database_url=app.state.db.url,
            egress_signing_key=EGRESS_KEY,
            egress_key_id="egress-k1",
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


def test_process_transport_replay_rejected(app) -> None:
    """跨进程防重放：同一 attempt 第二次经子进程转发被 replay store 拒绝。"""
    db = _db(app)
    try:
        prepared = _prepared(db, attempt_id="proc_replay")
        host = HostGateway(signing_key=HOST_KEY, key_id="host-k1")
        launcher = Launcher(host_public_key=HOST_KEY, replay=DbReplayStore(db))
        transport = s9_chain.ProcessTransport(
            database_url=app.state.db.url,
            egress_signing_key=EGRESS_KEY,
            egress_key_id="egress-k1",
        )
        request = host.build_request(
            prepared=prepared, body=canonical_payload_bytes(PAYLOAD), model="m"
        )
        first = launcher.dispatch(request, transport)
        assert first.phase == "confirmed_sent"

        # 新 launcher 实例（模拟另一进程），replay 仍命中数据库 → 拒绝。
        db2 = app.state.db.session()
        try:
            launcher2 = Launcher(host_public_key=HOST_KEY, replay=DbReplayStore(db2))
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
