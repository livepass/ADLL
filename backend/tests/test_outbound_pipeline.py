"""发送前强制检查：五项条件、显式范围、实际数据类型、payload/manifest 对齐。"""
from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta

import pytest

from app.models.base import utcnow
from app.services.outbound_pipeline import OutboundDenied, actual_data_types, prepare
from tests.helpers import (
    RECEIVER_WORKER,
    csrf_headers,
    login_client,
    make_repo,
    seed_authorization,
)


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
    auth_kwargs.setdefault("receiver", RECEIVER_WORKER)
    auth_kwargs.setdefault("scope", {"paths": ["a.txt"]})
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


def _prepare(task, auth, *, receiver=None, source=None, requirement="需求", feedback=None):
    return prepare(
        task=task,
        auth=auth,
        receiver=receiver or auth.receiver,
        requirement_text=requirement,
        feedback_texts=feedback if feedback is not None else ["反馈"],
        source_items=source if source is not None else _source(),
        model="m",
    )


def test_prepare_valid(tmp_path, app_factory) -> None:
    _app, task, auth = _setup(tmp_path, app_factory)
    prepared = _prepare(task, auth)
    assert prepared.payload_manifest["tool_return"] == []
    assert prepared.payload_manifest["source"][0]["path"] == "a.txt"
    assert "hello" in prepared.payload["messages"][0]["content"]
    assert set(prepared.payload.keys()) == {"model", "max_tokens", "thinking", "stream", "messages"}
    assert len(prepared.request_digest) == 64
    assert prepared.data_types == ["requirement", "feedback", "source"]


def test_actual_data_types_are_computed_from_request() -> None:
    assert actual_data_types("需求", [], []) == ["requirement"]
    assert actual_data_types("需求", ["反馈"], []) == ["requirement", "feedback"]
    assert actual_data_types("需求", [], _source()) == ["requirement", "source"]
    assert actual_data_types("  ", [], []) == []


def test_empty_scope_never_authorizes_all_source(tmp_path, app_factory) -> None:
    _app, task, auth = _setup(tmp_path, app_factory, scope={})
    with pytest.raises(OutboundDenied) as exc:
        _prepare(task, auth)
    assert exc.value.code == "scope_required"


def test_no_authorization_denied(tmp_path, app_factory) -> None:
    _app, task, _auth = _setup(tmp_path, app_factory)
    with pytest.raises(OutboundDenied) as exc:
        prepare(
            task=task, auth=None, receiver=RECEIVER_WORKER,
            requirement_text="x", feedback_texts=[], source_items=_source(), model="m",
        )
    assert exc.value.code == "no_authorization"


def test_revoked_and_expired_denied(tmp_path, app_factory) -> None:
    _app, task, auth = _setup(tmp_path, app_factory, revoked_at=utcnow())
    with pytest.raises(OutboundDenied) as exc:
        _prepare(task, auth)
    assert exc.value.code == "revoked"

    _app2, task2, auth2 = _setup(
        tmp_path, app_factory, expires_at=utcnow() - timedelta(seconds=1)
    )
    with pytest.raises(OutboundDenied) as exc2:
        _prepare(task2, auth2)
    assert exc2.value.code == "expired"


def test_cross_task_and_baseline_denied(tmp_path, app_factory) -> None:
    _app, task, auth = _setup(tmp_path, app_factory)
    auth.task_id = task.id + 100  # 模拟跨任务授权
    with pytest.raises(OutboundDenied) as exc:
        _prepare(task, auth)
    assert exc.value.code == "task_mismatch"

    auth.task_id = task.id
    auth.baseline_id = task.baseline_id + 100
    with pytest.raises(OutboundDenied) as exc2:
        _prepare(task, auth)
    assert exc2.value.code == "baseline_mismatch"


def test_bare_receiver_label_is_unverifiable(tmp_path, app_factory) -> None:
    _app, task, auth = _setup(tmp_path, app_factory)
    with pytest.raises(OutboundDenied) as exc:
        _prepare(task, auth, receiver="dashscope")
    assert exc.value.code == "receiver_unverifiable"


def test_receiver_endpoint_mismatch_denied(tmp_path, app_factory) -> None:
    _app, task, auth = _setup(tmp_path, app_factory)
    with pytest.raises(OutboundDenied) as exc:
        _prepare(task, auth, receiver="https://other.invalid/v1/messages")
    assert exc.value.code == "receiver_mismatch"


def test_source_outside_scope_denied(tmp_path, app_factory) -> None:
    _app, task, auth = _setup(tmp_path, app_factory)
    with pytest.raises(OutboundDenied) as exc:
        _prepare(task, auth, source=_source("other.txt"))
    assert exc.value.code == "scope_mismatch"


def test_data_type_not_authorized_when_source_not_granted(tmp_path, app_factory) -> None:
    _app, task, auth = _setup(
        tmp_path, app_factory, data_types=["requirement"], scope={"paths": ["a.txt"]}
    )
    with pytest.raises(OutboundDenied) as exc:
        _prepare(task, auth)
    assert exc.value.code == "data_type_not_authorized"


def test_scope_cannot_contain_traversal(tmp_path, app_factory) -> None:
    _app, task, auth = _setup(tmp_path, app_factory, scope={"paths": ["../escape.txt"]})
    with pytest.raises(OutboundDenied) as exc:
        _prepare(task, auth, source=_source("../escape.txt"))
    assert exc.value.code == "unverifiable"


def test_sensitive_and_digest_mismatch_denied(tmp_path, app_factory) -> None:
    _app, task, auth = _setup(tmp_path, app_factory, scope={"paths": [".env", "a.txt"]})
    with pytest.raises(OutboundDenied) as exc:
        _prepare(task, auth, source=_source(".env", "X=1\n"))
    assert exc.value.code == "sensitive_source"

    with pytest.raises(OutboundDenied) as exc2:
        _prepare(
            task,
            auth,
            source=[{"path": "a.txt", "content": "hello\n", "sha256": "0" * 64}],
        )
    assert exc2.value.code == "source_digest_mismatch"
