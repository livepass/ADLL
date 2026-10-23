"""百炼适配器：禁用默认、单次调用、超时/错误/截断、usage/cost、无审批能力。"""
from __future__ import annotations

import pytest

from app.agents.base import GenerationRequest
from app.agents.dashscope import (
    AdapterDisabled,
    AdapterResponseError,
    AdapterTimeout,
    DashscopeAgentAdapter,
)


def _request() -> GenerationRequest:
    return GenerationRequest(
        subset_path=None,
        requirement_text="r",
        payload={
            "model": "m",
            "max_tokens": 256,
            "thinking": {"type": "disabled"},
            "stream": False,
            "messages": [{"role": "user", "content": "x"}],
        },
    )


def _adapter(transport=None, *, enabled=True, synthetic=True) -> DashscopeAgentAdapter:
    return DashscopeAgentAdapter(
        endpoint="https://example.invalid/v1/messages",
        model="m",
        enabled=enabled,
        transport=transport,
        synthetic_transport=synthetic,
    )


def test_disabled_by_default() -> None:
    adapter = DashscopeAgentAdapter(endpoint="e", model="m")
    with pytest.raises(AdapterDisabled):
        adapter.generate(_request())


def test_success_single_call() -> None:
    calls = []

    def transport(payload, timeout):
        calls.append(payload)
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 3, "output_tokens": 2},
        }

    result = _adapter(transport).generate(_request())
    assert result.text == "ok"
    assert result.usage_basis == "actual"
    assert result.cost == {"amount": None, "currency": None, "basis": "unknown"}
    assert result.tool_call_log == []
    assert len(calls) == 1  # 无自动重试


def test_timeout() -> None:
    def transport(payload, timeout):
        raise TimeoutError()

    with pytest.raises(AdapterTimeout):
        _adapter(transport).generate(_request())


def test_transport_error() -> None:
    def transport(payload, timeout):
        raise RuntimeError("boom")

    with pytest.raises(AdapterResponseError):
        _adapter(transport).generate(_request())


def test_truncated() -> None:
    def transport(payload, timeout):
        return {"stop_reason": "max_tokens", "content": [{"type": "text", "text": "x"}]}

    with pytest.raises(AdapterResponseError) as exc:
        _adapter(transport).generate(_request())
    assert "truncated" in str(exc.value)


def test_empty_and_invalid_text() -> None:
    def empty(payload, timeout):
        return {"stop_reason": "end_turn", "content": []}

    with pytest.raises(AdapterResponseError):
        _adapter(empty).generate(_request())

    def bad_text(payload, timeout):
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": 123}]}

    with pytest.raises(AdapterResponseError):
        _adapter(bad_text).generate(_request())


def test_no_approval_capability() -> None:
    adapter = _adapter(lambda payload, timeout: {})
    declares = adapter.capabilities().declares
    assert declares["approval"] is False
    assert declares["tools"] is False
    assert not hasattr(adapter, "approve")
    assert not hasattr(adapter, "approval")


def test_self_check_isolation_fail_closed() -> None:
    real = DashscopeAgentAdapter(
        endpoint="e",
        model="m",
        enabled=True,
        transport=lambda payload, timeout: {},
        synthetic_transport=False,
    )
    assert real.self_check().ok is False
    assert _adapter(lambda payload, timeout: {}).self_check().ok is True