"""发送前最后的竞争边界（B/C 收口）。

覆盖：
- 预览摘要与「需求版本/源码快照变化」不一致时零发送；
- 授权在 prepare 之后、发送之前被撤销 → 零发送且不写发送审计；
- 同一次尝试的并发终结由数据库唯一索引兜底，审计不会出现互相矛盾的终态。
"""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.base import utcnow
from app.models.generation import GenerationExecution, VerificationAttempt
from app.models.outbound import OutboundAuthorization, SendAuditRecord
from app.models.task import Task
from app.services import generation_service, outbound, outbound_pipeline
from app.services.generation_service import GenerationBlocked, GenerationFailed
from tests.helpers import (
    RECEIVER_WORKER,
    csrf_headers,
    login_client,
    make_repo,
    seed_authorization,
)


class _VerifiedAdapter:
    """声明隔离已验证、端点为真实形状；从不真正发送。"""

    def __init__(self, endpoint: str = "https://example.invalid/v1/messages") -> None:
        self.endpoint = endpoint
        self.calls: list = []

    def capabilities(self):
        return SimpleNamespace(declares={"endpoint": self.endpoint})

    def self_check(self):
        return SimpleNamespace(ok=True, details={"worker_isolation": "verified"})

    def generate(self, request):  # pragma: no cover - 断言不会被调用
        self.calls.append(request)
        raise AssertionError("must not send")


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
    return (
        db,
        db.get(Task, task["id"]),
        db.get(OutboundAuthorization, auth_id),
        requirement,
        repo,
    )


def _source(repo, suffix: str = "") -> list[dict]:
    content = (repo / "a.txt").read_text(encoding="utf-8") + suffix
    return [
        {
            "path": "a.txt",
            "content": content,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }
    ]


def _snapshot_digest(items: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(items, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _prepared(db, task, auth, items, requirement_text: str = "需求"):
    return outbound_pipeline.prepare(
        task=task,
        auth=auth,
        receiver=auth.receiver,
        requirement_text=requirement_text,
        feedback_texts=[],
        source_items=items,
        model="m",
    )


def _start(db, task, auth, *, items, requirement_text, digest, adapter):
    return generation_service.start(
        db,
        task,
        auth,
        requirement_text=requirement_text,
        feedback_texts=[],
        source_items=items,
        model="m",
        adapter=adapter,
        snapshot_digest=_snapshot_digest(items),
        snapshot_manifest=items,
        preview_digest=digest,
        testing=False,
    )


def test_changed_requirement_after_preview_blocks_send(tmp_path, app_factory) -> None:
    db, task, auth, _req, repo = _setup(tmp_path, app_factory)
    try:
        items = _source(repo)
        preview_digest = _prepared(db, task, auth, items).request_digest
        adapter = _VerifiedAdapter()

        with pytest.raises(GenerationBlocked) as caught:
            _start(
                db,
                task,
                auth,
                items=items,
                requirement_text="需求（预览后被修改）",
                digest=preview_digest,
                adapter=adapter,
            )
        assert caught.value.code == "preview_digest_mismatch"
        assert adapter.calls == []
        assert db.query(GenerationExecution).count() == 0
    finally:
        db.close()


def test_changed_source_after_preview_blocks_send(tmp_path, app_factory) -> None:
    db, task, auth, _req, repo = _setup(tmp_path, app_factory)
    try:
        items = _source(repo)
        preview_digest = _prepared(db, task, auth, items).request_digest
        adapter = _VerifiedAdapter()

        changed = _source(repo, "// 预览后修改\n")
        with pytest.raises(GenerationBlocked) as caught:
            _start(
                db,
                task,
                auth,
                items=changed,
                requirement_text="需求",
                digest=preview_digest,
                adapter=adapter,
            )
        assert caught.value.code == "preview_digest_mismatch"
        assert adapter.calls == []
        assert db.query(GenerationExecution).count() == 0
    finally:
        db.close()


def test_matching_preview_digest_reaches_send(tmp_path, app_factory) -> None:
    """对照：摘要一致时才允许进入发送（避免上两条因别的原因通过）。"""
    db, task, auth, _req, repo = _setup(tmp_path, app_factory)
    try:
        items = _source(repo)
        preview_digest = _prepared(db, task, auth, items).request_digest
        adapter = _VerifiedAdapter()
        adapter.generate = lambda request: (_ for _ in ()).throw(RuntimeError("stop"))
        adapter.calls = []

        with pytest.raises(GenerationFailed):
            _start(
                db,
                task,
                auth,
                items=items,
                requirement_text="需求",
                digest=preview_digest,
                adapter=adapter,
            )
        # 说明确实走到了网络调用，而不是被门禁拦下（异常按“可能已发送”记录）
        phases = [
            row.phase
            for row in db.query(SendAuditRecord).order_by(SendAuditRecord.id).all()
        ]
        assert phases == ["prepared", "possibly_sent"]
    finally:
        db.close()


# --------------------------------------------------- 撤销与发送之间的竞争


def _running(db, task, requirement):
    execution = GenerationExecution(
        task_id=task.id,
        baseline_id=task.baseline_id,
        requirement_version_id=requirement["id"],
        status="running",
        provider="dashscope",
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution


def test_revoke_between_prepare_and_send_leaves_zero_send(tmp_path, app_factory) -> None:
    db, task, auth, requirement, repo = _setup(tmp_path, app_factory)
    try:
        items = _source(repo)
        prepared = _prepared(db, task, auth, items)
        execution = _running(db, task, requirement)

        # prepare 之后、真正发送之前撤销授权
        auth.status = "revoked"
        auth.revoked_at = utcnow()
        db.commit()

        adapter = _VerifiedAdapter()
        verification, proposal = generation_service._run_body(
            db,
            execution,
            prepared,
            adapter,
            auth_id=auth.id,
            requirement_text="需求",
            feedback_texts=[],
            source_items=items,
            requirement_id=requirement["id"],
            task_id=task.id,
            baseline_id=task.baseline_id,
            snapshot_digest=_snapshot_digest(items),
            snapshot_manifest=items,
            isolation={"ok": True, "details": {"worker_isolation": "verified"}},
            testing=False,
            cancel_event=None,
        )

        assert (verification, proposal) == (None, None)
        assert adapter.calls == []
        refreshed = db.get(GenerationExecution, execution.id)
        assert refreshed.status == "failed"
        assert refreshed.failure_reason == "authorization_revoked"
        # 未发出、也未写发送审计（不伪造 prepared/possibly_sent）
        assert db.query(SendAuditRecord).count() == 0
        assert db.query(VerificationAttempt).count() == 0
    finally:
        db.close()


# ----------------------------------------------- 同一次尝试的并发终结（DB 层）


def _attempt(db, task, auth, execution) -> str:
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


def test_second_terminal_is_rejected_by_database(tmp_path, app_factory) -> None:
    """绕过应用层检查直接插入第二个终态：数据库必须拒绝。"""
    db, task, auth, requirement, _repo = _setup(tmp_path, app_factory)
    try:
        execution = _running(db, task, requirement)
        attempt_id = _attempt(db, task, auth, execution)
        outbound.finish_attempt(db, attempt_id, phase="confirmed_sent")
        prepared_row = (
            db.query(SendAuditRecord)
            .filter_by(attempt_id=attempt_id, phase="confirmed_sent")
            .one()
        )

        contradictory = SendAuditRecord(
            authorization_id=prepared_row.authorization_id,
            execution_id=prepared_row.execution_id,
            attempt_id=attempt_id,
            phase="not_sent",
            receiver=prepared_row.receiver,
            payload_manifest=prepared_row.payload_manifest,
            content_digest=prepared_row.content_digest,
            payload_digest=prepared_row.payload_digest,
            request_digest=prepared_row.request_digest,
            error_code="race",
        )
        db.add(contradictory)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

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


def test_finish_attempt_twice_raises(tmp_path, app_factory) -> None:
    db, task, auth, requirement, _repo = _setup(tmp_path, app_factory)
    try:
        execution = _running(db, task, requirement)
        attempt_id = _attempt(db, task, auth, execution)
        outbound.finish_attempt(db, attempt_id, phase="possibly_sent", error_code="timeout")
        with pytest.raises(PermissionError):
            outbound.finish_attempt(db, attempt_id, phase="not_sent", error_code="late")
    finally:
        db.close()
