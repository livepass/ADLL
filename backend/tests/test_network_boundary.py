"""S9：OS 级网络边界的诚实评估（离线，不读写真实防火墙）。

这些用例锁定“什么不算证据”：应用端点检查、TEST-NET 超时、受限令牌 DACL
都不能让探针判通过；只有绑定到 Worker 主体的出站 block 规则 + 同主体被拒绝
观测 + 允许通道摘要一致，才允许 `verified`。
"""
from __future__ import annotations

import hashlib

from app.isolation.worker_main import body_digest_error
from app.services.network_boundary import (
    BoundaryEvidence,
    FirewallRuleEvidence,
    evaluate,
)

# 合成 SID 占位（非真实账户，仅用于区分 Worker 主体与“其他主体”）。
WORKER = "S-1-5-21-1000000000-1000000000-1000000000-2001"
OTHER = "S-1-5-21-1000000000-1000000000-1000000000-2002"


def _block_rule(sid: str = WORKER, action: str = "block") -> FirewallRuleEvidence:
    return FirewallRuleEvidence(
        name="adll_worker_outbound_block",
        direction="outbound",
        action=action,
        principal_sids=(sid,),
    )


def test_missing_worker_principal_is_not_configured() -> None:
    result = evaluate(BoundaryEvidence(worker_principal_sid=None, rules=()))
    assert result.status == "not_configured"
    assert result.passed is False
    assert "worker_principal_unknown" in result.reasons


def test_rules_for_another_principal_do_not_count() -> None:
    """本机存在 codex_sandbox_offline_block_*（SID …-1018），但不覆盖 ADLLTest。"""
    result = evaluate(
        BoundaryEvidence(worker_principal_sid=WORKER, rules=(_block_rule(OTHER),))
    )
    assert result.status == "not_configured"
    assert result.passed is False
    assert "no_outbound_rule_for_worker" in result.reasons


def test_application_and_timeout_checks_are_not_network_evidence() -> None:
    result = evaluate(
        BoundaryEvidence(
            worker_principal_sid=WORKER,
            rules=(),
            app_endpoint_check=True,
            test_net_timeout=True,
            restricted_token_dacl_check=True,
        )
    )
    assert result.status == "not_configured"
    assert result.passed is False
    assert "app_endpoint_check_is_not_network_control" in result.ignored_observations
    assert "test_net_timeout_is_ambiguous" in result.ignored_observations
    assert (
        "restricted_token_dacl_check_is_not_network_policy"
        in result.ignored_observations
    )


def test_rule_without_observed_denial_is_not_passed() -> None:
    result = evaluate(
        BoundaryEvidence(
            worker_principal_sid=WORKER,
            rules=(_block_rule(),),
            observed_denial=False,
            allowed_channel_digest_match=True,
        )
    )
    assert result.status == "rule_present_unverified"
    assert result.passed is False
    assert "no_observed_denial" in result.reasons


def test_denial_without_digest_match_is_unverified() -> None:
    result = evaluate(
        BoundaryEvidence(
            worker_principal_sid=WORKER,
            rules=(_block_rule(),),
            observed_denial=True,
            allowed_channel_digest_match=False,
        )
    )
    assert result.status == "unverified"
    assert result.passed is False
    assert "allowed_channel_digest_mismatch" in result.reasons


def test_allow_rule_alone_does_not_pass() -> None:
    result = evaluate(
        BoundaryEvidence(
            worker_principal_sid=WORKER,
            rules=(_block_rule(action="allow"),),
            observed_denial=True,
            allowed_channel_digest_match=True,
        )
    )
    assert result.passed is False
    assert "no_block_rule_for_worker" in result.reasons


def test_full_evidence_passes() -> None:
    result = evaluate(
        BoundaryEvidence(
            worker_principal_sid=WORKER,
            rules=(_block_rule(),),
            observed_denial=True,
            allowed_channel_digest_match=True,
        )
    )
    assert result.status == "verified"
    assert result.passed is True
    assert result.reasons == []


def test_inbound_rules_are_not_outbound_evidence() -> None:
    inbound = FirewallRuleEvidence(
        name="inbound_block",
        direction="inbound",
        action="block",
        principal_sids=(WORKER,),
    )
    result = evaluate(
        BoundaryEvidence(
            worker_principal_sid=WORKER,
            rules=(inbound,),
            observed_denial=True,
            allowed_channel_digest_match=True,
        )
    )
    assert result.passed is False
    assert "no_outbound_rule_for_worker" in result.reasons


# ------------------------------------------- worker 发送前复核审计摘要


def test_worker_requires_request_digest() -> None:
    assert body_digest_error({}, b"{}") == "request_digest_missing"
    assert body_digest_error({"request_digest": ""}, b"{}") == "request_digest_missing"


def test_worker_rejects_body_that_differs_from_audit() -> None:
    body = b'{"a":1}'
    digest = hashlib.sha256(body).hexdigest()
    assert body_digest_error({"request_digest": digest}, body) is None
    assert (
        body_digest_error({"request_digest": digest}, body + b" ")
        == "body_digest_mismatch"
    )
