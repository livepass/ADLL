"""发送前强制检查：五项条件、授权内容边界、payload/manifest 对齐。"""
from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta

import pytest

from app.models.base import utcnow
from app.services.outbound_pipeline import OutboundDenied, prepare
from tests.helpers import csrf_headers, login_client, make_repo, seed_authorization


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _setup(tmp_path, app_factory, **auth_kwargs):
    repo = make_repo(tmp_path, name="repo-" + uuid.uuid4().hex[:8])
    app = app_factory(authorized_roots=(str(tmp_path),))
    client, csrf = login_client(app)
    linked = client.post(
        "/api/repositories/link", json={"path": str(repo)}, headers=csrf_headers(csrf)
    ).json()
    tag = uuid.uuid4().hex[:8]
    task = client.post(
        "/api/tasks",
        json={
            "repository_id": linked["repository"]["id"],
            "baseline_id": linked["baseline"]["id"],
            "title": "T",
        },
        headers=csrf_headers(csrf, f"k-task-{tag}"),
    ).json()["task"]
    client.put(
        f"/api/tasks/{task['id']}/requirement",
        json={"content": "需求"},
        headers=csrf_headers(csrf, f"k-req-{tag}"),
    )
    auth_id = seed_authorization(app, task["id"], **auth_kwargs)
    db = app.state.db.session()
    try:
        from app.models.outbound import OutboundAuthorization
        from app.models.task import Task

        task_obj = db.get(Task, task["id"])
        auth = db.get(OutboundAuthorization, auth_id)
        return app, task_obj, auth
    finally:
        db.close()


def _source(path="a.txt", content="hello\n"):
    return [{"path": path, "content": content, "sha256": _sha(content)}]


def test_prepare_valid(tmp_path, app_factory) -> None:
    app, task, auth = _setup(tmp_path, app_factory)
    prepared = prepare(
        task=task,
        auth=auth,
        receiver=auth.receiver,
        data_types=list(auth.data_types),
        scope=dict(auth.send_scope),
        requirement_text="需求",
        feedback_texts=["反馈"],
        source_items=_source(),
        model="m",
    )
    assert prepared.payload_manifest["tool_return"] == []
    assert prepared.payload_manifest["source"][0]["path"] == "a.txt"
    assert "hello" in prepared.payload["messages"][0]["content"]
    assert set(prepared.payload.keys()) == {"model", "max_tokens", "thinking", "stream", "messages"}
    assert len(prepared.request_digest) == 64


def test_no_authorization_denied(tmp_path, app_factory) -> None:
    _app, task, _auth = _setup(tmp_path, app_factory)
    with pytest.raises(OutboundDenied) as exc:
        prepare(
            task=task, auth=None, receiver="dashscope", data_types=["requirement"],
            scope={}, requirement_text="x", feedback_texts=[], source_items=_source(), model="m",
        )
    assert exc.value.code == "no_authorization"


def test_revoked_and_expired_denied(tmp_path, app_factory) -> None:
    _app, task, auth = _setup(tmp_path, app_factory, revoked_at=utcnow())
    with pytest.raises(OutboundDenied) as exc:
        prepare(task=task, auth=auth, receiver=auth.receiver, data_types=list(auth.data_types),
                scope=dict(auth.send_scope), requirement_text="x", feedback_texts=[],
                source_items=_source(), model="m")
    assert exc.value.code == "revoked"

    _app2, task2, auth2 = _setup(tmp_path, app_factory, expires_at=utcnow() - timedelta(seconds=1))
    with pytest.raises(OutboundDenied) as exc2:
        prepare(task=task2, auth=auth2, receiver=auth2.receiver, data_types=list(auth2.data_types),
                scope=dict(auth2.send_scope), requirement_text="x", feedback_texts=[],
                source_items=_source(), model="m")
    assert exc2.value.code == "expired"


def test_cross_task_and_baseline_denied(tmp_path, app_factory) -> None:
    _app, task, auth = _setup(tmp_path, app_factory)
    other_task_id = task.id + 100
    auth.task_id = other_task_id  # 模拟跨任务授权
    with pytest.raises(OutboundDenied) as exc:
        prepare(task=task, auth=auth, receiver=auth.receiver, data_types=list(auth.data_types),
                scope=dict(auth.send_scope), requirement_text="x", feedback_texts=[],
                source_items=_source(), model="m")
    assert exc.value.code == "task_mismatch"

    auth.task_id = task.id
    auth.baseline_id = task.baseline_id + 100
    with pytest.raises(OutboundDenied) as exc2:
        prepare(task=task, auth=auth, receiver=auth.receiver, data_types=list(auth.data_types),
                scope=dict(auth.send_scope), requirement_text="x", feedback_texts=[],
                source_items=_source(), model="m")
    assert exc2.value.code == "baseline_mismatch"


def test_receiver_scope_and_type_denied(tmp_path, app_factory) -> None:
    _app, task, auth = _setup(tmp_path, app_factory)
    with pytest.raises(OutboundDenied) as exc:
        prepare(task=task, auth=auth, receiver="other", data_types=list(auth.data_types),
                scope=dict(auth.send_scope), requirement_text="x", feedback_texts=[],
                source_items=_source(), model="m")
    assert exc.value.code == "receiver_mismatch"

    with pytest.raises(OutboundDenied) as exc2:
        prepare(task=task, auth=auth, receiver=auth.receiver, data_types=list(auth.data_types),
                scope={"paths": ["other.txt"]}, requirement_text="x", feedback_texts=[],
                source_items=_source(), model="m")
    assert exc2.value.code == "scope_mismatch"

    with pytest.raises(OutboundDenied) as exc3:
        prepare(task=task, auth=auth, receiver=auth.receiver,
                data_types=["requirement", "source", "unknown_type"],
                scope=dict(auth.send_scope), requirement_text="x", feedback_texts=[],
                source_items=_source(), model="m")
    assert exc3.value.code == "data_type_not_authorized"


def test_sensitive_and_digest_mismatch_denied(tmp_path, app_factory) -> None:
    _app, task, auth = _setup(tmp_path, app_factory)
    with pytest.raises(OutboundDenied) as exc:
        prepare(task=task, auth=auth, receiver=auth.receiver, data_types=list(auth.data_types),
                scope=dict(auth.send_scope), requirement_text="x", feedback_texts=[],
                source_items=_source(".env", "X=1\n"), model="m")
    assert exc.value.code == "sensitive_source"

    with pytest.raises(OutboundDenied) as exc2:
        prepare(task=task, auth=auth, receiver=auth.receiver, data_types=list(auth.data_types),
                scope=dict(auth.send_scope), requirement_text="x", feedback_texts=[],
                source_items=[{"path": "a.txt", "content": "hello\n", "sha256": "0" * 64}],
                model="m")
    assert exc2.value.code == "source_digest_mismatch"