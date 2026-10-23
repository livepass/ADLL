"""生成后核验（fail-closed）：只用可复核证据判定 verified。

输入证据四类：
1. 真实快照：`snapshot_digest` + 实际 source 清单（路径/内容摘要）；
2. 运行时隔离：适配器 `self_check()` 的探针证据（受限令牌/SID/DACL/Job）；
3. 发送事实：审计尝试的终态（`confirmed_sent` / `possibly_sent` / `not_sent`）；
4. 生成结果：响应文本摘要与传输证据。

任何一项缺失、矛盾或不可验证 → `unconfirmed`，并给出原因；不写死 verified，
也不以 `testing` 标记直接放行。合成/Mock 证据只允许在 testing=True 的离线测试中
判为 verified，并在证据中显式标注 `synthetic`。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from ..core.payload import payload_digest as compute_payload_digest

HEX64 = 64


@dataclass
class VerificationOutcome:
    status: str
    sufficient: bool
    checks: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    isolation: dict = field(default_factory=dict)
    synthetic: bool = False
    coverage_note: str = ""

    @property
    def evidence_sufficiency(self) -> dict:
        return {
            "sufficient": self.sufficient,
            "checks": self.checks,
            "reasons": self.reasons,
            "synthetic": self.synthetic,
        }


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == HEX64 and all(
        c in "0123456789abcdef" for c in value.lower()
    )


def _isolation_state(isolation: dict) -> tuple[bool, bool]:
    """Return (is_verified, is_synthetic)."""
    details = isolation.get("details") if isinstance(isolation, dict) else None
    if not isinstance(details, dict):
        return False, False
    synthetic = bool(details.get("synthetic") or details.get("mock"))
    verified = details.get("worker_isolation") == "verified" or synthetic
    return verified, synthetic


def verify(
    *,
    prepared,
    source_items: list[dict],
    snapshot_digest: str | None,
    snapshot_manifest: list[dict] | None = None,
    isolation: dict,
    send_phase: str,
    result_text: str,
    result_evidence: dict,
    testing: bool,
) -> VerificationOutcome:
    checks: dict[str, bool] = {}
    reasons: list[str] = []

    recomputed = compute_payload_digest(prepared.payload)
    checks["payload_digest"] = recomputed == prepared.request_digest
    if not checks["payload_digest"]:
        reasons.append("payload_digest_mismatch")

    manifest_source = prepared.payload_manifest.get("source") or []
    expected_source = [
        {"path": item["path"], "sha256": item["sha256"]} for item in source_items
    ]
    checks["manifest_source"] = manifest_source == expected_source
    if not checks["manifest_source"]:
        reasons.append("manifest_source_mismatch")

    checks["manifest_tool_return_empty"] = prepared.payload_manifest.get("tool_return") == []
    if not checks["manifest_tool_return_empty"]:
        reasons.append("tool_return_not_empty")

    # 快照摘要必须能由快照清单重算出来，不能只信任调用方给的一串十六进制。
    if _is_digest(snapshot_digest) and snapshot_manifest:
        recomputed_snapshot = hashlib.sha256(
            json.dumps(snapshot_manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        checks["snapshot_digest"] = recomputed_snapshot == snapshot_digest
    else:
        checks["snapshot_digest"] = False
    if not checks["snapshot_digest"]:
        reasons.append("snapshot_digest_invalid")

    isolation_ok, synthetic = _isolation_state(isolation)
    checks["isolation_verified"] = isolation_ok
    if not isolation_ok:
        reasons.append("isolation_unverified")

    checks["send_confirmed"] = send_phase == "confirmed_sent"
    if not checks["send_confirmed"]:
        reasons.append(f"send_{send_phase}")

    text = result_text or ""
    response_digest = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""
    checks["response_present"] = bool(text.strip())
    # 必须由适配器给出与响应正文一致的摘要；缺失即视为证据不足。
    checks["response_digest"] = bool(response_digest) and (
        result_evidence.get("response_digest") == response_digest
    )
    if not checks["response_present"]:
        reasons.append("response_empty")
    if not checks["response_digest"]:
        reasons.append("response_digest_mismatch")

    transport = str(result_evidence.get("transport") or "")
    confirmed = result_evidence.get("confirmed") is True
    checks["transport_confirmed"] = confirmed
    if not confirmed:
        reasons.append("transport_not_confirmed")

    if not testing:
        checks["non_synthetic_evidence"] = (not synthetic) and not transport.startswith(
            ("synthetic", "mock")
        )
        if not checks["non_synthetic_evidence"]:
            reasons.append("synthetic_evidence_in_production")

    sufficient = all(checks.values())
    status = "verified" if sufficient else "unconfirmed"
    note = (
        "verified: snapshot+isolation+send+response evidence complete"
        if sufficient
        else "unconfirmed: " + ", ".join(reasons)
    )
    return VerificationOutcome(
        status=status,
        sufficient=sufficient,
        checks=checks,
        reasons=reasons,
        isolation=isolation,
        synthetic=synthetic or transport.startswith(("synthetic", "mock")),
        coverage_note=note,
    )
