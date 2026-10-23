"""自动化测试专用 Mock（FR-009：Mock 仅测试替身，不得作为正式业务功能）。"""
from __future__ import annotations

from ..models.enums import CancelOutcome
from .base import (
    AdapterCapabilities,
    AgentAdapter,
    BoundaryCheckReport,
    EventSink,
    GenerationRequest,
    GenerationResult,
)


class MockAgentAdapter(AgentAdapter):
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self._cancelled = False

    def generate(
        self, request: GenerationRequest, sink: EventSink | None = None
    ) -> GenerationResult:
        if self.fail:
            raise RuntimeError("mock adapter failure (synthetic)")
        if sink is not None:
            sink.emit({"type": "start"})
        text = "MOCK_PLAN: " + (request.requirement_text or "")
        if sink is not None:
            sink.emit({"type": "delta", "text": text})
        return GenerationResult(
            text=text,
            citations=[{"path": "mock/example.py", "commit": "0" * 40, "mock": True}],
            usage={"input_tokens": 10, "output_tokens": 5},
            usage_basis="actual",
            cost={
                "amount": None,
                "currency": None,
                "basis": "estimated",
                "method": "mock-estimate",
            },
            terminal_status="completed",
            tool_call_log=[],  # 候选 C：无工具
            send_evidence={
                "transport": "mock",
                "sent": True,
                "confirmed": True,
                "response_digest": __import__("hashlib").sha256(
                    text.encode("utf-8")
                ).hexdigest(),
            },
        )

    def cancel(self, execution_id: str) -> CancelOutcome:
        if self._cancelled:
            return CancelOutcome.ALREADY_FINISHED
        self._cancelled = True
        return CancelOutcome.CANCELLED

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            {
                "mock": True,
                "tools": False,
                "network": False,
                "real_model": False,
                "endpoint": "mock://local",
            }
        )

    def self_check(self) -> BoundaryCheckReport:
        return BoundaryCheckReport(ok=True, details={"mock": True})