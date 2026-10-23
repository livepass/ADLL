"""ADLL_TESTING 配置隔离：测试路由/Mock/隔离检查/数据库隔离/标记。"""
from __future__ import annotations

import dataclasses

import pytest

from app.agents.factory import NoRealAdapterAvailable, get_adapter
from app.main import create_app
from app.models.generation import GenerationExecution
from tests.helpers import (
    csrf_headers,
    login_client,
    make_repo,
    make_settings,
    seed_authorization,
)


def test_production_does_not_register_test_routes(tmp_path) -> None:
    app = create_app(make_settings(f"sqlite:///{tmp_path/'prod.db'}", testing=False))
    app.state.db.create_all()
    client, _csrf = login_client(app)
    assert client.get("/_test/secure").status_code == 404
    assert client.post("/_test/session-role").status_code == 404


def test_production_factory_refuses_mock(tmp_path) -> None:
    settings = make_settings(f"sqlite:///{tmp_path/'prod2.db'}", testing=False)
    with pytest.raises(NoRealAdapterAvailable):
        get_adapter(settings)


def test_real_ai_enabled_but_isolation_unverified_blocks(tmp_path) -> None:
    repo = make_repo(tmp_path)
    base = make_settings(
        f"sqlite:///{tmp_path/'real.db'}",
        testing=False,
        authorized_roots=(str(tmp_path),),
    )
    settings = dataclasses.replace(base, real_ai_enabled=True)
    app = create_app(settings)
    app.state.db.create_all()
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
    resp = client.post(
        f"/api/tasks/{task['id']}/generations",
        json={"authorization_id": auth_id},
        headers=csrf_headers(csrf, "gen-real"),
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "isolation_unverified"
    db = app.state.db.session()
    try:
        assert db.query(GenerationExecution).count() == 0  # 零发送/零执行
    finally:
        db.close()


def test_mock_results_are_marked_synthetic(tmp_path) -> None:
    repo = make_repo(tmp_path)
    app = create_app(
        make_settings(
            f"sqlite:///{tmp_path/'mock.db'}",
            testing=True,
            authorized_roots=(str(tmp_path),),
        )
    )
    app.state.db.create_all()
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
    resp = client.post(
        f"/api/tasks/{task['id']}/generations",
        json={"authorization_id": auth_id},
        headers=csrf_headers(csrf, "gen-mock"),
    )
    assert resp.status_code == 202, resp.text
    execution_id = resp.json()["execution_id"]
    import time

    for _ in range(200):
        detail = client.get(f"/api/generations/{execution_id}").json()
        if detail["execution"]["status"] in {"completed", "failed", "timeout", "cancelled"}:
            break
        time.sleep(0.02)
    detail = client.get(f"/api/generations/{execution_id}").json()
    assert detail["execution"]["provider"] == "mock"
    assert detail["verification"]["status"] == "verified"
    db = app.state.db.session()
    try:
        execution = db.get(GenerationExecution, execution_id)
        assert execution.provider == "mock"
    finally:
        db.close()


def test_test_and_production_databases_isolated(tmp_path) -> None:
    test_app = create_app(make_settings(f"sqlite:///{tmp_path/'a.db'}", testing=True))
    prod_app = create_app(make_settings(f"sqlite:///{tmp_path/'b.db'}", testing=False))
    test_app.state.db.create_all()
    prod_app.state.db.create_all()
    assert test_app.state.settings.database_url != prod_app.state.settings.database_url
    # 两个库互不共享数据
    a = test_app.state.db.session()
    b = prod_app.state.db.session()
    try:
        from app.models.repository import AnalysisBaseline, GitRepository
        from app.models.task import Task

        repo = GitRepository(
            path=str(tmp_path), repo_identity="isolated", object_format="sha1"
        )
        a.add(repo)
        a.flush()
        baseline = AnalysisBaseline(
            repository_id=repo.id,
            commit_sha="0" * 40,
            object_format="sha1",
            workspace_decision="committed_only",
        )
        a.add(baseline)
        a.flush()
        a.add(
            Task(
                repository_id=repo.id,
                baseline_id=baseline.id,
                title="only-a",
            )
        )
        a.commit()
        assert b.query(Task).count() == 0
    finally:
        a.close()
        b.close()