"""S9：OS 级网络边界的诚实评估（离线，不读写真实防火墙）。

这些用例锁定“什么不算证据”，以及完整覆盖的必要性：
- 任意一条狭窄 block 不等于完整出站白名单；
- collector_errors 非空必须 fail-closed；
- 不能靠直接传几个 True 就冒充生产级 verified；
- 应用端点检查、TEST-NET 超时、受限令牌 DACL 均不构成网络证据。
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


def _block_rule(sid: str = WORKER, action: str = "block", **kwargs) -> FirewallRuleEvidence:
    return FirewallRuleEvidence(
        name="adll_worker_outbound_block",
        direction="outbound",
        action=action,
        principal_sids=(sid,),
        **kwargs,
    )


def _full_coverage(**overrides) -> BoundaryEvidence:
    """合法完整证据的基线；任何缺失都应由评估器判 unverified。"""
    base = {
        "worker_principal_sid": WORKER,
        "rules": (_block_rule(),),
        "observed_denial": True,
        "allowed_channel_digest_match": True,
        "outbound_block_covers_all": True,
        "outbound_block_covers_ipv4": True,
        "outbound_block_covers_ipv6": True,
        "loopback_blocked": True,
        "proxy_blocked": True,
        "no_allow_bypass": True,
    }
    base.update(overrides)
    return BoundaryEvidence(**base)


def test_missing_worker_principal_is_not_configured() -> None:
    result = evaluate(BoundaryEvidence(worker_principal_sid=None, rules=()))
    assert result.status == "not_configured"
    assert result.passed is False
    assert "worker_principal_unknown" in result.reasons


def test_rules_for_another_principal_do_not_count() -> None:
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
    result = evaluate(_full_coverage(observed_denial=False))
    assert result.status == "rule_present_unverified"
    assert result.passed is False
    assert "no_observed_denial" in result.reasons


def test_denial_without_digest_match_is_unverified() -> None:
    result = evaluate(_full_coverage(allowed_channel_digest_match=False))
    assert result.status == "unverified"
    assert result.passed is False
    assert "allowed_channel_digest_mismatch" in result.reasons


def test_allow_rule_alone_does_not_pass() -> None:
    result = evaluate(_full_coverage(rules=(_block_rule(action="allow"),)))
    assert result.passed is False
    assert "no_block_rule_for_worker" in result.reasons


def test_inbound_rules_are_not_outbound_evidence() -> None:
    inbound = FirewallRuleEvidence(
        name="inbound_block",
        direction="inbound",
        action="block",
        principal_sids=(WORKER,),
    )
    result = evaluate(_full_coverage(rules=(inbound,)))
    assert result.passed is False
    assert "no_outbound_rule_for_worker" in result.reasons


def test_full_evidence_passes() -> None:
    result = evaluate(_full_coverage())
    assert result.status == "verified"
    assert result.passed is True
    assert result.reasons == []


# ---------------------------- 假阳性与缺证据负向测试


def test_narrow_block_rule_is_not_complete_whitelist() -> None:
    """存在一条绑定 Worker 的 block，但未证明覆盖全部出站 → 不能判 verified。"""
    narrow = _block_rule(remote_addresses=("203.0.113.0/24",), covers_all_remote=False)
    result = evaluate(_full_coverage(rules=(narrow,), outbound_block_covers_all=False))
    assert result.status == "unverified"
    assert result.passed is False
    assert "block_does_not_cover_all_outbound" in result.reasons


def test_missing_ipv6_coverage_fails() -> None:
    result = evaluate(_full_coverage(outbound_block_covers_ipv6=False))
    assert result.passed is False
    assert "block_does_not_cover_ipv6" in result.reasons


def test_missing_ipv4_coverage_fails() -> None:
    result = evaluate(_full_coverage(outbound_block_covers_ipv4=False))
    assert result.passed is False
    assert "block_does_not_cover_ipv4" in result.reasons


def test_unblocked_loopback_fails() -> None:
    result = evaluate(_full_coverage(loopback_blocked=False))
    assert result.passed is False
    assert "loopback_not_blocked" in result.reasons


def test_proxy_path_not_blocked_fails() -> None:
    result = evaluate(_full_coverage(proxy_blocked=False))
    assert result.passed is False
    assert "proxy_path_not_blocked" in result.reasons


def test_allow_bypass_possible_fails() -> None:
    result = evaluate(_full_coverage(no_allow_bypass=False))
    assert result.passed is False
    assert "allow_bypass_possible" in result.reasons


def test_allow_rule_on_same_principal_fails() -> None:
    """同一主体既有 block 又有出站 allow → 放行可能覆盖 block，判 unverified。"""
    rules = (_block_rule(), _block_rule(action="allow"))
    result = evaluate(_full_coverage(rules=rules))
    assert result.passed is False
    assert "allow_rule_overrides_block" in result.reasons


def test_collector_error_fails_closed() -> None:
    result = evaluate(_full_coverage(collector_errors=["firewall_collection_failed"]))
    assert result.status == "unverified"
    assert result.passed is False
    assert "collector_errors_present" in result.reasons
    assert result.collector_errors == ["firewall_collection_failed"]


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
