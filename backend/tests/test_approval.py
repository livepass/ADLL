"""审批门禁：正常/异常/并发/失效/回滚/幂等/append-only/重启重算。"""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.models.audit import AuditLog, SecurityEvent
from app.models.proposal import ApprovalEvent, ProposalVersion
from app.models.task import Task
from app.services import approval_service
from app.services.approval_service import ApprovalError
from tests.helpers import csrf_headers, git, login_client, make_repo, seed_proposal


def _setup(tmp_path, app_factory, **seed):
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
    proposal_id = seed_proposal(app, task["id"], **seed)
    return {
        "app": app,
        "client": client,
        "csrf": csrf,
        "repo": repo,
        "task_id": task["id"],
        "requirement": requirement,
        "proposal_id": proposal_id,
    }


def _approve(ctx, version=1, key="approve-1"):
    return ctx["client"].post(
        f"/api/tasks/{ctx['task_id']}/proposals/{version}/approve",
        json={"reason": None},
        headers=csrf_headers(ctx["csrf"], key),
    )


def _reject(ctx, version=1, key="reject-1"):
    return ctx["client"].post(
        f"/api/tasks/{ctx['task_id']}/proposals/{version}/reject",
        json={"reason": "not acceptable"},
        headers=csrf_headers(ctx["csrf"], key),
    )


def test_approve_normal_binds_five_elements(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    resp = _approve(ctx)
    assert resp.status_code == 200, resp.text
    event = resp.json()["approval"]
    assert event["decision"] == "approved"
    assert event["requirement_version_id"] == ctx["requirement"]["id"]
    assert event["repo_identity"]
    assert len(event["commit_sha"]) == 40
    assert len(event["proposal_content_hash"]) == 64

    task = ctx["client"].get(f"/api/tasks/{ctx['task_id']}").json()["task"]
    assert task["status"] == "approved"
    assert task["current_approval_id"] == event["id"]

    history = ctx["client"].get(f"/api/tasks/{ctx['task_id']}/approvals").json()["approvals"]
    assert len(history) == 1 and history[0]["effective"] is True


def test_reject(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    resp = _reject(ctx)
    assert resp.status_code == 200, resp.text
    assert resp.json()["approval"]["decision"] == "rejected"
    task = ctx["client"].get(f"/api/tasks/{ctx['task_id']}").json()["task"]
    assert task["status"] == "rejected"

    db = ctx["app"].state.db.session()
    try:
        assert db.query(ApprovalEvent).filter_by(decision="approved").count() == 0
    finally:
        db.close()


def test_unauthenticated_rejected(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    anonymous = TestClient(ctx["app"])
    resp = anonymous.post(f"/api/tasks/{ctx['task_id']}/proposals/1/approve", json={})
    assert resp.status_code == 401


def test_missing_csrf_rejected(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    resp = ctx["client"].post(f"/api/tasks/{ctx['task_id']}/proposals/1/approve", json={})
    assert resp.status_code == 403
    assert resp.json()["code"] == "csrf_failed"
    db = ctx["app"].state.db.session()
    try:
        assert db.query(SecurityEvent).filter_by(kind="approval_csrf_denied").count() >= 1
    finally:
        db.close()


def test_agent_subject_cannot_approve(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    created = ctx["client"].post("/_test/session-role", params={"role": "agent"}).json()
    agent = TestClient(ctx["app"])
    agent.cookies.set("adll_session", created["token"])
    resp = agent.post(
        f"/api/tasks/{ctx['task_id']}/proposals/1/approve",
        json={},
        headers={"X-CSRF-Token": created["csrf_token"]},
    )
    assert resp.status_code == 403
    db = ctx["app"].state.db.session()
    try:
        assert db.query(SecurityEvent).filter_by(kind="approval_role_denied").count() >= 1
    finally:
        db.close()


def test_stale_version_rejected(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    resp = _approve(ctx, version=2)
    assert resp.status_code == 409
    assert resp.json()["code"] == "approval_target_stale"
    db = ctx["app"].state.db.session()
    try:
        assert db.query(ApprovalEvent).count() == 0
    finally:
        db.close()


def test_requirement_change_invalidates_approval(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    assert _approve(ctx).status_code == 200
    ctx["client"].put(
        f"/api/tasks/{ctx['task_id']}/requirement",
        json={"content": "需求 v2"},
        headers=csrf_headers(ctx["csrf"], "k-req2"),
    )
    history = ctx["client"].get(f"/api/tasks/{ctx['task_id']}/approvals").json()["approvals"]
    assert history[0]["effective"] is False
    # 旧审批事件本身保留
    assert len(history) == 1


def test_baseline_change_invalidates_approval(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    assert _approve(ctx).status_code == 200
    (ctx["repo"] / "b.txt").write_text("b\n", encoding="utf-8", newline="\n")
    git(ctx["repo"], "add", "b.txt")
    git(ctx["repo"], "commit", "-m", "second")
    changed = ctx["client"].post(
        f"/api/tasks/{ctx['task_id']}/baseline",
        json={},
        headers=csrf_headers(ctx["csrf"], "k-rebase"),
    )
    assert changed.status_code == 200
    history = ctx["client"].get(f"/api/tasks/{ctx['task_id']}/approvals").json()["approvals"]
    assert history[0]["effective"] is False


@pytest.mark.parametrize(
    "seed,expected",
    [
        ({"verification_status": "failed"}, "verification_not_passed"),
        ({"verification_status": "unconfirmed"}, "verification_not_passed"),
        ({"sufficient": False}, "verification_not_passed"),
        ({"create_verification": False}, "verification_not_passed"),
        ({"execution_status": "failed"}, "verification_not_passed"),
    ],
)
def test_verification_gate_blocks_approval(tmp_path, app_factory, seed, expected) -> None:
    ctx = _setup(tmp_path, app_factory, **seed)
    resp = _approve(ctx)
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == expected


def test_failed_approval_rolls_back_and_audits(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory, verification_status="failed")
    assert _approve(ctx).status_code == 409
    db = ctx["app"].state.db.session()
    try:
        assert db.query(ApprovalEvent).count() == 0
        task = db.get(Task, ctx["task_id"])
        assert task.current_approval_id is None
        assert task.status != "approved"
        assert db.query(AuditLog).filter(AuditLog.action.like("approval_denied:%")).count() >= 1
    finally:
        db.close()


def test_duplicate_approval_rejected(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    assert _approve(ctx, key="a1").status_code == 200
    second = _approve(ctx, key="a2")
    assert second.status_code == 409
    assert second.json()["code"] == "approval_exists"
    db = ctx["app"].state.db.session()
    try:
        assert db.query(ApprovalEvent).filter_by(decision="approved").count() == 1
    finally:
        db.close()


def test_concurrent_approval_produces_one_event(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    app = ctx["app"]
    db1 = app.state.db.session()
    db2 = app.state.db.session()
    barrier = threading.Barrier(2)
    results = []

    def run(db):
        try:
            barrier.wait(timeout=10)
            task = db.get(Task, ctx["task_id"])
            event = approval_service.approve(db, task, 1, "user")
            results.append(("ok", event.id))
        except ApprovalError as exc:
            results.append(("err", exc.code))
        except Exception as exc:  # noqa: BLE001
            results.append(("exc", repr(exc)))
        finally:
            db.close()

    threads = [threading.Thread(target=run, args=(db1,)), threading.Thread(target=run, args=(db2,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert any(item[0] == "ok" for item in results), results
    assert any(item == ("err", "approval_exists") for item in results), results
    db = app.state.db.session()
    try:
        assert db.query(ApprovalEvent).filter_by(decision="approved").count() == 1
    finally:
        db.close()


def test_append_only_proposal_and_approval(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    assert _approve(ctx).status_code == 200
    db = ctx["app"].state.db.session()
    try:
        with pytest.raises(Exception):
            db.execute(
                text("UPDATE proposal_versions SET content='x' WHERE task_id=:t"),
                {"t": ctx["task_id"]},
            )
            db.commit()
        db.rollback()
        with pytest.raises(Exception):
            db.execute(
                text("UPDATE approval_events SET reason='x' WHERE task_id=:t"),
                {"t": ctx["task_id"]},
            )
            db.commit()
        db.rollback()
        with pytest.raises(Exception):
            db.execute(
                text("DELETE FROM approval_events WHERE task_id=:t"), {"t": ctx["task_id"]}
            )
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_idempotent_replay_and_conflict(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    first = _approve(ctx, version=1, key="same")
    second = _approve(ctx, version=1, key="same")
    assert first.status_code == 200 and second.status_code == 200
    assert second.json().get("replayed") is True
    assert first.json()["approval"]["id"] == second.json()["approval"]["id"]

    conflict = _approve(ctx, version=2, key="same")
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"


def test_restart_recomputes_validity(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    assert _approve(ctx).status_code == 200

    app2 = app_factory()
    client2, csrf2 = login_client(app2)
    history = client2.get(f"/api/tasks/{ctx['task_id']}/approvals").json()["approvals"]
    assert history[0]["effective"] is True

    client2.put(
        f"/api/tasks/{ctx['task_id']}/requirement",
        json={"content": "v2"},
        headers=csrf_headers(csrf2, "r2"),
    )
    history = client2.get(f"/api/tasks/{ctx['task_id']}/approvals").json()["approvals"]
    assert history[0]["effective"] is False