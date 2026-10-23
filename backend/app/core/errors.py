"""统一错误约定：`{code, message, detail?}`（contracts/api-endpoints.md 通用约定）。

HTTPException 的 detail 若为 dict 则原样作为响应体；否则包装为 {code,message}。
不回传异常对象/调用栈/凭据（FR-042）。
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorResponse(BaseModel):
    code: str
    message: str
    detail: str | None = None


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        content = detail if isinstance(detail, dict) else {
            "code": "http_error",
            "message": str(detail),
        }
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"code": "internal_error", "message": "服务器内部错误", "detail": None},
        )