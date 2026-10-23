"""AgentAdapter Mock：成功/失败/取消；工厂 fail-closed（不得以 Mock 冒充正式）。"""
from __future__ import annotations

import pytest

from app.agents.base import GenerationRequest
from app.agents.factory import NoRealAdapterAvailable, get_adapter
from app.agents.mock import MockAgentAdapter
from app.models.enums import CancelOutcome
from tests.helpers import make_settings


def test_mock_generate_success() -> None:
    adapter = MockAgentAdapter()
    events = []

    class Sink:
        def emit(self, event):
            events.append(event)

    result = adapter.generate(
        GenerationRequest(subset_path=None, requirement_text="需求X"), sink=Sink()
    )
    assert result.text == "MOCK_PLAN: 需求X"
    assert result.tool_call_log == []  # 候选 C 无工具
    assert result.usage["input_tokens"] == 10
    assert result.cost["basis"] == "estimated"
    assert any(e["type"] == "delta" for e in events)


def test_mock_failure_raises() -> None:
    adapter = MockAgentAdapter(fail=True)
    with pytest.raises(RuntimeError):
        adapter.generate(GenerationRequest(subset_path=None, requirement_text="x"))


def test_mock_cancel_semantics() -> None:
    adapter = MockAgentAdapter()
    assert adapter.cancel("e1") == CancelOutcome.CANCELLED
    assert adapter.cancel("e1") == CancelOutcome.ALREADY_FINISHED


def test_factory_testing_returns_mock() -> None:
    adapter = get_adapter(make_settings("sqlite://", testing=True))
    assert isinstance(adapter, MockAgentAdapter)


def test_factory_production_fail_closed() -> None:
    with pytest.raises(NoRealAdapterAvailable):
        get_adapter(make_settings("sqlite://", testing=False))


def test_mock_via_http(client, auth) -> None:
    resp = client.post("/_test/agent-generate", json={"requirement_text": "需求Y"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"].startswith("MOCK_PLAN:")
    assert body["tool_call_log"] == []
    assert body["terminal_status"] == "completed"