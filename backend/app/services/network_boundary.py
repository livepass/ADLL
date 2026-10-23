"""S9 网络边界评估：只承认可复核、覆盖完整的 OS 级证据，fail-closed。

`verified` 的充分条件（缺一即不通过）：

1. Worker 安全主体明确且已知（`worker_principal_sid`）；
2. 存在**完整覆盖**的出站 block 策略，而不是任意一条狭窄 block：
   - `outbound_block_covers_all`：block 规则覆盖该主体的全部出站（不限远端地址/程序/协议），
     或等价地构成覆盖 IPv4+IPv6 的默认拒绝；
   - `outbound_block_covers_ipv4` / `outbound_block_covers_ipv6` 分别成立；
   - 回环与代理/替代路径不得绕过（`loopback_blocked`、`proxy_blocked`）；
   - 无针对该主体的任何出站 `allow` 规则在 block 之上放行（`no_allow_bypass`）；
3. 同主体对**非授权目的地**有一次被拒绝观测（`observed_denial`）；
4. 授权通道字节摘要与审计 `request_digest` 一致（`allowed_channel_digest_match`）；
5. 采集过程无错误（`collector_errors` 为空）。

只要 `collector_errors` 非空、或关键证据来源不可复核，就 fail-closed。

明确**不构成证据**的观察（记入 `ignored_observations`）：应用层端点白名单、
TEST-NET 超时、受限令牌 DACL 检查、以及“存在任意一条 block 规则”（窄规则不等于完整白名单）。
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field

SID_RE = re.compile(r"S-1-[0-9-]+")

_COLLECT_RULES = r"""
$ErrorActionPreference = 'Stop'
$rows = @()
foreach ($r in @(Get-NetFirewallRule -Direction Outbound -Enabled True -ErrorAction Stop)) {
    $app = $null
    $sids = @()
    $ra = $null
    try { $app = ($r | Get-NetFirewallApplicationFilter).Program } catch { }
    try { $sids = @(($r | Get-NetFirewallSecurityFilter).LocalUser) } catch { }
    try { $ra = @(($r | Get-NetFirewallAddressFilter).RemoteAddress) } catch { }
    $rows += [pscustomobject]@{
        name    = $r.Name
        action  = [string]$r.Action
        program = $app
        local   = $sids
        remote  = $ra
    }
}
$rows | ConvertTo-Json -Depth 5 -Compress
"""


def _run_powershell(script: str, timeout: int = 60) -> tuple[str, str | None]:
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "", type(exc).__name__
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip().splitlines()
        return "", detail[-1] if detail else f"exit_{completed.returncode}"
    return completed.stdout.decode("utf-8", "replace"), None


def _resolve_principal_sid(sid_or_name: str) -> tuple[str | None, str | None]:
    """Return a SID for a configured principal (SID literal or account name)."""
    value = sid_or_name.strip()
    if SID_RE.fullmatch(value):
        return value, None
    script = (
        "$u = Get-LocalUser -Name '%s' -ErrorAction Stop; $u.SID.Value"
        % value.replace("'", "''")
    )
    out, error = _run_powershell(script)
    if error:
        return None, f"principal_lookup_failed:{error}"
    sid = out.strip()
    return (sid or None), None


def collect_boundary_evidence(
    worker_principal_sid: str | None,
) -> BoundaryEvidence:
    """Read-only collection + conservative evidence assembly (fail-closed).

    Only reports what the OS actually returns. `outbound_block_covers_*` /
    `loopback_blocked` / `proxy_blocked` / `no_allow_bypass` are all left False
    here: proving full coverage requires a dedicated denied-observation probe,
    not a rule-name heuristic. A bare collection therefore never yields
    `verified` — it can only reach `rule_present_unverified` at best.
    """
    errors: list[str] = []
    sid: str | None = None
    if not worker_principal_sid:
        return BoundaryEvidence(
            worker_principal_sid=None,
            collector_errors=["worker_principal_not_configured"],
        )
    sid, principal_error = _resolve_principal_sid(worker_principal_sid)
    if principal_error:
        errors.append(principal_error)

    rules, rule_errors = _collect_rules()
    errors.extend(rule_errors)

    return BoundaryEvidence(
        worker_principal_sid=sid,
        rules=tuple(rules),
        observed_denial=False,
        allowed_channel_digest_match=False,
        collector_errors=errors,
    )


def _collect_rules() -> tuple[list["FirewallRuleEvidence"], list[str]]:
    out, error = _run_powershell(_COLLECT_RULES)
    if error:
        return [], [f"firewall_collection_failed:{error}"]
    if not out.strip():
        return [], []
    try:
        rows = json.loads(out)
    except json.JSONDecodeError:
        return [], ["firewall_output_not_json"]
    if isinstance(rows, dict):
        rows = [rows]
    rules: list[FirewallRuleEvidence] = []
    for row in rows:
        local = row.get("local") or []
        if isinstance(local, str):
            local = [local]
        sids: list[str] = []
        for value in local:
            sids.extend(SID_RE.findall(str(value)))
        remote = row.get("remote") or []
        if isinstance(remote, str):
            remote = [remote]
        remote_addresses = tuple(sorted({str(r).strip() for r in remote if str(r).strip()}))
        rules.append(
            FirewallRuleEvidence(
                name=str(row.get("name") or ""),
                direction="outbound",
                action=str(row.get("action") or "").lower(),
                enabled=True,
                principal_sids=tuple(sorted(set(sids))),
                program=row.get("program") or None,
                remote_addresses=remote_addresses,
                covers_all_remote="any" in remote_addresses,
                covers_any_program=not row.get("program"),
            )
        )
    return rules, []



@dataclass(frozen=True)
class FirewallRuleEvidence:
    name: str
    direction: str  # "outbound" / "inbound"
    action: str  # "block" / "allow"
    enabled: bool = True
    principal_sids: tuple[str, ...] = ()
    program: str | None = None
    remote_addresses: tuple[str, ...] = ()
    protocol: str | None = None
    # 采集器能解析出“覆盖全部远端/程序”即置 True；否则视为未知/局部，不能据此判完整覆盖。
    covers_all_remote: bool = False
    covers_any_program: bool = False


@dataclass
class BoundaryEvidence:
    worker_principal_sid: str | None = None
    rules: tuple[FirewallRuleEvidence, ...] = ()
    observed_denial: bool = False
    allowed_channel_digest_match: bool = False
    # 明确覆盖声明（由可信采集器据规则展开得出，不能靠调用方直接填 True 冒充）
    outbound_block_covers_all: bool = False
    outbound_block_covers_ipv4: bool = False
    outbound_block_covers_ipv6: bool = False
    loopback_blocked: bool = False
    proxy_blocked: bool = False
    no_allow_bypass: bool = False
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


def _bound_rules(evidence: BoundaryEvidence, sid: str) -> list[FirewallRuleEvidence]:
    return [
        rule
        for rule in evidence.rules
        if rule.direction == "outbound"
        and rule.enabled
        and rule.principal_sids
        and sid in rule.principal_sids
    ]


def evaluate(evidence: BoundaryEvidence) -> BoundaryResult:
    ignored = _ignored(evidence)
    errors = list(evidence.collector_errors)

    # 采集出错 → 立即 fail-closed，不进入任何“通过”分支。
    if errors:
        return BoundaryResult("unverified", False, ["collector_errors_present"], ignored, errors)

    if not evidence.worker_principal_sid:
        return BoundaryResult(
            "not_configured", False, ["worker_principal_unknown"], ignored, errors
        )

    sid = evidence.worker_principal_sid
    bound = _bound_rules(evidence, sid)
    if not bound:
        return BoundaryResult(
            "not_configured", False, ["no_outbound_rule_for_worker"], ignored, errors
        )

    blockers = [rule for rule in bound if rule.action == "block"]
    if not blockers:
        return BoundaryResult(
            "unverified", False, ["no_block_rule_for_worker"], ignored, errors
        )

    # 任何作用于该主体的出站 allow，都可能覆盖 block；默认拒绝不能与放行共存。
    if any(rule.action == "allow" for rule in bound):
        return BoundaryResult(
            "unverified", False, ["allow_rule_overrides_block"], ignored, errors
        )

    reasons: list[str] = []
    if not evidence.outbound_block_covers_all:
        reasons.append("block_does_not_cover_all_outbound")
    if not evidence.outbound_block_covers_ipv4:
        reasons.append("block_does_not_cover_ipv4")
    if not evidence.outbound_block_covers_ipv6:
        reasons.append("block_does_not_cover_ipv6")
    if not evidence.loopback_blocked:
        reasons.append("loopback_not_blocked")
    if not evidence.proxy_blocked:
        reasons.append("proxy_path_not_blocked")
    if not evidence.no_allow_bypass:
        reasons.append("allow_bypass_possible")
    if reasons:
        return BoundaryResult("unverified", False, reasons, ignored, errors)

    if not evidence.observed_denial:
        return BoundaryResult(
            "rule_present_unverified", False, ["no_observed_denial"], ignored, errors
        )

    if not evidence.allowed_channel_digest_match:
        return BoundaryResult(
            "unverified", False, ["allowed_channel_digest_mismatch"], ignored, errors
        )

    return BoundaryResult("verified", True, [], ignored, errors)
