"""数据库约束、迁移前建表与 append-only 触发器验证。"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models import IdempotencyRecord, OutboundAuthorization, SendAuditRecord, UserSession
from app.models.base import utcnow


def _session(db):
    return db.session()


def test_foreign_keys_enabled(app) -> None:
    with app.state.db.engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_unique_session_token_hash(app) -> None:
    db = _session(app.state.db)
    try:
        expires = utcnow() + timedelta(hours=1)
        db.add(UserSession(token_hash="a" * 64, csrf_token="c", role="user", expires_at=expires))
        db.commit()
        db.add(UserSession(token_hash="a" * 64, csrf_token="c2", role="user", expires_at=expires))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_unique_idempotency_key(app) -> None:
    db = _session(app.state.db)
    try:
        db.add(IdempotencyRecord(key="k", request_hash="h", state="pending"))
        db.commit()
        db.add(IdempotencyRecord(key="k", request_hash="h2", state="pending"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_foreign_key_enforced_on_audit(app) -> None:
    db = _session(app.state.db)
    try:
        db.add(
            SendAuditRecord(
                authorization_id=9999, payload_manifest={}, content_digest="d"
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_append_only_trigger(app) -> None:
    db = _session(app.state.db)
    try:
        auth = OutboundAuthorization(
            receiver="dashscope", data_types=["requirement"], send_scope={"k": 1},
            status="approved",
        )
        db.add(auth)
        db.commit()
        db.refresh(auth)
        rec = SendAuditRecord(
            authorization_id=auth.id, payload_manifest={"requirement": []}, content_digest="d"
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        with pytest.raises(Exception):
            db.execute(
                text("UPDATE send_audit_records SET content_digest='x' WHERE id=:i"),
                {"i": rec.id},
            )
            db.commit()
        db.rollback()
        with pytest.raises(Exception):
            db.execute(
                text("DELETE FROM send_audit_records WHERE id=:i"), {"i": rec.id}
            )
            db.commit()
        db.rollback()
    finally:
        db.close()