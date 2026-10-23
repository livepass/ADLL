"""任务与需求版本 API：创建/查询/不可变版本/并发/基准不漂移/幂等。"""
from __future__ import annotations

import threading

from app.models.task import RequirementVersion, Task
from app.services import task_service
from tests.helpers import csrf_headers, git, login_client, make_repo


def _setup(tmp_path, app_factory):
    repo = make_repo(tmp_path)
    app = app_factory(authorized_roots=(str(tmp_path),))
    client, csrf = login_client(app)
    linked = client.post(
        "/api/repositories/link", json={"path": str(repo)}, headers=csrf_headers(csrf)
    ).json()
    return {
        "app": app,
        "client": client,
        "csrf": csrf,
        "repo": repo,
        "repo_id": linked["repository"]["id"],
        "baseline_id": linked["baseline"]["id"],
    }


def _create_task(ctx, key="k-task"):
    return ctx["client"].post(
        "/api/tasks",
        json={
            "repository_id": ctx["repo_id"],
            "baseline_id": ctx["baseline_id"],
            "title": "T1",
        },
        headers=csrf_headers(ctx["csrf"], key),
    )


def test_create_list_detail(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    resp = _create_task(ctx)
    assert resp.status_code == 200, resp.text
    task = resp.json()["task"]
    assert task["current_requirement_version"] is None

    listed = ctx["client"].get("/api/tasks").json()["tasks"]
    assert len(listed) == 1
    detail = ctx["client"].get(f"/api/tasks/{task['id']}").json()["task"]
    assert detail["title"] == "T1"


def test_requirement_versions_immutable(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    task_id = _create_task(ctx).json()["task"]["id"]
    r1 = ctx["client"].put(
        f"/api/tasks/{task_id}/requirement",
        json={"content": "v1"},
        headers=csrf_headers(ctx["csrf"], "r1"),
    )
    assert r1.status_code == 200 and r1.json()["requirement_version"]["seq"] == 1
    r2 = ctx["client"].put(
        f"/api/tasks/{task_id}/requirement",
        json={"content": "v2"},
        headers=csrf_headers(ctx["csrf"], "r2"),
    )
    assert r2.status_code == 200 and r2.json()["requirement_version"]["seq"] == 2

    detail = ctx["client"].get(f"/api/tasks/{task_id}").json()["task"]
    assert detail["current_requirement_version"]["seq"] == 2
    assert detail["current_requirement_version"]["content"] == "v2"

    db = ctx["app"].state.db.session()
    try:
        assert db.query(RequirementVersion).filter_by(task_id=task_id).count() == 2
    finally:
        db.close()


def test_requirement_concurrent_seq(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    task_id = _create_task(ctx).json()["task"]["id"]
    app = ctx["app"]
    barrier = threading.Barrier(2)
    errors = []

    def run(content):
        db = app.state.db.session()
        try:
            barrier.wait(timeout=10)
            task = db.get(Task, task_id)
            task_service.save_requirement(db, task, content)
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
        finally:
            db.close()

    threads = [
        threading.Thread(target=run, args=("a",)),
        threading.Thread(target=run, args=("b",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert not errors, errors
    db = app.state.db.session()
    try:
        seqs = sorted(
            v.seq for v in db.query(RequirementVersion).filter_by(task_id=task_id).all()
        )
    finally:
        db.close()
    assert seqs == [1, 2]


def test_baseline_does_not_drift_on_head_change(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    task = _create_task(ctx).json()["task"]
    task_id = task["id"]
    original_baseline_id = task["baseline_id"]
    db = ctx["app"].state.db.session()
    try:
        from app.models.repository import AnalysisBaseline

        original_commit = db.get(AnalysisBaseline, original_baseline_id).commit_sha
    finally:
        db.close()

    (ctx["repo"] / "b.txt").write_text("b\n", encoding="utf-8", newline="\n")
    git(ctx["repo"], "add", "b.txt")
    git(ctx["repo"], "commit", "-m", "second")

    unchanged = ctx["client"].get(f"/api/tasks/{task_id}").json()["task"]
    assert unchanged["baseline_id"] == original_baseline_id

    changed = ctx["client"].post(
        f"/api/tasks/{task_id}/baseline",
        json={},
        headers=csrf_headers(ctx["csrf"], "k-rebase"),
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["baseline_id"] != original_baseline_id
    assert body["baseline"]["commit_sha"] != original_commit


def test_idempotent_create_replay(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    first = _create_task(ctx, key="same-key")
    second = _create_task(ctx, key="same-key")
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["task"]["id"] == second.json()["task"]["id"]
    assert second.json().get("replayed") is True


def test_conflict_and_auth_csrf(tmp_path, app_factory) -> None:
    ctx = _setup(tmp_path, app_factory)
    first = _create_task(ctx, key="c-key")
    assert first.status_code == 200
    # 同键不同请求 → 409
    conflict = ctx["client"].post(
        "/api/tasks",
        json={
            "repository_id": ctx["repo_id"],
            "baseline_id": ctx["baseline_id"],
            "title": "different",
        },
        headers=csrf_headers(ctx["csrf"], "c-key"),
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"

    # 缺 CSRF
    no_csrf = ctx["client"].post(
        "/api/tasks",
        json={
            "repository_id": ctx["repo_id"],
            "baseline_id": ctx["baseline_id"],
            "title": "x",
        },
    )
    assert no_csrf.status_code == 403