"""执行终态与核验的提交一致性（A）与重启后孤立发送尝试恢复（C）。

这里的并发检查不使用 sleep：在 `verification.verify()` 内部用**独立会话**
观察数据库已提交状态，因此“completed 是否提前可见”是被直接观测的事实，
而不是靠时间窗猜测。
"""
from __future__ import annotations

import hashlib
import json

import pytest

from app.agents.dashscope import DashscopeAgentAdapter
from app.models.generation import GenerationExecution, VerificationAttempt
from app.models.outbound import OutboundAuthorization, SendAuditRecord
from app.models.proposal import ProposalVersion
from app.models.task import Task
from app.services import generation_service, outbound, outbound_pipeline
from app.services.generation_service import GenerationFailed
from tests.helpers import (
    RECEIVER_WORKER,
    csrf_headers,
    login_client,
    make_repo,
    seed_authorization,
)

END_TURN = {
    "stop_reason": "end_turn",
    "content": [{"type": "text", "text": "synthetic plan"}],
    "usage": {"input_tokens": 1, "output_tokens": 1},
}


def _setup(tmp_path, app_factory):
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
            "title": "T",
        },
        headers=csrf_headers(csrf, "k-task"),
    ).json()["task"]
    requirement = client.put(
        f"/api/tasks/{task['id']}/requirement",
        json={"content": "需求"},
        headers=csrf_headers(csrf, "k-req"),
    ).json()["requirement_version"]
    auth_id = seed_authorization(
        app, task["id"], scope={"paths": ["a.txt"]}, receiver=RECEIVER_WORKER
    )
    db = app.state.db.session()
    return (
        app,
        client,
        db,
        db.get(Task, task["id"]),
        db.get(OutboundAuthorization, auth_id),
        requirement,
        repo,
    )


def _adapter(calls: list | None = None) -> DashscopeAgentAdapter:
    def transport(payload, timeout):
        if calls is not None:
            calls.append(payload)
        return END_TURN

    return DashscopeAgentAdapter(
        endpoint="https://example.invalid/v1/messages",
        model="m",
        enabled=True,
        transport=transport,
        synthetic_transport=True,
    )


def _source(repo) -> list[dict]:
    content = (repo / "a.txt").read_text(encoding="utf-8")
    return [
        {
            "path": "a.txt",
            "content": content,
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
        }
    ]


def _snapshot_digest(items: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(items, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _start(db, task, auth, repo, adapter, **overrides):
    items = _source(repo)
    prepared = outbound_pipeline.prepare(
        task=task,
        auth=auth,
        receiver=auth.receiver,
        requirement_text="需求",
        feedback_texts=[],
        source_items=items,
        model="m",
    )
    kwargs = {
        "requirement_text": "需求",
        "feedback_texts": [],
        "source_items": items,
        "model": "m",
        "adapter": adapter,
        "snapshot_digest": _snapshot_digest(items),
        "snapshot_manifest": items,
        "testing": True,
    }
    kwargs.update(overrides)
    assert prepared.request_digest  # 预览摘要存在
    return generation_service.start(db, task, auth, **kwargs)


# ---------------------------------------------------------------- A. 提交边界


def test_completed_never_visible_before_verification_is_persisted(
    tmp_path, app_factory, monkeypatch
) -> None:
    """核验执行期间，独立会话必须看到 running 且没有核验记录。"""
    _app, _client, db, task, auth, _req, repo = _setup(tmp_path, app_factory)
    observed: dict[str, object] = {}
    real_verify = generation_service.verification.verify

    def spy(**kwargs):
        side = _app.state.db.session()
        try:
            execution = (
                side.query(GenerationExecution)
                .order_by(GenerationExecution.id.desc())
                .first()
            )
            observed["status"] = execution.status
            observed["verifications"] = (
                side.query(VerificationAttempt)
                .filter_by(execution_id=execution.id)
                .count()
            )
        finally:
            side.close()
        return real_verify(**kwargs)

    monkeypatch.setattr(generation_service.verification, "verify", spy)
    try:
        execution, record, proposal = _start(db, task, auth, repo, _adapter())
        assert observed == {"status": "running", "verifications": 0}
        assert execution.status == "completed"
        assert record is not None and record.status == "verified"
        assert proposal is not None
    finally:
        db.close()


def test_verification_exception_leaves_failed_state(tmp_path, app_factory, monkeypatch) -> None:
    """核验抛异常：不得留下 completed，且已发生的发送仍可追溯。"""
    _app, _client, db, task, auth, _req, repo = _setup(tmp_path, app_factory)

    def boom(**kwargs):
        raise RuntimeError("verify exploded")

    monkeypatch.setattr(generation_service.verification, "verify", boom)
    try:
        with pytest.raises(GenerationFailed) as caught:
            _start(db, task, auth, repo, _adapter())
        assert caught.value.code.startswith("verification_error")
        db.expire_all()
        execution = db.query(GenerationExecution).one()
        assert execution.status == "failed"
        assert execution.failure_reason.startswith("verification_error")
        assert db.query(VerificationAttempt).count() == 0
        assert db.query(ProposalVersion).count() == 0
        phases = [
            row.phase
            for row in db.query(SendAuditRecord).order_by(SendAuditRecord.id).all()
        ]
        # 发送确实发生过：审计保留，但不因此伪造成功。
        assert phases == ["prepared", "confirmed_sent"]
    finally:
        db.close()


def test_persist_failure_rolls_back_completion(tmp_path, app_factory, monkeypatch) -> None:
    """核验已算出但最终提交失败：回滚后必须 failed，不能 completed。"""
    _app, _client, db, task, auth, _req, repo = _setup(tmp_path, app_factory)
    state = {"armed": False}
    real_verify = generation_service.verification.verify

    def verify_then_arm(**kwargs):
        outcome = real_verify(**kwargs)
        state["armed"] = True
        return outcome

    real_commit = db.commit

    def flaky_commit():
        if state["armed"]:
            state["armed"] = False
            raise RuntimeError("injected commit failure")
        return real_commit()

    monkeypatch.setattr(generation_service.verification, "verify", verify_then_arm)
    monkeypatch.setattr(db, "commit", flaky_commit)
    try:
        with pytest.raises(GenerationFailed) as caught:
            _start(db, task, auth, repo, _adapter())
        assert caught.value.code.startswith("verification_persist_error")
    finally:
        monkeypatch.setattr(db, "commit", real_commit)
    try:
        db.expire_all()
        execution = db.query(GenerationExecution).one()
        assert execution.status == "failed"
        assert execution.failure_reason.startswith("verification_persist_error")
        assert db.query(VerificationAttempt).count() == 0
        assert db.query(ProposalVersion).count() == 0
    finally:
        db.close()


def test_detail_flags_legacy_completed_without_verification(tmp_path, app_factory) -> None:
    """历史数据：completed 但无核验 → 读侧显式标记，不当作可信成功。"""
    _app, client, db, task, auth, requirement, _repo = _setup(tmp_path, app_factory)
    try:
        execution = GenerationExecution(
            task_id=task.id,
            baseline_id=task.baseline_id,
            requirement_version_id=requirement["id"],
            status="running",
            provider="mock",
            outbound_authorization_id=auth.id,
        )
        db.add(execution)
        db.commit()
        execution.status = "completed"
        db.commit()
        body = client.get(f"/api/generations/{execution.id}").json()
        assert body["verification"] is None
        assert body["verification_missing"] is True
        assert body["execution"]["status"] == "completed"
    finally:
        db.close()


# ------------------------------------------------------- C. 重启后的发送尝试


def _running_execution(db, task, requirement, auth) -> GenerationExecution:
    execution = GenerationExecution(
        task_id=task.id,
        baseline_id=task.baseline_id,
        requirement_version_id=requirement["id"],
        status="running",
        provider="mock",
        outbound_authorization_id=auth.id,
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution


def _prepared_attempt(db, task, auth, execution) -> str:
    return outbound.begin_attempt(
        db,
        auth,
        task_id=task.id,
        baseline_id=task.baseline_id,
        execution_id=str(execution.id),
        receiver=auth.receiver,
        manifest={"requirement": [], "feedback": [], "source": [], "tool_return": []},
        request_digest="0" * 64,
    )


def test_restart_marks_orphan_prepared_attempt_possibly_sent(
    tmp_path, app_factory
) -> None:
    _app, _client, db, task, auth, requirement, _repo = _setup(tmp_path, app_factory)
    try:
        execution = _running_execution(db, task, requirement, auth)
        attempt_id = _prepared_attempt(db, task, auth, execution)

        generation_service.reconcile_after_restart(db)

        rows = (
            db.query(SendAuditRecord)
            .filter_by(attempt_id=attempt_id)
            .order_by(SendAuditRecord.id)
            .all()
        )
        assert [row.phase for row in rows] == ["prepared", "possibly_sent"]
        # append-only：原 prepared 行未被改写
        assert rows[0].request_digest == "0" * 64
        assert rows[1].error_code == "restart_unconfirmed"
        assert rows[1].request_digest == rows[0].request_digest
        assert db.get(GenerationExecution, execution.id).status == "failed"
        # 不伪造“已发送”，也不声称“确定未发送”
        assert "confirmed_sent" not in {row.phase for row in rows}
        assert "not_sent" not in {row.phase for row in rows}
    finally:
        db.close()


def test_restart_reconcile_is_idempotent(tmp_path, app_factory) -> None:
    _app, _client, db, task, auth, requirement, _repo = _setup(tmp_path, app_factory)
    try:
        execution = _running_execution(db, task, requirement, auth)
        attempt_id = _prepared_attempt(db, task, auth, execution)
        generation_service.reconcile_after_restart(db)
        generation_service.reconcile_after_restart(db)
        rows = (
            db.query(SendAuditRecord)
            .filter_by(attempt_id=attempt_id)
            .order_by(SendAuditRecord.id)
            .all()
        )
        assert [row.phase for row in rows] == ["prepared", "possibly_sent"]
    finally:
        db.close()


def test_reconcile_skips_attempt_with_terminal_phase(tmp_path, app_factory) -> None:
    _app, _client, db, task, auth, requirement, _repo = _setup(tmp_path, app_factory)
    try:
        execution = _running_execution(db, task, requirement, auth)
        attempt_id = _prepared_attempt(db, task, auth, execution)
        outbound.finish_attempt(db, attempt_id, phase="confirmed_sent")
        assert generation_service.reconcile_orphan_attempts(db) == 0
        phases = [
            row.phase
            for row in db.query(SendAuditRecord)
            .filter_by(attempt_id=attempt_id)
            .order_by(SendAuditRecord.id)
            .all()
        ]
        assert phases == ["prepared", "confirmed_sent"]
    finally:
        db.close()


def test_orphan_reconcile_leaves_in_flight_attempt_alone(tmp_path, app_factory) -> None:
    """单跑 reconcile_orphan_attempts 时，仍在 running 的执行不能被打断。"""
    _app, _client, db, task, auth, requirement, _repo = _setup(tmp_path, app_factory)
    try:
        execution = _running_execution(db, task, requirement, auth)
        attempt_id = _prepared_attempt(db, task, auth, execution)
        assert generation_service.reconcile_orphan_attempts(db) == 0
        phases = [
            row.phase
            for row in db.query(SendAuditRecord)
            .filter_by(attempt_id=attempt_id)
            .order_by(SendAuditRecord.id)
            .all()
        ]
        assert phases == ["prepared"]
    finally:
        db.close()
