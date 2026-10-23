"""方案版本链与反馈（T025）：不修改原版本、不自动继承审批、无真实 Adapter 时不假造新版本。"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.models.proposal import Feedback, ProposalVersion
from tests.helpers import csrf_headers, login_client, make_repo, seed_proposal


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
    client.put(
        f"/api/tasks/{task['id']}/requirement",
        json={"content": "需求"},
        headers=csrf_headers(csrf, "k-req"),
    )
    seed_proposal(app, task["id"])
    return app, client, csrf, task["id"]


def test_feedback_records_and_reports_regeneration_unavailable(tmp_path, app_factory) -> None:
    app, client, csrf, task_id = _setup(tmp_path, app_factory)
    resp = client.post(
        f"/api/tasks/{task_id}/proposals/1/feedback",
        json={"content": "请补充错误处理"},
        headers=csrf_headers(csrf, "fb1"),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["feedback"]["content"] == "请补充错误处理"
    assert body["regeneration"] == {
        "required": True,
        "available": False,
        "reason": "real_adapter_unavailable",
    }
    db = app.state.db.session()
    try:
        assert db.query(Feedback).count() == 1
        # 不得假造新方案版本
        assert db.query(ProposalVersion).filter_by(task_id=task_id).count() == 1
    finally:
        db.close()


def test_feedback_on_missing_version(tmp_path, app_factory) -> None:
    app, client, csrf, task_id = _setup(tmp_path, app_factory)
    resp = client.post(
        f"/api/tasks/{task_id}/proposals/99/feedback",
        json={"content": "x"},
        headers=csrf_headers(csrf, "fb2"),
    )
    assert resp.status_code == 404


def test_proposal_chain_lists_versions(tmp_path, app_factory) -> None:
    app, client, csrf, task_id = _setup(tmp_path, app_factory)
    resp = client.get(f"/api/tasks/{task_id}/proposals")
    assert resp.status_code == 200
    proposals = resp.json()["proposals"]
    assert len(proposals) == 1
    assert proposals[0]["seq"] == 1
    assert proposals[0]["has_approved_event"] is False


def test_feedback_append_only(tmp_path, app_factory) -> None:
    app, client, csrf, task_id = _setup(tmp_path, app_factory)
    client.post(
        f"/api/tasks/{task_id}/proposals/1/feedback",
        json={"content": "fb"},
        headers=csrf_headers(csrf, "fb3"),
    )
    db = app.state.db.session()
    try:
        with pytest.raises(Exception):
            db.execute(text("UPDATE feedbacks SET content='x'"))
            db.commit()
        db.rollback()
        with pytest.raises(Exception):
            db.execute(text("DELETE FROM feedbacks"))
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_feedback_does_not_inherit_or_invalidate_approval(tmp_path, app_factory) -> None:
    app, client, csrf, task_id = _setup(tmp_path, app_factory)
    approved = client.post(
        f"/api/tasks/{task_id}/proposals/1/approve",
        json={},
        headers=csrf_headers(csrf, "a1"),
    )
    assert approved.status_code == 200
    client.post(
        f"/api/tasks/{task_id}/proposals/1/feedback",
        json={"content": "意见"},
        headers=csrf_headers(csrf, "fb4"),
    )
    history = client.get(f"/api/tasks/{task_id}/approvals").json()["approvals"]
    assert len(history) == 1 and history[0]["effective"] is True
    proposals = client.get(f"/api/tasks/{task_id}/proposals").json()["proposals"]
    assert len(proposals) == 1  # 未生成新版本 → 无“继承”问题，也无假造