"""S9 网络边界评估：只承认可复核的 OS 级证据，fail-closed。

判定 `verified` 必须同时满足：

1. 存在**绑定到 Worker 安全主体**的出站规则（Windows Firewall，`direction=outbound`）；
2. 规则中有对该主体生效的 `block`；
3. 有一次同主体、同目的地的**被拒绝观测**（`observed_denial`）；
4. 实际允许通道的字节摘要与审计 `request_digest` 一致。

明确**不构成证据**的三类观察（只记入 `ignored_observations`）：

- 应用层端点白名单（`app_endpoint_check`）：只约束应用，不约束进程；
- TEST-NET/外部地址超时（`test_net_timeout`）：超时可能是 DNS、路由、代理或对端丢弃，
  不能证明被本地策略阻断；
- 受限令牌的 DACL 检查（`restricted_token_dacl_check`）：文件系统权限，与网络无关。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FirewallRuleEvidence:
    name: str
    direction: str  # "outbound" / "inbound"
    action: str  # "block" / "allow"
    enabled: bool = True
    principal_sids: tuple[str, ...] = ()
    program: str | None = None
    remote_addresses: tuple[str, ...] = ()


@dataclass
class BoundaryEvidence:
    worker_principal_sid: str | None = None
    rules: tuple[FirewallRuleEvidence, ...] = ()
    observed_denial: bool = False
    allowed_channel_digest_match: bool = False
    # 以下只用于如实记录“看过但不作数”的观察
    app_endpoint_check: bool = False
    test_net_timeout: bool = False
    restricted_token_dacl_check: bool = False
    collector_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BoundaryResult:
    status: str  # not_configured / rule_present_unverified / unverified / verified
    passed: bool
    reasons: list[str]
    ignored_observations: list[str]
    collector_errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "passed": self.passed,
            "reasons": self.reasons,
            "ignored_observations": self.ignored_observations,
            "collector_errors": self.collector_errors,
        }


def _ignored(evidence: BoundaryEvidence) -> list[str]:
    ignored: list[str] = []
    if evidence.app_endpoint_check:
        ignored.append("app_endpoint_check_is_not_network_control")
    if evidence.test_net_timeout:
        ignored.append("test_net_timeout_is_ambiguous")
    if evidence.restricted_token_dacl_check:
        ignored.append("restricted_token_dacl_check_is_not_network_policy")
    return ignored


def evaluate(evidence: BoundaryEvidence) -> BoundaryResult:
    ignored = _ignored(evidence)
    errors = list(evidence.collector_errors)

    if not evidence.worker_principal_sid:
        return BoundaryResult(
            "not_configured", False, ["worker_principal_unknown"], ignored, errors
        )

    bound = [
        rule
        for rule in evidence.rules
        if rule.direction == "outbound"
        and rule.enabled
        and rule.principal_sids
        and evidence.worker_principal_sid in rule.principal_sids
    ]
    if not bound:
        return BoundaryResult(
            "not_configured", False, ["no_outbound_rule_for_worker"], ignored, errors
        )

    blockers = [rule for rule in bound if rule.action == "block"]
    if not blockers:
        return BoundaryResult(
            "unverified", False, ["no_block_rule_for_worker"], ignored, errors
        )

    if not evidence.observed_denial:
        # 有规则但没观测到拒绝：只能说“规则存在，尚未验证”，不能算通过。
        return BoundaryResult(
            "rule_present_unverified", False, ["no_observed_denial"], ignored, errors
        )

    if not evidence.allowed_channel_digest_match:
        return BoundaryResult(
            "unverified", False, ["allowed_channel_digest_mismatch"], ignored, errors
        )

    return BoundaryResult("verified", True, [], ignored, errors)
