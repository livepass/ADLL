"""S9 只读网络边界探针（不修改防火墙、不发起外部网络请求）。

用法：
    python scripts/s9_network_probe.py --worker-principal ADLLTest

输出 JSON：`status` / `passed` / `reasons` / `ignored_observations`。
未配置 OS 级出站限制时如实返回 `not_configured`（passed=false），
不会用应用端点检查、TEST-NET 超时或 DACL 结果冒充网络白名单。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.network_boundary import (  # noqa: E402
    BoundaryEvidence,
    FirewallRuleEvidence,
    evaluate,
)

SID_RE = re.compile(r"S-1-[0-9-]+")
COLLECT_RULES = r"""
$ErrorActionPreference = 'Stop'
$rows = @()
foreach ($r in @(Get-NetFirewallRule -Direction Outbound -Enabled True -ErrorAction Stop)) {
    $app = $null
    $sids = @()
    try { $app = ($r | Get-NetFirewallApplicationFilter).Program } catch { }
    try { $sids = @(($r | Get-NetFirewallSecurityFilter).LocalUser) } catch { }
    $rows += [pscustomobject]@{
        name    = $r.Name
        action  = [string]$r.Action
        program = $app
        local   = $sids
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


def resolve_principal_sid(name: str) -> tuple[str | None, str | None]:
    script = (
        "$u = Get-LocalUser -Name '%s' -ErrorAction Stop; $u.SID.Value" % name.replace("'", "''")
    )
    out, error = _run_powershell(script)
    if error:
        return None, f"principal_lookup_failed:{error}"
    sid = out.strip()
    return (sid or None), None


def collect_rules() -> tuple[list[FirewallRuleEvidence], list[str]]:
    out, error = _run_powershell(COLLECT_RULES)
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
        rules.append(
            FirewallRuleEvidence(
                name=str(row.get("name") or ""),
                direction="outbound",
                action=str(row.get("action") or "").lower(),
                enabled=True,
                principal_sids=tuple(sorted(set(sids))),
                program=row.get("program") or None,
            )
        )
    return rules, []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-principal", default="ADLLTest")
    args = parser.parse_args()

    sid, principal_error = resolve_principal_sid(args.worker_principal)
    rules, errors = collect_rules()
    if principal_error:
        errors.append(principal_error)

    evidence = BoundaryEvidence(
        worker_principal_sid=sid,
        rules=tuple(rules),
        # 只读探针不会发送任何请求，因此不存在“被拒绝”或“通道摘要一致”的证据。
        observed_denial=False,
        allowed_channel_digest_match=False,
        collector_errors=errors,
    )
    result = evaluate(evidence)
    payload = {
        **result.as_dict(),
        "worker_principal": args.worker_principal,
        "worker_principal_sid": sid,
        "outbound_rules_seen": len(rules),
        "outbound_rules_bound_to_worker": sum(
            1 for rule in rules if sid and sid in rule.principal_sids
        ),
        "note": "只读采集；未修改防火墙，未发起外部网络请求。",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
