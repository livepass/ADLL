"""批 10：实际 HTTP JSON 请求体摘要（payload_digest）离线验证。

- canonical bytes 与 HTTP transport/worker 使用同一字节序列；
- 任一请求字段变化 → 摘要变化；
- 摘要不含 Authorization/API Key；
- SendAuditRecord 持久化 execution_id/authorization_id/payload_digest。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import urllib.request
from pathlib import Path

from app.agents.dashscope import _urllib_transport
from app.core.payload import canonical_payload_bytes, payload_digest

BACKEND = Path(__file__).resolve().parents[1]


def _payload() -> dict:
    return {
        "model": "qwen3.7-flash-2026-07-15",
        "max_tokens": 256,
        "thinking": {"type": "disabled"},
        "stream": False,
        "messages": [{"role": "user", "content": "## Requirement\n合成需求"}],
    }


class _FakeResponse:
    status = 200

    def read(self, size: int | None = None) -> bytes:
        return b'{"stop_reason":"end_turn","content":[],"usage":{}}'

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


class _CapturingOpener:
    def __init__(self) -> None:
        self.request = None
        self.timeout = None

    def open(self, request, timeout=None):
        self.request = request
        self.timeout = timeout
        return _FakeResponse()


def test_digest_is_stable_and_changes_with_any_field() -> None:
    payload = _payload()
    baseline = payload_digest(payload)
    assert baseline == hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()
    assert baseline == payload_digest(json.loads(json.dumps(payload)))

    variants = [
        {**payload, "model": "other-model"},
        {**payload, "max_tokens": 128},
        {
            **payload,
            "messages": [{"role": "user", "content": "## Requirement\nchanged"}],
        },
        {**payload, "stream": True},
    ]
    for variant in variants:
        assert payload_digest(variant) != baseline


def test_urllib_transport_sends_canonical_bytes_without_key(monkeypatch) -> None:
    opener = _CapturingOpener()

    def fake_build_opener(*args, **kwargs):
        return opener

    monkeypatch.setenv("ADLL_DASHSCOPE_ENDPOINT", "https://example.invalid/v1/messages")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "FAKE-KEY-MUST-NOT-APPEAR")
    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)

    payload = _payload()
    _urllib_transport(payload, 30)

    assert opener.request.data == canonical_payload_bytes(payload)
    assert hashlib.sha256(opener.request.data).hexdigest() == payload_digest(payload)
    assert b"FAKE-KEY-MUST-NOT-APPEAR" not in opener.request.data
    assert b"Authorization" not in opener.request.data
    assert opener.timeout == 30


def test_worker_real_transport_uses_body_file_bytes(monkeypatch, tmp_path) -> None:
    spec = importlib.util.spec_from_file_location(
        "adll_worker_main", BACKEND / "app" / "isolation" / "worker_main.py"
    )
    assert spec is not None and spec.loader is not None
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)

    opener = _CapturingOpener()

    def fake_build_opener(*args, **kwargs):
        return opener

    body = canonical_payload_bytes(_payload())
    body_file = tmp_path / "request_body.bin"
    body_file.write_bytes(body)
    monkeypatch.setenv("ADLL_WORKER_REAL_TRANSPORT", "1")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "FAKE-KEY-MUST-NOT-APPEAR")
    monkeypatch.setattr(worker.urllib.request, "build_opener", fake_build_opener)

    result = worker._real_call(
        {
            "endpoint": "https://dashscope.aliyuncs.com/apps/anthropic/v1/messages",
            "payload": _payload(),
            "body_file": str(body_file),
            "work_dir": str(tmp_path),
            "timeout": 30,
        }
    )
    assert result["ok"] is True
    assert opener.request.data == body
    assert hashlib.sha256(opener.request.data).hexdigest() == payload_digest(_payload())
    assert (tmp_path / "sent.marker").exists()
    assert b"FAKE-KEY-MUST-NOT-APPEAR" not in opener.request.data


def test_generation_audit_persists_payload_digest(tmp_path, app_factory) -> None:
    from app.models.outbound import SendAuditRecord
    from tests.helpers import (
        csrf_headers,
        login_client,
        make_repo,
        seed_authorization,
    )

    repo = make_repo(tmp_path)
    app = app_factory(authorized_roots=(str(tmp_path),), testing=True)
    client, csrf = login_client(app)
    linked = client.post(
        "/api/repositories/link", json={"path": str(repo)}, headers=csrf_headers(csrf)
    ).json()
    task = client.post(
        "/api/tasks",
        json={
            "repository_id": linked["repository"]["id"],
            "baseline_id": linked["baseline"]["id"],
            "title": "digest",
        },
        headers=csrf_headers(csrf, "digest-task"),
    ).json()["task"]
    client.put(
        f"/api/tasks/{task['id']}/requirement",
        json={"content": "摘要测试"},
        headers=csrf_headers(csrf, "digest-req"),
    )
    auth_id = seed_authorization(app, task["id"], scope={"paths": ["a.txt"]})
    resp = client.post(
        f"/api/tasks/{task['id']}/generations",
        json={"authorization_id": auth_id},
        headers=csrf_headers(csrf, "digest-gen"),
    )
    assert resp.status_code == 202, resp.text
    execution_id = resp.json()["execution_id"]
    import time

    for _ in range(200):
        detail = client.get(f"/api/generations/{execution_id}").json()
        if detail["execution"]["status"] in {"completed", "failed", "timeout", "cancelled"}:
            break
        time.sleep(0.02)

    db = app.state.db.session()
    try:
        record = (
            db.query(SendAuditRecord)
            .filter_by(execution_id=str(execution_id), phase="prepared")
            .one()
        )
        assert record.authorization_id == auth_id
        assert record.payload_digest
        assert len(record.payload_digest) == 64
        assert record.payload_digest != record.content_digest
        assert record.content_digest
    finally:
        db.close()

    audit = client.get(f"/api/generations/{execution_id}/send-audit").json()["audits"]
    prepared_audit = next(item for item in audit if item["phase"] == "prepared")
    assert prepared_audit["payload_digest"] == record.payload_digest