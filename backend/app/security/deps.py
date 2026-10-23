"""认证/CSRF 依赖（服务端强制；不以 localhost/CORS/前端标记作为身份）。

- `get_current_session`：无有效会话 → 401（回环地址不豁免）。
- `require_user_role`：非 `role=user`（如 agent 主体）→ 403。
- `require_user_action`：状态变更接口额外强制 `X-CSRF-Token`。
"""
from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request

from ..models.enums import SessionRole
from ..models.session import UserSession
from .sessions import get_session

COOKIE_NAME = "adll_session"
ANONYMOUS_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_db(request: Request):
    db = request.app.state.db.session()
    try:
        yield db
    finally:
        db.close()


def get_current_session(request: Request, db=Depends(get_db)) -> UserSession:
    raw = request.cookies.get(COOKIE_NAME)
    session = get_session(db, raw)
    if session is None:
        raise HTTPException(
            status_code=401, detail={"code": "unauthenticated", "message": "需要登录会话"}
        )
    return session


def require_user_role(session: UserSession = Depends(get_current_session)) -> UserSession:
    if session.role != SessionRole.USER.value:
        raise HTTPException(
            status_code=403, detail={"code": "forbidden", "message": "需要用户主体（role=user）"}
        )
    return session


def require_user_action(
    request: Request, session: UserSession = Depends(require_user_role)
) -> UserSession:
    if request.method not in ANONYMOUS_METHODS:
        header = request.headers.get("X-CSRF-Token")
        if not header or not hmac.compare_digest(header, session.csrf_token):
            raise HTTPException(
                status_code=403, detail={"code": "csrf_failed", "message": "CSRF 校验失败"}
            )
    return session