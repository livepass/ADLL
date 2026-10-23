"""认证接口：登录 / 登出 / 当前身份。

- 登录：校验环境注入的口令（常量时间），成功后由服务端创建会话并以 HttpOnly Cookie 下发；
  同时返回 CSRF Token（供状态变更请求的 `X-CSRF-Token` 头）。
- 不以 localhost / CORS / 前端标记作为身份。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ..models.enums import SessionRole
from ..models.session import UserSession
from ..security.deps import COOKIE_NAME, get_current_session
from ..security.password import verify_password
from ..security.sessions import create_session, revoke_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    password: str


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict:
    settings = request.app.state.settings
    if not settings.admin_password:
        raise HTTPException(
            status_code=503,
            detail={"code": "auth_unavailable", "message": "未配置认证凭据（fail-closed）"},
        )
    if not verify_password(body.password, settings.admin_password):
        raise HTTPException(
            status_code=401, detail={"code": "invalid_credentials", "message": "凭据无效"}
        )
    db = request.app.state.db.session()
    try:
        raw, session = create_session(db, SessionRole.USER, settings.session_ttl_seconds)
        response.set_cookie(
            COOKIE_NAME,
            raw,
            httponly=True,
            samesite="strict",
            secure=settings.cookie_secure,
            max_age=settings.session_ttl_seconds,
            path="/",
        )
        return {"role": session.role, "csrf_token": session.csrf_token}
    finally:
        db.close()


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    session: UserSession = Depends(get_current_session),
) -> dict:
    db = request.app.state.db.session()
    try:
        current = db.get(UserSession, session.id)
        if current is not None:
            revoke_session(db, current)
    finally:
        db.close()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(session: UserSession = Depends(get_current_session)) -> dict:
    # CSRF Token 为同步器令牌：仅返回给已认证的同源会话（跨站脚本无法读取响应）。
    return {
        "role": session.role,
        "expires_at": session.expires_at.isoformat(),
        "csrf_token": session.csrf_token,
    }