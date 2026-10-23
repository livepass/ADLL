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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.network_boundary import (  # noqa: E402
    collect_boundary_evidence,
    evaluate,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-principal", default="ADLLTest")
    args = parser.parse_args()

    evidence = collect_boundary_evidence(args.worker_principal)
    result = evaluate(evidence)
    rules = evidence.rules
    sid = evidence.worker_principal_sid
    payload = {
        **result.as_dict(),
        "worker_principal": args.worker_principal,
        "worker_principal_sid": sid,
        "outbound_rules_seen": len(rules),
        "outbound_rules_bound_to_worker": sum(
            1 for rule in rules if sid and sid in rule.principal_sids
        ),
        "note": "只读采集；未修改防火墙，未发起外部网络请求；"
        "完整覆盖/拒绝观测/通道摘要仍需专项探测，仅采集不会判 verified。",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
