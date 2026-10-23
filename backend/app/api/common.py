"""API 公共工具：幂等包装 + 错误抛出。"""
from __future__ import annotations

import json

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from ..services import idempotency


def idempotent(request: Request, db, payload_obj, handler) -> JSONResponse:
    key = request.headers.get("Idempotency-Key")
    payload = json.dumps(
        payload_obj, sort_keys=True, ensure_ascii=False, default=str
    ).encode("utf-8")
    status, body, replayed = idempotency.execute(
        db, key, f"{request.method} {request.url.path}", payload, handler
    )
    content = dict(body)
    if replayed:
        content.setdefault("replayed", True)
    return JSONResponse(status_code=status, content=content)


def http_error(status: int, code: str, message: str) -> None:
    raise HTTPException(status_code=status, detail={"code": code, "message": message})