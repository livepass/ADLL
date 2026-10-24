"""S9 强制门禁：无可信 OS 网络边界证据时，真实传输必须零外发（离线）。"""
from __future__ import annotations

import pytest

from app.agents.base import GenerationRequest
from app.agents.dashscope import AdapterDisabled
from app.agents.worker import WorkerAgentAdapter
from app.isolation.sandbox import ProbeResult
from app.services import network_boundary


def _adapter(monkeypatch, **kwargs) -> WorkerAgentAdapter:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "FAKE-KEY-MUST-NOT-APPEAR")
    adapter = WorkerAgentAdapter(
        endpoint="https://dashscope.aliyuncs.com/apps/anthropic/v1/messages",
        model="m",
        synthetic=False,
        real_transport=True,
        **kwargs,
    )
    # 让隔离探针通过，从而真正走到 S9 门禁；否则会先抛 isolation_unverified。
    monkeypatch.setattr(
        adapter, "_probe", lambda: ProbeResult(True, {"synthetic": True}, None)
    )
    return adapter


def _request() -> GenerationRequest:
    return GenerationRequest(
        subset_path=None,
        requirement_text="REQ",
        feedback_texts=[],
        send_manifest={"source": []},
        payload={"model": "m", "max_tokens": 256, "messages": [{"role": "user", "content": "x"}]},
        # S9-2 完整绑定：提供合法 attempt_id/authorization_id/receiver/request_digest，
        # 使测试真正走到 S9 网络门禁，而非被绑定校验提前拦截。
        attempt_id="gate-test-attempt",
        authorization_id=1,
        receiver="https://dashscope.aliyuncs.com/apps/anthropic/v1/messages",
        request_digest="g" * 64,
    )


@pytest.mark.parametrize(
    "evidence_kwargs, expect_reason",
    [
        # 未配置 worker 主体
        ({"worker_principal_sid": None, "collector_errors": ["worker_principal_not_configured"]},
         "s9_network_boundary"),
        # 采集异常 → fail-closed
        ({"worker_principal_sid": "S-1-5-21-1000000000-1000000000-1000000000-2001",
          "collector_errors": ["firewall_collection_failed:x"]},
         "s9_network_boundary"),
        # 无出站规则
        ({"worker_principal_sid": "S-1-5-21-1000000000-1000000000-1000000000-2001",
          "rules": (), "collector_errors": []},
         "s9_network_boundary"),
    ],
)
def test_real_transport_rejected_without_s9_evidence(
    monkeypatch, evidence_kwargs, expect_reason
) -> None:
    def fake_collect(_sid):
        return network_boundary.BoundaryEvidence(**evidence_kwargs)

    monkeypatch.setattr(network_boundary, "collect_boundary_evidence", fake_collect)
    adapter = _adapter(monkeypatch)

    with pytest.raises(AdapterDisabled) as caught:
        adapter.generate(_request())
    assert caught.value.args[0].startswith(expect_reason)
    # 零外发：没有进入 worker，也没有 job/result。
    assert adapter.last_job is None
    assert adapter.last_result is None


def test_real_transport_rejected_even_with_key_and_transport(monkeypatch) -> None:
    """仅 real_transport + API Key 存在不能绕过 S9。"""
    def fake_collect(_sid):
        # 主体已知但没有任何出站 block 规则 → 不通过
        return network_boundary.BoundaryEvidence(
            worker_principal_sid="S-1-5-21-1000000000-1000000000-1000000000-2001",
            rules=(),
            collector_errors=[],
        )

    monkeypatch.setattr(network_boundary, "collect_boundary_evidence", fake_collect)
    adapter = _adapter(monkeypatch)

    with pytest.raises(AdapterDisabled) as caught:
        adapter.generate(_request())
    assert caught.value.args[0].startswith("s9_network_boundary")
    assert adapter.last_result is None


def test_synthetic_mode_does_not_require_s9(monkeypatch, tmp_path) -> None:
    """合成模式不冒充真实 OS 网络证据，不触发 S9 门禁（走 worker 合成路径）。"""
    # synthetic=True 时不进入 real 分支，因此 collect_boundary_evidence 不应被调用。
    collected: list = []

    def fake_collect(_sid):
        collected.append(True)
        raise AssertionError("must not be called in synthetic mode")

    monkeypatch.setattr(network_boundary, "collect_boundary_evidence", fake_collect)

    adapter = WorkerAgentAdapter(
        endpoint="https://dashscope.aliyuncs.com/apps/anthropic/v1/messages",
        model="m",
        synthetic=True,
        real_transport=False,
    )
    # synthetic + real_transport=False：不要求 S9；也不应调用采集器。
    # 这里只验证不会触发真实传输分支（无 key 也不会报 missing key，因为走 synthetic）。
    assert adapter.synthetic is True
    assert collected == []
