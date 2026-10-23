"""发送前强制检查与载荷组装（T028/T029）。

- 五项同时成立：同任务、同基准、同接收方（实际端点）、同实际发送范围、授权 active。
- 实际数据类型**从最终请求计算**（需求/反馈/源码/工具返回），不读取授权记录自证。
- `send_scope` 是显式路径白名单；空 scope 不再表示全部源码。
- 仅使用已授权内容组装请求；工具返回恒空（候选 C）。
- 记录请求摘要、接收方、发送范围；任何超出授权 → 拒绝且零发送。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from . import outbound
from .snapshot import _is_sensitive
from ..core.payload import payload_digest as compute_payload_digest

TOOL_RETURNS: tuple = ()


class OutboundDenied(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class Prepared:
    payload: dict
    payload_manifest: dict
    request_digest: str
    receiver: str
    scope: dict
    data_types: list[str]


def actual_data_types(
    requirement_text: str,
    feedback_texts: list[str],
    source_items: list[dict],
    tool_returns: tuple | list = TOOL_RETURNS,
) -> list[str]:
    """Compute what is really being sent, independent of the authorization record."""
    types: list[str] = []
    if requirement_text and requirement_text.strip():
        types.append("requirement")
    if [text for text in feedback_texts if text and text.strip()]:
        types.append("feedback")
    if source_items:
        types.append("source")
    if tool_returns:
        types.append("tool_return")
    return types


def _compose(requirement_text: str, feedback_texts: list[str], source_items: list[dict]) -> str:
    parts = ["## Requirement", requirement_text]
    if feedback_texts:
        parts.append("## Feedback")
        parts.extend(feedback_texts)
    if source_items:
        parts.append("## Source")
        for item in source_items:
            parts.append(f"### {item['path']}")
            parts.append(item["content"])
    return "\n".join(parts)


def prepare(
    *,
    task,
    auth,
    receiver: str,
    requirement_text: str,
    feedback_texts: list[str],
    source_items: list[dict],
    model: str,
    max_tokens: int = 256,
) -> Prepared:
    actual_types = actual_data_types(requirement_text, feedback_texts, source_items)
    scope = {"paths": sorted({item["path"] for item in source_items})}

    decision = outbound.evaluate(
        auth,
        task_id=task.id,
        baseline_id=task.baseline_id,
        receiver=receiver,
        data_types=actual_types,
        scope=scope,
    )
    if not decision.allowed:
        raise OutboundDenied(decision.code)

    for item in source_items:
        if _is_sensitive(item["path"]):
            raise OutboundDenied("sensitive_source")
        digest = hashlib.sha256(item["content"].encode("utf-8")).hexdigest()
        if digest != item["sha256"]:
            raise OutboundDenied("source_digest_mismatch")

    text = _compose(requirement_text, feedback_texts, source_items)
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "thinking": {"type": "disabled"},
        "stream": False,
        "messages": [{"role": "user", "content": text}],
    }
    manifest = {
        "requirement": [requirement_text] if "requirement" in actual_types else [],
        "feedback": list(feedback_texts) if "feedback" in actual_types else [],
        "source": [{"path": i["path"], "sha256": i["sha256"]} for i in source_items],
        "tool_return": [],
    }
    digest = compute_payload_digest(payload)
    prepared = Prepared(payload, manifest, digest, receiver, scope, actual_types)
    _assert_alignment(prepared, requirement_text, feedback_texts, source_items)
    return prepared


def _assert_alignment(
    prepared: Prepared,
    requirement_text: str,
    feedback_texts: list[str],
    source_items: list[dict],
) -> None:
    """核验实际序列化请求与 payload_manifest 一致，且无额外内容。"""
    expected = _compose(requirement_text, feedback_texts, source_items)
    if prepared.payload["messages"][0]["content"] != expected:
        raise OutboundDenied("manifest_misalignment")
    if prepared.payload_manifest["tool_return"] != []:
        raise OutboundDenied("tool_return_not_empty")
    if prepared.payload_manifest["source"] != [
        {"path": item["path"], "sha256": item["sha256"]} for item in source_items
    ]:
        raise OutboundDenied("manifest_source_mismatch")
    if set(prepared.payload.keys()) != {
        "model",
        "max_tokens",
        "thinking",
        "stream",
        "messages",
    }:
        raise OutboundDenied("payload_extra_keys")
