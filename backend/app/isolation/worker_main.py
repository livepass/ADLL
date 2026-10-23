"""受限生成 worker（独立进程，仅标准库）。

- 只读取父进程写入 sandbox 的 job JSON；不访问原仓库、审批 DB、用户目录。
- 出站策略：仅精确允许的 Messages 端点；禁代理、禁重定向、单次请求。
- 真实传输必须显式 `ADLL_WORKER_REAL_TRANSPORT=1`；否则 fail-closed。
- 合成模式仅用于离线测试，结果明确标记 synthetic，不冒充真实服务商。
- 不打印/持久化 API Key、Authorization 头或响应正文。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

MAX_RESPONSE_BYTES = 1_000_000
ALLOWED_ENDPOINTS = {
    "https://dashscope.aliyuncs.com/apps/anthropic/v1/messages",
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(
            req.full_url, code, "redirect refused", headers, fp
        )


def _opener() -> urllib.request.OpenerDirector:
    # 显式空 ProxyHandler：不使用父进程/系统代理；禁自动重定向。
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def body_digest_error(job: dict, body: bytes) -> str | None:
    """Check the bytes about to be sent against the audited request digest.

    The parent records `request_digest` in the send audit; the worker recomputes
    it here so an authorized channel and the audit row refer to the same bytes.
    Returns an error code, or None when they match.
    """
    expected = job.get("request_digest")
    if not isinstance(expected, str) or not expected:
        return "request_digest_missing"
    actual = hashlib.sha256(body).hexdigest()
    if actual != expected:
        return "body_digest_mismatch"
    return None


def _real_call(job: dict) -> dict:
    if os.environ.get("ADLL_WORKER_REAL_TRANSPORT") != "1":
        return {"ok": False, "error": "real_transport_disabled"}
    endpoint = job.get("endpoint")
    if endpoint not in ALLOWED_ENDPOINTS:
        return {"ok": False, "error": "endpoint_not_allowed"}
    key = os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        return {"ok": False, "error": "credential_missing"}
    payload = job.get("payload")
    if not isinstance(payload, dict):
        return {"ok": False, "error": "payload_invalid"}
    body_file = job.get("body_file")
    if body_file:
        try:
            body = Path(body_file).read_bytes()
        except OSError:
            return {"ok": False, "error": "body_file_unreadable"}
    else:
        body = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    digest_error = body_digest_error(job, body)
    if digest_error is not None:
        # 摘要不符 → 零发送：不能把与审计不一致的字节发出去。
        return {"ok": False, "error": digest_error}
    # 发送前落一个标记：父进程终止 worker 后据此如实区分是否已发出。
    work_dir = Path(job.get("work_dir") or Path(sys.argv[1]).parent)
    marker = work_dir / "sent.marker"
    marker.write_text("sent", encoding="utf-8")
    request = urllib.request.Request(endpoint, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", "Bearer " + key)  # 仅用于请求；不写日志
    try:
        with _opener().open(request, timeout=int(job.get("timeout", 30))) as response:
            if response.status != 200:
                return {"ok": False, "error": f"http_status:{response.status}"}
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"http_error:{exc.code}"}
    except (TimeoutError, OSError) as exc:
        return {"ok": False, "error": type(exc).__name__}
    if len(raw) > MAX_RESPONSE_BYTES:
        return {"ok": False, "error": "response_too_large"}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "error": "response_not_json"}
    return {"ok": True, "provider": "dashscope", "response": parsed}


def _synthetic_call(job: dict) -> dict:
    requirement = str(job.get("requirement", ""))
    return {
        "ok": True,
        "provider": "synthetic_worker",
        "response": {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "SYNTHETIC_WORKER_PLAN: " + requirement}],
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    }


def _phase(name: str) -> None:
    """Write a content-free progress marker to the parent-captured stderr."""
    try:
        if sys.stderr is not None:
            sys.stderr.write(f"adll_worker_phase={name}\n")
            sys.stderr.flush()
    except (OSError, ValueError):
        # A closed/redirected stderr must never mask the real worker result.
        return


def main() -> int:
    _phase("start")
    if len(sys.argv) != 3:
        _phase("bad_arguments")
        return 2
    _phase("read_job")
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    mode = job.get("mode", "real")
    _phase(f"call:{mode}")
    if mode == "synthetic" and job.get("synthetic_allowed") is True:
        result = _synthetic_call(job)
    elif mode == "real":
        result = _real_call(job)
    else:
        result = {"ok": False, "error": "mode_not_allowed"}
    _phase("write_result")
    Path(sys.argv[2]).write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )
    _phase("done")
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())