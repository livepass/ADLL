"""口令校验（常量时间比较；凭据由环境注入，不落库/不落日志）。"""
from __future__ import annotations

import hmac


def verify_password(supplied: str | None, expected: str | None) -> bool:
    if not supplied or not expected:
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))