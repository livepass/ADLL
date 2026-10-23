"""阿里云百炼（Anthropic 兼容 Messages API）AgentAdapter（候选 C，T030）。

- 固定已批准端点；**不使用** Claude Agent SDK / CLI / 模型工具。
- 单次请求、无自动重试、超时；响应解析；usage/cost 三分类。
- 默认 `enabled=False`（生产默认禁止外部 AI 发送，需显式配置且通过隔离核验）。
- **无审批能力**：不持有数据库/审批服务引用，不写 ApprovalEvent。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from ..core.payload import canonical_payload_bytes
from ..models.enums import CancelOutcome
from .base import (
    AdapterCapabilities,
    AgentAdapter,
    BoundaryCheckReport,
    EventSink,
    GenerationRequest,
    GenerationResult,
)


class AdapterDisabled(RuntimeError):
    pass


class AdapterTimeout(RuntimeError):
    pass


class AdapterResponseError(RuntimeError):
    pass


class AdapterCancelled(RuntimeError):
    """worker 被终止；sent 表示终止前是否已写出站请求。"""

    def __init__(self, message: str = "adapter cancelled", *, sent: bool = False) -> None:
        super().__init__(message)
        self.sent = sent


def _urllib_transport(payload: dict, timeout: int) -> dict:
    """真实传输（默认）：单次 POST；禁重定向；禁代理；读取 DASHSCOPE_API_KEY。"""
    endpoint = os.environ.get("ADLL_DASHSCOPE_ENDPOINT", "")
    if not endpoint:
        raise AdapterDisabled("endpoint not configured")
    key = os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        raise AdapterDisabled("DASHSCOPE_API_KEY missing (never logged)")
    data = canonical_payload_bytes(payload)
    req = urllib.request.Request(endpoint, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + key)  # 仅此处使用；不打印
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            if resp.status != 200:
                raise AdapterResponseError(f"http_status:{resp.status}")
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise AdapterResponseError(f"http_error:{exc.code}") from exc
    except TimeoutError as exc:  # noqa: UP041
        raise AdapterTimeout("request timed out") from exc
    except OSError as exc:
        raise AdapterResponseError(type(exc).__name__) from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterResponseError("response_not_json") from exc


class DashscopeAgentAdapter(AgentAdapter):
    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        timeout: int = 30,
        transport=None,
        enabled: bool = False,
        synthetic_transport: bool = False,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout
        self.transport = transport or _urllib_transport
        self.enabled = enabled
        self.synthetic_transport = synthetic_transport

    def generate(
        self, request: GenerationRequest, sink: EventSink | None = None
    ) -> GenerationResult:
        if not self.enabled:
            raise AdapterDisabled("real AI sending disabled (fail-closed)")
        if not isinstance(request.payload, dict):
            raise AdapterResponseError("host-assembled payload required")
        if sink is not None:
            sink.emit({"type": "start"})
        try:
            response = self.transport(request.payload, self.timeout)
        except TimeoutError as exc:  # noqa: UP041
            raise AdapterTimeout("request timed out") from exc
        except (AdapterTimeout, AdapterResponseError, AdapterDisabled):
            raise
        except Exception as exc:  # noqa: BLE001
            raise AdapterResponseError(type(exc).__name__) from exc

        if not isinstance(response, dict):
            raise AdapterResponseError("response_not_object")
        stop_reason = response.get("stop_reason")
        if stop_reason == "max_tokens":
            raise AdapterResponseError("truncated:max_tokens")
        content = response.get("content")
        if not isinstance(content, list):
            raise AdapterResponseError("content_missing")
        text_parts = []
        for block in content:
            if not isinstance(block, dict):
                raise AdapterResponseError("content_block_invalid")
            if block.get("type") == "text":
                value = block.get("text")
                if not isinstance(value, str):
                    raise AdapterResponseError("text_not_string")
                text_parts.append(value)
        text = "".join(text_parts)
        if not text.strip():
            raise AdapterResponseError("empty_content")

        usage = response.get("usage")
        if isinstance(usage, dict) and isinstance(usage.get("input_tokens"), int) and isinstance(
            usage.get("output_tokens"), int
        ):
            usage_value = usage
            usage_basis = "actual"
        else:
            usage_value = {}
            usage_basis = "unavailable"

        if sink is not None:
            sink.emit({"type": "delta", "text": text})
        return GenerationResult(
            text=text,
            citations=[],
            usage=usage_value,
            usage_basis=usage_basis,
            cost={"amount": None, "currency": None, "basis": "unknown"},
            terminal_status="completed",
            tool_call_log=[],  # 候选 C：无工具
        )

    def cancel(self, execution_id: str) -> CancelOutcome:
        return CancelOutcome.NOT_CANCELLED

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            {
                "provider": "dashscope",
                "endpoint": self.endpoint,
                "model": self.model,
                "tools": False,
                "network": True,
                "real_model": True,
                "approval": False,
                "transport": "synthetic" if self.synthetic_transport else "urllib",
            }
        )

    def self_check(self) -> BoundaryCheckReport:
        # 真实传输的 OS 级隔离尚未验证 → fail-closed；合成传输入测试用途
        if self.synthetic_transport:
            return BoundaryCheckReport(ok=True, details={"synthetic": True, "approval": False})
        return BoundaryCheckReport(
            ok=False,
            details={
                "os_isolation": "unverified",
                "approval": False,
                "tools": False,
            },
        )