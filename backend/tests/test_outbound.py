"""出站授权：五项同时满足 + 跨任务/跨基准拒绝 + 审计四类。"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.models import OutboundAuthorization, SendAuditRecord
from app.models.base import utcnow
from app.services import outbound

TASK = 1
BASELINE = 1


def _make(db, **kwargs):
    auth = OutboundAuthorization(
        task_id=kwargs.get("task_id", TASK),
        baseline_id=kwargs.get("baseline_id", BASELINE),
        receiver=kwargs.get("receiver", "dashscope"),
        data_types=kwargs.get("data_types", ["requirement", "source"]),
        send_scope=kwargs.get("send_scope", {"kind": "task", "id": 1}),
        status=kwargs.get("status", "approved"),
        revoked_at=kwargs.get("revoked_at"),
        expires_at=kwargs.get("expires_at"),
    )
    db.add(auth)
    db.commit()
    db.refresh(auth)
    return auth


def _eval(auth, **kw):
    return outbound.evaluate(
        auth,
        task_id=kw.get("task_id", TASK),
        baseline_id=kw.get("baseline_id", BASELINE),
        receiver=kw.get("receiver", "dashscope"),
        data_types=kw.get("data_types", ["requirement"]),
        scope=kw.get("scope", {"kind": "task", "id": 1}),
    )


def test_no_authorization_denied(app) -> None:
    d = _eval(None)
    assert d.allowed is False and d.code == "no_authorization"


def test_pending_denied(app) -> None:
    db = app.state.db.session()
    try:
        assert _eval(_make(db, status="pending")).code == "not_approved"
    finally:
        db.close()


def test_revoked_denied(app) -> None:
    db = app.state.db.session()
    try:
        assert _eval(_make(db, revoked_at=utcnow())).code == "revoked"
    finally:
        db.close()


def test_expired_denied(app) -> None:
    db = app.state.db.session()
    try:
        auth = _make(db, expires_at=utcnow() - timedelta(seconds=1))
        assert _eval(auth).code == "expired"
    finally:
        db.close()


def test_task_mismatch_denied(app) -> None:
    db = app.state.db.session()
    try:
        auth = _make(db, task_id=TASK)
        assert _eval(auth, task_id=TASK + 1).code == "task_mismatch"
    finally:
        db.close()


def test_baseline_mismatch_denied(app) -> None:
    db = app.state.db.session()
    try:
        auth = _make(db, baseline_id=BASELINE)
        assert _eval(auth, baseline_id=BASELINE + 1).code == "baseline_mismatch"
    finally:
        db.close()


def test_receiver_mismatch_denied(app) -> None:
    db = app.state.db.session()
    try:
        assert _eval(_make(db), receiver="other").code == "receiver_mismatch"
    finally:
        db.close()


def test_data_type_not_authorized_denied(app) -> None:
    db = app.state.db.session()
    try:
        auth = _make(db, data_types=["requirement"])
        assert _eval(auth, data_types=["requirement", "source"]).code == "data_type_not_authorized"
    finally:
        db.close()


def test_scope_mismatch_denied(app) -> None:
    db = app.state.db.session()
    try:
        assert _eval(_make(db), scope={"kind": "other"}).code == "scope_mismatch"
    finally:
        db.close()


def test_unverifiable_when_task_baseline_missing(app) -> None:
    db = app.state.db.session()
    try:
        auth = _make(db, task_id=None, baseline_id=None)
        assert _eval(auth).code == "unverifiable"
    finally:
        db.close()


def test_valid_allowed(app) -> None:
    db = app.state.db.session()
    try:
        assert _eval(_make(db), data_types=["requirement", "source"]).allowed is True
    finally:
        db.close()


def test_record_send_binding_mismatch_rejected(app) -> None:
    db = app.state.db.session()
    try:
        auth = _make(db)
        with pytest.raises(PermissionError):
            outbound.record_send(
                db, auth, task_id=TASK + 1, baseline_id=BASELINE,
                execution_id="e", requirement=[], feedback=[], source=[],
            )
    finally:
        db.close()


def test_record_send_four_categories_tool_return_empty(app) -> None:
    db = app.state.db.session()
    try:
        auth = _make(db)
        rec = outbound.record_send(
            db, auth, task_id=TASK, baseline_id=BASELINE,
            execution_id="e1", requirement=["req"], feedback=["fb"], source=[{"p": "a"}],
        )
        manifest = rec.payload_manifest
        assert set(manifest.keys()) == {"requirement", "feedback", "source", "tool_return"}
        assert manifest["tool_return"] == []
        with pytest.raises(Exception):
            db.execute(
                text("UPDATE send_audit_records SET content_digest='x' WHERE id=:i"),
                {"i": rec.id},
            )
            db.commit()
        db.rollback()
    finally:
        db.close()