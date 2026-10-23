"""服务端会话：创建 / 查询 / 撤销（仅存 token 哈希）。"""
from __future__ import annotations

from datetime import timedelta

from ..models.base import utcnow
from ..models.session import UserSession
from .tokens import hash_token, new_token


def create_session(db, role, ttl_seconds: int) -> tuple[str, UserSession]:
    raw = new_token()
    csrf = new_token(24)
    session = UserSession(
        token_hash=hash_token(raw),
        csrf_token=csrf,
        role=str(role),
        expires_at=utcnow() + timedelta(seconds=ttl_seconds),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return raw, session


def get_session(db, raw_token: str | None) -> UserSession | None:
    if not raw_token:
        return None
    session = db.query(UserSession).filter_by(token_hash=hash_token(raw_token)).one_or_none()
    if session is None:
        return None
    if session.expires_at <= utcnow():
        return None
    return session


def revoke_session(db, session: UserSession) -> None:
    db.delete(session)
    db.commit()