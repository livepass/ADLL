#!/usr/bin/env python3
"""
DRAFT — Messages API Smoke Test 脚本草案（阿里云百炼，Anthropic 兼容）—— 安全修复版
=====================================================================================
性质：静态审查用草案。**未经人工批准不得运行**（授权门 SMOKE_TEST_AUTHORIZED）。

对应 [fv1-messages-api-smoke-plan.md](./fv1-messages-api-smoke-plan.md)：
  - 供应商/接收方：阿里云百炼，Base URL `https://dashscope.aliyuncs.com/apps/anthropic`
  - 端点：`/v1/messages`（POST）
  - 模型：`qwen3.7-flash-2026-07-15`
  - 固定参数：max_tokens=256、thinking={"type":"disabled"}、stream=false、timeout=30、
    不配置 tools、不启用自动重试
  - 唯一提示词：`请只输出：ADLL_SMOKE_OK`（不含真实仓库/快照/路径/PII）

安全修复点（2026-10-19）：
  1. 禁止自动 HTTP 重定向：用 `_NoRedirect` 覆盖默认 HTTPRedirectHandler，任何 3xx 抛
     HTTPError → 停止，绝不向 Location 转发（尤其不转发 Authorization 头）。
  2. 禁止自动代理：自定义 opener 显式 `ProxyHandler({})`，直连固定 HTTPS 接收方。
  3. 最多一次实际 HTTP POST：`_post()` 单次守卫（哨兵计数），二次调用即抛错；无循环/重试。
  4. 响应结构校验：content/stop_reason/usage 必查；`stop_reason="max_tokens"`、正文
     为空或 strip 后 ≠ `ADLL_SMOKE_OK` 一律 FAIL。
  5. 安全错误处理：JSON 解析失败/异常类型/结构不符均安全返回，不打印 Authorization/Key。
  6. 响应读取限长：`MAX_RESPONSE_BYTES` 封顶，超出即 FAIL，杜绝无界内存占用。
  7. request-id 优先读响应头；无头时回退检查响应体 `id`，并如实标注实际来源字段。
  8. 不打印/不持久化 Authorization 头、API Key 或任何含凭据对象。
  9. 保留授权门、合成提示词、模型、max_tokens=256、thinking=disabled、stream=false、timeout=30。

安全说明：
  - 仅用 Python 标准库（urllib/json/os/sys），不 import/安装任何第三方依赖；
  - 不主动读取 API Key：仅在授权门通过、真正发请求前从环境变量 `DASHSCOPE_API_KEY`
    读取，且绝不打印/写入日志；任何输出均不含 Key 明文；
  - 默认（未设授权门）直接拒绝执行，不产生任何网络请求。

警告：本文件是草案，不得在方案 S1–S6 全部签署前运行。
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = "https://dashscope.aliyuncs.com/apps/anthropic"
ENDPOINT = BASE_URL + "/v1/messages"
MODEL = "qwen3.7-flash-2026-07-15"
PROMPT = "请只输出：ADLL_SMOKE_OK"
EXPECTED_TEXT = "ADLL_SMOKE_OK"
MAX_TOKENS = 256
TIMEOUT_S = 30
MAX_RESPONSE_BYTES = 1_000_000  # 1 MiB 封顶，超出即 FAIL

# 哨兵：最多一次实际 HTTP POST
_POST_SENT = {"count": 0}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁止自动重定向：任何 3xx 抛 HTTPError，绝不向 Location 发起后续请求。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def _make_opener():
    """返回禁用重定向 + 禁用代理（直连）的 opener。"""
    return urllib.request.build_opener(_NoRedirect(), urllib.request.ProxyHandler({}))


def _authorized() -> bool:
    return os.environ.get("SMOKE_TEST_AUTHORIZED") == "1"


def _post(opener, req):
    """单次 POST 守卫：全局只允许一次，二次调用抛错（无循环/重试）。"""
    if _POST_SENT["count"] > 0:
        raise RuntimeError("at most one HTTP POST allowed (no retry/loop)")
    _POST_SENT["count"] = 1
    return opener.open(req, timeout=TIMEOUT_S)


def _validate_payload(payload, expected=EXPECTED_TEXT):
    """结构校验。返回 (verdict, detail)；verdict ∈ {"PASS","FAIL"}。

    要求：stop_reason == "end_turn"（无工具、无自定义停止序列）；usage 含非负整数
    input_tokens/output_tokens；content 文本块 text 为 str；正文 strip 后 == expected。
    本函数不接触网络、不含凭据。
    """
    if not isinstance(payload, dict):
        return ("FAIL", "payload_not_json_object")
    content = payload.get("content")
    if not isinstance(content, list) or not content:
        return ("FAIL", "content_missing_or_empty")
    parts = []
    for block in content:
        if not isinstance(block, dict):
            return ("FAIL", "content_block_not_object")
        if block.get("type") != "text":
            continue
        t = block.get("text")
        if not isinstance(t, str):
            return ("FAIL", "text_not_string")
        parts.append(t)
    text = "".join(parts)
    if payload.get("stop_reason") != "end_turn":
        return ("FAIL", "stop_reason_not_end_turn")
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return ("FAIL", "usage_missing_or_invalid")
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if (
        isinstance(input_tokens, bool)
        or isinstance(output_tokens, bool)
        or not isinstance(input_tokens, int)
        or not isinstance(output_tokens, int)
        or input_tokens < 0
        or output_tokens < 0
    ):
        return ("FAIL", "usage_tokens_invalid")
    if text.strip() != expected:
        return ("FAIL", "content_not_equal_expected")
    return ("PASS", {"stop_reason": payload.get("stop_reason"), "usage": usage})


def main() -> int:
    if not _authorized():
        print("REFUSED: smoke test NOT authorized.")
        print("(set SMOKE_TEST_AUTHORIZED=1 only after plan S1-S6 are all human-signed)")
        return 2

    key = os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        print("MISSING: DASHSCOPE_API_KEY not set (value is never printed).")
        return 2

    body = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "thinking": {"type": "disabled"},
        "stream": False,
        # 不配置 "tools"：零工具
        "messages": [{"role": "user", "content": PROMPT}],
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": "Bearer " + key,  # 仅此处使用；绝不打印/持久化
            "Content-Type": "application/json",
        },
    )

    opener = _make_opener()
    try:
        resp = _post(opener, req)
    except urllib.error.HTTPError as e:
        print("HTTPError status =", e.code)  # 含 3xx（重定向被拦截）；不打印 Key
        return 1
    except urllib.error.URLError as e:
        print("URLError reason_type =", type(e.reason).__name__)
        return 1
    except Exception as e:  # noqa: BLE001 — 仅打印异常类型，不含凭据
        print("REQUEST_ERROR", type(e).__name__)
        return 1

    # 成功状态要求 HTTP 200（3xx 已被拦截；其余非 200 → 非零退出）
    status = getattr(resp, "status", None)
    if status is None:
        try:
            status = resp.getcode()
        except Exception:  # noqa: BLE001
            status = None
    if status != 200:
        print("HTTP status != 200:", status)
        return 1

    try:
        # request-id 直接经响应头大小写不敏感查找；缺失再回退响应体 id
        request_id = resp.headers.get("x-request-id") or resp.headers.get("request-id")
        rid_source = "header" if request_id else "absent"

        chunks = []
        total = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                print("RESPONSE_TOO_LARGE")
                return 3
            chunks.append(chunk)
        raw = b"".join(chunks).decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001 — 读取异常 → 非零退出
        print("RESPONSE_READ_ERROR", type(e).__name__)
        return 1
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print("RESPONSE_NOT_JSON")
        return 1

    if not isinstance(payload, dict):
        print("RESPONSE_NOT_OBJECT")
        return 1

    # request-id 头缺失时回退响应体 id，并如实标注来源
    if not request_id:
        body_id = payload.get("id")
        if body_id:
            request_id = body_id
            rid_source = "body.id"

    verdict, detail = _validate_payload(payload)
    print("request_id =", request_id, "(source = %s)" % rid_source)
    print("usage =", json.dumps(payload.get("usage", {}), ensure_ascii=False))
    print("stop_reason =", payload.get("stop_reason"))
    print("verdict =", verdict, "detail =", detail)
    return 0 if verdict == "PASS" else 3


if __name__ == "__main__":
    sys.exit(main())