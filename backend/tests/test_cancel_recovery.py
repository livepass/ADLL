"""T033–T034：取消（发送前/已发送后）、迟到结果、重启恢复、单运行约束。"""
from __future__ import annotations

import hashlib
import threading
import time

import pytest
from sqlalchemy import text

from app.agents.dashscope import DashscopeAgentAdapter
from app.models.base import utcnow
from app.models.generation import GenerationExecution, VerificationAttempt
from app.models.late_result import LateResultRecord
from app.models.outbound import OutboundAuthorization
from app.models.proposal import ProposalVersion
from app.models.task import Task
from app.services import generation_service, outbound_pipeline
from tests.helpers import (
    RECEIVER_WORKER,
    csrf_headers,
    git,
    login_client,
    make_repo,
    seed_authorization,
)


def _setup(tmp_path, app_factory):
    repo = make_repo(tmp_path)
    app = app_factory(authorized_roots=(str(tmp_path),))
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
    try:
        task_obj = db.get(Task, task["id"])
        auth = db.get(OutboundAuthorization, auth_id)
        return app, db, repo, task_obj, auth, requirement
    finally:
        pass


def _adapter(transport):
    return DashscopeAgentAdapter(
        endpoint="https://example.invalid/v1/messages",
        model="m",
        enabled=True,
        transport=transport,
        synthetic_transport=True,
    )


def _source(repo):
    content = (repo / "a.txt").read_text(encoding="utf-8")
    return [{"path": "a.txt", "content": content, "sha256": hashlib.sha256(content.encode()).hexdigest()}]


def _prepared(db, task, auth, repo):
    return outbound_pipeline.prepare(
        task=task,
        auth=auth,
        receiver=auth.receiver,
        requirement_text="需求",
        feedback_texts=[],
        source_items=_source(repo),
        model="m",
    )


def _running(db, task, requirement):
    execution = GenerationExecution(
        task_id=task.id,
        baseline_id=task.baseline_id,
        requirement_version_id=requirement["id"],
        status="running",
        provider="mock",
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution


def _ok(calls=None):
    def transport(payload, timeout):
        if calls is not None:
            calls.append(payload)
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "plan"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    return transport


def test_cancel_before_send_is_cancelled_without_send(tmp_path, app_factory) -> None:
    app, db, repo, task, auth, requirement = _setup(tmp_path, app_factory)
    try:
        event = threading.Event()
        event.set()  # 取消在发送前已受理
        calls = []
        execution = _running(db, task, requirement)
        prepared = _prepared(db, task, auth, repo)
        verification, proposal = generation_service._run_body(
            db,
            execution,
            prepared,
            _adapter(_ok(calls)),
            auth_id=auth.id,
            requirement_text="需求",
            feedback_texts=[],
            source_items=_source(repo),
            requirement_id=requirement["id"],
            task_id=task.id,
            baseline_id=task.baseline_id,
            snapshot_digest="0" * 64,
            snapshot_manifest=_source(repo),
            isolation={"ok": True, "details": {"synthetic": True}},
            testing=True,
            cancel_event=event,
        )
        assert calls == []
        assert execution.status == "cancelled"
        assert execution.cancel_outcome == "cancelled"
        assert verification is None and proposal is None
    finally:
        db.close()


def test_cancel_after_send_is_not_cancelled_and_late_result_recorded(tmp_path, app_factory) -> None:
    app, db, repo, task, auth, requirement = _setup(tmp_path, app_factory)
    try:
        event = threading.Event()
        calls = []

        def transport(payload, timeout):
            calls.append(payload)
            event.set()  # 请求已发出后才收到取消
            return {
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "late plan"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }

        execution = _running(db, task, requirement)
        prepared = _prepared(db, task, auth, repo)
        verification, proposal = generation_service._run_body(
            db,
            execution,
            prepared,
            _adapter(transport),
            auth_id=auth.id,
            requirement_text="需求",
            feedback_texts=[],
            source_items=_source(repo),
            requirement_id=requirement["id"],
            task_id=task.id,
            baseline_id=task.baseline_id,
            snapshot_digest="0" * 64,
            snapshot_manifest=_source(repo),
            isolation={"ok": True, "details": {"synthetic": True}},
            testing=True,
            cancel_event=event,
        )
        assert len(calls) == 1  # 已发送，无法撤回
        assert execution.status == "cancelled"
        assert execution.cancel_outcome == "not_cancelled"
        assert verification is None and proposal is None
        late = db.query(LateResultRecord).filter_by(execution_id=execution.id).one()
        assert late.disposition == "discard"
        assert len(late.digest) == 64
        assert db.query(ProposalVersion).count() == 0
    finally:
        db.close()


def test_cancel_terminal_returns_already_finished(tmp_path, app_factory) -> None:
    app, db, repo, task, auth, requirement = _setup(tmp_path, app_factory)
    try:
        execution = _running(db, task, requirement)
        execution.status = "completed"
        execution.finished_at = utcnow()
        db.commit()
        assert generation_service.request_cancel(db, execution.id) == "already_finished"
        assert generation_service.request_cancel(db, 99999) is None
    finally:
        db.close()


def test_restart_recovery_marks_running_failed(tmp_path, app_factory) -> None:
    app, db, repo, task, auth, requirement = _setup(tmp_path, app_factory)
    try:
        execution = _running(db, task, requirement)
        count = generation_service.reconcile_after_restart(db)
        assert count >= 1
        refreshed = db.get(GenerationExecution, execution.id)
        assert refreshed.status == "failed"
        assert refreshed.failure_reason == "restart_incomplete"
        # 证据不足：不产生 verified
        assert db.query(VerificationAttempt).filter_by(execution_id=execution.id).count() == 0
    finally:
        db.close()


def test_single_running_execution_enforced(tmp_path, app_factory) -> None:
    app, db, repo, task, auth, requirement = _setup(tmp_path, app_factory)
    try:
        _running(db, task, requirement)
        with pytest.raises(generation_service.GenerationBlocked) as exc:
            generation_service.start_async(
                db,
                app.state.db.session,
                task,
                auth,
                requirement_text="需求",
                feedback_texts=[],
                source_items=_source(repo),
                model="m",
                adapter=_adapter(_ok()),
                testing=True,
            )
        assert exc.value.code == "active_execution_exists"
    finally:
        db.close()


def test_retry_has_independent_execution_identity(tmp_path, app_factory) -> None:
    app, db, repo, task, auth, requirement = _setup(tmp_path, app_factory)
    try:
        first = generation_service.start_async(
            db, app.state.db.session, task, auth,
            requirement_text="需求", feedback_texts=[],
            source_items=_source(repo), model="m", adapter=_adapter(_ok()), testing=True,
        )
        for _ in range(200):
            check = app.state.db.session()
            try:
                if check.get(GenerationExecution, first).status in generation_service.TERMINAL:
                    break
            finally:
                check.close()
            time.sleep(0.02)
        second = generation_service.start_async(
            db, app.state.db.session, task, auth,
            requirement_text="需求", feedback_texts=[],
            source_items=_source(repo), model="m", adapter=_adapter(_ok()), testing=True,
        )
        assert first != second
    finally:
        db.close()


class _CancelAdapter:
    def __init__(self, sent: bool, event: threading.Event) -> None:
        self.sent = sent
        self.event = event

    def generate(self, request, sink=None):
        from app.agents.dashscope import AdapterCancelled

        self.event.set()
        raise AdapterCancelled("worker terminated", sent=self.sent)


@pytest.mark.parametrize(
    ("sent", "outcome"), [(False, "cancelled"), (True, "not_cancelled")]
)
def test_worker_termination_records_true_cancel_outcome(
    tmp_path, app_factory, sent, outcome
) -> None:
    app, db, repo, task, auth, requirement = _setup(tmp_path, app_factory)
    try:
        event = threading.Event()
        execution = _running(db, task, requirement)
        verification, proposal = generation_service._run_body(
            db,
            execution,
            _prepared(db, task, auth, repo),
            _CancelAdapter(sent, event),
            auth_id=auth.id,
            requirement_text="需求",
            feedback_texts=[],
            source_items=_source(repo),
            requirement_id=requirement["id"],
            task_id=task.id,
            baseline_id=task.baseline_id,
            snapshot_digest="0" * 64,
            snapshot_manifest=_source(repo),
            isolation={"ok": True, "details": {"synthetic": True}},
            testing=True,
            cancel_event=event,
        )
        assert execution.status == "cancelled"
        assert execution.cancel_outcome == outcome
        assert verification is None and proposal is None
        assert db.query(ProposalVersion).count() == 0
    finally:
        db.close()


def test_late_result_append_only(tmp_path, app_factory) -> None:
    app, db, repo, task, auth, requirement = _setup(tmp_path, app_factory)
    try:
        event = threading.Event()

        def transport(payload, timeout):
            event.set()
            return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "x"}]}

        execution = _running(db, task, requirement)
        generation_service._run_body(
            db, execution, _prepared(db, task, auth, repo), _adapter(transport),
            auth_id=auth.id, requirement_text="需求", feedback_texts=[],
            source_items=_source(repo), requirement_id=requirement["id"],
            task_id=task.id, baseline_id=task.baseline_id,
            snapshot_digest="0" * 64,
            snapshot_manifest=_source(repo),
            isolation={"ok": True, "details": {"synthetic": True}},
            testing=True, cancel_event=event,
        )
        with pytest.raises(Exception):
            db.execute(text("UPDATE late_result_records SET disposition='x'"))
            db.commit()
        db.rollback()
    finally:
        db.close()