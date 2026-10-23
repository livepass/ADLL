"""核验服务：只按证据判定，缺一项即 unconfirmed（离线合成，不触网）。"""
from __future__ import annotations

import hashlib
import json

from app.core.payload import payload_digest
from app.services.outbound_pipeline import Prepared
from app.services.verification import verify

TEXT = "synthetic plan"
SOURCE = [{"path": "a.txt", "content": "hello\n", "sha256": hashlib.sha256(b"hello\n").hexdigest()}]


def _snapshot_digest(items=SOURCE) -> str:
    canonical = json.dumps(items, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _prepared() -> Prepared:
    payload = {
        "model": "m",
        "max_tokens": 256,
        "thinking": {"type": "disabled"},
        "stream": False,
        "messages": [{"role": "user", "content": "## Requirement\n需求"}],
    }
    manifest = {
        "requirement": ["需求"],
        "feedback": [],
        "source": [{"path": "a.txt", "sha256": SOURCE[0]["sha256"]}],
        "tool_return": [],
    }
    return Prepared(
        payload=payload,
        payload_manifest=manifest,
        request_digest=payload_digest(payload),
        receiver="https://example.invalid/v1/messages",
        scope={"paths": ["a.txt"]},
        data_types=["requirement", "source"],
    )


def _evidence(**overrides):
    base = {
        "transport": "worker-real",
        "sent": True,
        "confirmed": True,
        "response_digest": hashlib.sha256(TEXT.encode("utf-8")).hexdigest(),
    }
    base.update(overrides)
    return base


def _verify(**overrides):
    kwargs = {
        "prepared": _prepared(),
        "source_items": SOURCE,
        "snapshot_digest": _snapshot_digest(),
        "snapshot_manifest": SOURCE,
        "snapshot_manifest": SOURCE,
        "isolation": {"ok": True, "details": {"worker_isolation": "verified"}},
        "send_phase": "confirmed_sent",
        "result_text": TEXT,
        "result_evidence": _evidence(),
        "testing": False,
    }
    kwargs.update(overrides)
    return verify(**kwargs)


def test_complete_evidence_is_verified() -> None:
    outcome = _verify()
    assert outcome.status == "verified"
    assert outcome.sufficient is True
    assert outcome.reasons == []
    assert all(outcome.checks.values())


def test_possibly_sent_is_unconfirmed() -> None:
    outcome = _verify(send_phase="possibly_sent")
    assert outcome.status == "unconfirmed"
    assert "send_possibly_sent" in outcome.reasons
    assert outcome.checks["send_confirmed"] is False


def test_not_sent_is_unconfirmed() -> None:
    outcome = _verify(send_phase="not_sent")
    assert outcome.status == "unconfirmed"
    assert outcome.checks["send_confirmed"] is False


def test_missing_isolation_is_unconfirmed() -> None:
    outcome = _verify(isolation={"ok": False, "details": {}})
    assert outcome.status == "unconfirmed"
    assert "isolation_unverified" in outcome.reasons


def test_missing_snapshot_digest_is_unconfirmed() -> None:
    outcome = _verify(snapshot_digest=None)
    assert outcome.status == "unconfirmed"
    assert "snapshot_digest_invalid" in outcome.reasons


def test_tampered_snapshot_digest_is_unconfirmed() -> None:
    outcome = _verify(snapshot_digest="0" * 64)
    assert outcome.status == "unconfirmed"
    assert "snapshot_digest_invalid" in outcome.reasons


def test_payload_digest_mismatch_is_unconfirmed() -> None:
    prepared = _prepared()
    tampered = Prepared(
        payload={**prepared.payload, "max_tokens": 1},
        payload_manifest=prepared.payload_manifest,
        request_digest=prepared.request_digest,
        receiver=prepared.receiver,
        scope=prepared.scope,
        data_types=prepared.data_types,
    )
    outcome = _verify(prepared=tampered)
    assert outcome.status == "unconfirmed"
    assert "payload_digest_mismatch" in outcome.reasons


def test_manifest_source_mismatch_is_unconfirmed() -> None:
    prepared = _prepared()
    manifest = {**prepared.payload_manifest, "source": []}
    tampered = Prepared(
        payload=prepared.payload,
        payload_manifest=manifest,
        request_digest=prepared.request_digest,
        receiver=prepared.receiver,
        scope=prepared.scope,
        data_types=prepared.data_types,
    )
    outcome = _verify(prepared=tampered)
    assert outcome.status == "unconfirmed"
    assert "manifest_source_mismatch" in outcome.reasons


def test_response_digest_mismatch_is_unconfirmed() -> None:
    outcome = _verify(result_evidence=_evidence(response_digest="0" * 64))
    assert outcome.status == "unconfirmed"
    assert "response_digest_mismatch" in outcome.reasons


def test_empty_response_is_unconfirmed() -> None:
    outcome = _verify(result_text="   ", result_evidence=_evidence(response_digest=""))
    assert outcome.status == "unconfirmed"
    assert "response_empty" in outcome.reasons


def test_transport_not_confirmed_is_unconfirmed() -> None:
    outcome = _verify(result_evidence=_evidence(confirmed=False))
    assert outcome.status == "unconfirmed"
    assert "transport_not_confirmed" in outcome.reasons


def test_synthetic_evidence_rejected_in_production() -> None:
    outcome = _verify(
        isolation={"ok": True, "details": {"synthetic": True}},
        result_evidence=_evidence(transport="synthetic"),
        testing=False,
    )
    assert outcome.status == "unconfirmed"
    assert "synthetic_evidence_in_production" in outcome.reasons


def test_synthetic_evidence_allowed_only_in_testing() -> None:
    outcome = _verify(
        isolation={"ok": True, "details": {"synthetic": True}},
        result_evidence=_evidence(transport="synthetic"),
        testing=True,
    )
    assert outcome.status == "verified"
    assert outcome.synthetic is True


def test_mock_evidence_allowed_only_in_testing() -> None:
    testing_outcome = _verify(
        isolation={"ok": True, "details": {"mock": True}},
        result_evidence=_evidence(transport="mock"),
        testing=True,
    )
    assert testing_outcome.status == "verified"

    production_outcome = _verify(
        isolation={"ok": True, "details": {"mock": True}},
        result_evidence=_evidence(transport="mock"),
        testing=False,
    )
    assert production_outcome.status == "unconfirmed"
