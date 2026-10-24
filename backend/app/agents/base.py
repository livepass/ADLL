"""AgentAdapter 接口语义（contracts/agent-adapter.md §4）。

接口不绑定具体实现；候选 C（Messages API 直连）与测试 Mock 均实现本接口。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..models.enums import CancelOutcome


@dataclass
class GenerationRequest:
    subset_path: str | None
    requirement_text: str
    feedback_texts: list[str] = field(default_factory=list)
    send_manifest: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    payload: dict[str, Any] | None = None
    execution_id: int | None = None
    # S9-2：审计绑定。attempt_id 来自已持久化 prepared 审计行；
    # request_digest 是该行记录的授权摘要，adapter 不得自行生成替代值。
    attempt_id: str | None = None
    request_digest: str | None = None
    # S9-2 完整绑定：authorization_id 与 receiver 也必须来自 prepared/授权记录，
    # 供 adapter 在发送前做 attempt/authorization/receiver/request_digest 一致性校验。
    authorization_id: int | None = None
    receiver: str | None = None


@dataclass
class GenerationResult:
    text: str
    citations: list[dict[str, Any]]
    usage: dict[str, Any]
    usage_basis: str
    cost: dict[str, Any]
    terminal_status: str
    tool_call_log: list[dict[str, Any]] = field(default_factory=list)
    # 传输事实（不伪造网络状态）：sent/confirmed/transport/response_digest。
    send_evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterCapabilities:
    declares: dict[str, Any]


@dataclass
class BoundaryCheckReport:
    ok: bool
    details: dict[str, Any]


class EventSink(Protocol):
    def emit(self, event: dict[str, Any]) -> None: ...


class AgentAdapter(Protocol):
    def generate(
        self, request: GenerationRequest, sink: EventSink | None = None
    ) -> GenerationResult: ...

    def cancel(self, execution_id: str) -> CancelOutcome: ...

    def capabilities(self) -> AdapterCapabilities: ...

    def self_check(self) -> BoundaryCheckReport: ...