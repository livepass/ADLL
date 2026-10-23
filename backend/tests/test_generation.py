"""生成编排：门禁零发送、执行/核验/方案落库、失败与 fail-closed、审计对齐。"""
from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import text

from app.agents.dashscope import AdapterDisabled, DashscopeAgentAdapter
from app.models.generation import GenerationExecution, VerificationAttempt
from app.models.outbound import OutboundAuthorization, SendAuditRecord
from app.models.task import Task
from app.services import generation_service
from app.services.generation_service import GenerationBlocked, GenerationFailed
from app.services.outbound_pipeline import OutboundDenied
from tests.helpers import (
    csrf_headers,
    git,
    login_client,
    make_repo,
    seed_authorization,
)


def _setup(tmp_path, app_factory, *, testing=True, binary=False):
    repo = make_repo(tmp_path)
    (repo / "secret.txt").write_text("secret\n", encoding="utf-8", newline="\n")
    (repo / "other.txt").write_text("other\n", encoding="utf-8", newline="\n")
    (repo / ".env").write_text("X=1\n", encoding="utf-8", newline="\n")
    if binary:
        (repo / "bin.dat").write_bytes(b"\xff\xfe\x00binary\n")
    git(repo, "add", "secret.txt", "other.txt", ".env")
    if binary:
        git(repo, "add", "bin.dat")
    git(repo, "commit", "-m", "extra")
    app = app_factory(authorized_roots=(str(tmp_path),), testing=testing)
    client, csrf = login_client(app)
    linked = client.post(
        "/api/repositories/link", json={"path": str(repo)}, headers=csrf_headers(csrf)
    ).json()
    task = client.post(
        "/api/tasks",
        json={
            "repository_id": linked["repository"]["id"],
            "baseline_id": linked["baseline"]["id"],
            "title": "T",
        },
        headers=csrf_headers(csrf, "k-task"),
    ).json()["task"]
    client.put(
        f"/api/tasks/{task['id']}/requirement",
        json={"content": "需求"},
        headers=csrf_headers(csrf, "k-req"),
    )
    auth_id = seed_authorization(app, task["id"], scope={"paths": ["a.txt"]})
    return app, client, csrf, repo, task, auth_id


def _objects(app, task_id, auth_id):
    db = app.state.db.session()
    return db, db.get(Task, task_id), db.get(OutboundAuthorization, auth_id)


def _adapter(transport, *, enabled=True, synthetic=True):
    return DashscopeAgentAdapter(
        endpoint="https://example.invalid/v1/messages",
        model="m",
        enabled=enabled,
        transport=transport,
        synthetic_transport=synthetic,
    )


def _ok_transport(calls):
    def transport(payload, timeout):
        calls.append(payload)
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "synthetic plan"}],
            "usage": {"input_tokens": 5, "output_tokens": 3},
        }

    return transport


def _source(repo, path="a.txt"):
    content = (repo / path).read_text(encoding="utf-8")
    return [{"path": path, "content": content, "sha256": hashlib.sha256(content.encode()).hexdigest()}]


def _start(db, task, auth, repo, adapter, *, testing):
    return generation_service.start(
        db,
        task,
        auth,
        receiver=auth.receiver,
        data_types=list(auth.data_types),
        scope=dict(auth.send_scope),
        requirement_text="需求",
        feedback_texts=[],
        source_items=_source(repo),
        model="m",
        adapter=adapter,
        testing=testing,
    )


def test_success_creates_execution_verification_proposal(tmp_path, app_factory) -> None:
    app, _client, _csrf, repo, task, auth_id = _setup(tmp_path, app_factory)
    db, task_obj, auth = _objects(app, task["id"], auth_id)
    calls = []
    try:
        execution, verification, proposal = _start(
            db, task_obj, auth, repo, _adapter(_ok_transport(calls)), testing=True
        )
        assert execution.status == "completed"
        assert verification.status == "verified"
        assert proposal is not None and proposal.content == "synthetic plan"
        assert len(calls) == 1
        audit = db.query(SendAuditRecord).filter_by(execution_id=str(execution.id)).one()
        assert audit.payload_manifest["tool_return"] == []
        assert audit.payload_manifest["source"][0]["path"] == "a.txt"
        assert len(audit.content_digest) == 64
        assert audit.payload_digest is not None and len(audit.payload_digest) == 64
        assert audit.payload_digest != audit.content_digest
    finally:
        db.close()


def test_gate_denied_zero_send(tmp_path, app_factory) -> None:
    from app.models.base import utcnow

    app, _client, _csrf, repo, task, _auth_id = _setup(tmp_path, app_factory)
    revoked_id = seed_authorization(
        app, task["id"], scope={"paths": ["a.txt"]}, revoked_at=utcnow()
    )
    db, task_obj, auth = _objects(app, task["id"], revoked_id)
    calls = []
    try:
        with pytest.raises(OutboundDenied):
            _start(db, task_obj, auth, repo, _adapter(_ok_transport(calls)), testing=True)
        assert calls == []
        assert db.query(GenerationExecution).count() == 0
    finally:
        db.close()


def test_timeout_marks_execution_no_proposal(tmp_path, app_factory) -> None:
    app, _client, _csrf, repo, task, auth_id = _setup(tmp_path, app_factory)
    db, task_obj, auth = _objects(app, task["id"], auth_id)

    def transport(payload, timeout):
        raise TimeoutError()

    try:
        with pytest.raises(GenerationFailed) as exc:
            _start(db, task_obj, auth, repo, _adapter(transport), testing=True)
        assert exc.value.code == "timeout"
        execution = db.query(GenerationExecution).one()
        assert execution.status == "timeout"
        assert db.query(VerificationAttempt).count() == 0
    finally:
        db.close()


def test_adapter_disabled_fails_closed(tmp_path, app_factory) -> None:
    app, _client, _csrf, repo, task, auth_id = _setup(tmp_path, app_factory)
    db, task_obj, auth = _objects(app, task["id"], auth_id)
    calls = []
    try:
        with pytest.raises(GenerationFailed):
            _start(db, task_obj, auth, repo, _adapter(_ok_transport(calls), enabled=False), testing=True)
        assert calls == []
        assert db.query(GenerationExecution).one().status == "failed"
    finally:
        db.close()


def test_isolation_unverified_blocks_before_send(tmp_path, app_factory) -> None:
    app, _client, _csrf, repo, task, auth_id = _setup(tmp_path, app_factory)
    db, task_obj, auth = _objects(app, task["id"], auth_id)
    calls = []
    try:
        with pytest.raises(GenerationBlocked) as exc:
            _start(
                db,
                task_obj,
                auth,
                repo,
                _adapter(_ok_transport(calls), synthetic=False),
                testing=False,
            )
        assert exc.value.code == "isolation_unverified"
        assert calls == []
        assert db.query(GenerationExecution).count() == 0
    finally:
        db.close()


def test_unverified_execution_yields_no_proposal(tmp_path, app_factory) -> None:
    app, _client, _csrf, repo, task, auth_id = _setup(tmp_path, app_factory)
    db, task_obj, auth = _objects(app, task["id"], auth_id)
    calls = []
    try:
        execution, verification, proposal = _start(
            db, task_obj, auth, repo, _adapter(_ok_transport(calls)), testing=False
        )
        assert execution.status == "completed"
        assert verification.status == "unconfirmed"
        assert proposal is None
    finally:
        db.close()


def test_api_generation_testing_flow(tmp_path, app_factory) -> None:
    import time

    app, client, csrf, repo, task, auth_id = _setup(tmp_path, app_factory, testing=True)
    resp = client.post(
        f"/api/tasks/{task['id']}/generations",
        json={"authorization_id": auth_id},
        headers=csrf_headers(csrf, "gen-1"),
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    execution_id = body["execution_id"]
    assert body["status"] == "running"
    assert body["snapshot"]["authorized_paths"] == ["a.txt"]
    assert body["snapshot"]["files"] == ["a.txt"]
    reasons = {e["path"]: e["reason"] for e in body["snapshot"]["excluded"]}
    assert reasons.get("other.txt") == "not_authorized"
    assert reasons.get("secret.txt") == "sensitive"
    assert reasons.get(".env") == "sensitive"

    for _ in range(300):
        detail = client.get(f"/api/generations/{execution_id}").json()
        if detail["execution"]["status"] in generation_service.TERMINAL:
            break
        time.sleep(0.02)
    detail = client.get(f"/api/generations/{execution_id}").json()
    assert detail["execution"]["status"] == "completed"
    assert detail["execution"]["provider"] == "mock"
    assert detail["verification"]["status"] == "verified"
    assert detail["proposal"] is not None

    audit = client.get(f"/api/generations/{execution_id}/send-audit").json()["audits"]
    assert audit and audit[0]["payload_manifest"]["source"][0]["path"] == "a.txt"

    cancel = client.post(
        f"/api/generations/{execution_id}/cancel", headers=csrf_headers(csrf, "cancel-1")
    )
    assert cancel.json()["outcome"] == "already_finished"


def test_api_generation_baseline_unavailable_returns_423(tmp_path, app_factory) -> None:
    from app.models.repository import AnalysisBaseline

    app, client, csrf, repo, task, auth_id = _setup(tmp_path, app_factory, testing=True)
    db = app.state.db.session()
    try:
        baseline = db.get(AnalysisBaseline, task["baseline_id"])
        baseline.available = False
        baseline.unavailable_reason = "commit_missing"
        db.commit()
    finally:
        db.close()

    resp = client.post(
        f"/api/tasks/{task['id']}/generations",
        json={"authorization_id": auth_id},
        headers=csrf_headers(csrf, "gen-423"),
    )
    assert resp.status_code == 423
    assert resp.json()["code"] == "baseline_unavailable"


def test_binary_file_skipped_and_recorded(tmp_path, app_factory) -> None:
    import time

    app, client, csrf, repo, task, _auth_id = _setup(
        tmp_path, app_factory, testing=True, binary=True
    )
    auth_id = seed_authorization(
        app, task["id"], scope={"paths": ["a.txt", "bin.dat"]}
    )

    resp = client.post(
        f"/api/tasks/{task['id']}/generations",
        json={"authorization_id": auth_id},
        headers=csrf_headers(csrf, "gen-bin"),
    )
    assert resp.status_code == 202, resp.text
    snapshot = resp.json()["snapshot"]
    assert snapshot["files"] == ["a.txt"]
    assert "bin.dat" in snapshot["snapshot_files"]
    assert {"path": "bin.dat", "reason": "binary"} in snapshot["excluded"]

    execution_id = resp.json()["execution_id"]
    for _ in range(300):
        detail = client.get(f"/api/generations/{execution_id}").json()
        if detail["execution"]["status"] in generation_service.TERMINAL:
            break
        time.sleep(0.02)
    assert detail["execution"]["status"] == "completed"
    audit = client.get(f"/api/generations/{execution_id}/send-audit").json()["audits"]
    assert [item["path"] for item in audit[0]["payload_manifest"]["source"]] == ["a.txt"]


def test_api_generation_production_disabled(tmp_path, app_factory) -> None:
    app, client, csrf, _repo, task, auth_id = _setup(tmp_path, app_factory, testing=False)
    resp = client.post(
        f"/api/tasks/{task['id']}/generations",
        json={"authorization_id": auth_id},
        headers=csrf_headers(csrf, "gen-prod"),
    )
    assert resp.status_code == 503
    assert resp.json()["code"] == "ai_disabled"


def test_terminal_freeze_and_verification_append_only(tmp_path, app_factory) -> None:
    app, _client, _csrf, repo, task, auth_id = _setup(tmp_path, app_factory)
    db, task_obj, auth = _objects(app, task["id"], auth_id)
    try:
        execution, _verification, _proposal = _start(
            db, task_obj, auth, repo, _adapter(_ok_transport([])), testing=True
        )
        with pytest.raises(Exception):
            db.execute(
                text("UPDATE generation_executions SET status='failed' WHERE id=:i"),
                {"i": execution.id},
            )
            db.commit()
        db.rollback()
        with pytest.raises(Exception):
            db.execute(text("UPDATE verification_attempts SET status='failed'"))
            db.commit()
        db.rollback()
    finally:
        db.close()