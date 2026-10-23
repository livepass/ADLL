"""仓库关联 API：合法/脏工作区/非法/未授权 + 认证/CSRF。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.helpers import csrf_headers, login_client, make_repo


def test_link_clean_creates_baseline(tmp_path, app_factory) -> None:
    repo = make_repo(tmp_path)
    app = app_factory(authorized_roots=(str(tmp_path),))
    client, csrf = login_client(app)
    resp = client.post(
        "/api/repositories/link", json={"path": str(repo)}, headers=csrf_headers(csrf)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["needs_decision"] is False
    assert body["baseline"] is not None
    assert body["baseline"]["available"] is True
    assert body["repository"]["object_format"] == "sha1"
    assert len(body["baseline"]["commit_sha"]) == 40


def test_link_dirty_requires_decision_then_baseline(tmp_path, app_factory) -> None:
    repo = make_repo(tmp_path)
    (repo / "a.txt").write_text("changed\n", encoding="utf-8", newline="\n")
    app = app_factory(authorized_roots=(str(tmp_path),))
    client, csrf = login_client(app)
    resp = client.post(
        "/api/repositories/link", json={"path": str(repo)}, headers=csrf_headers(csrf)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["needs_decision"] is True
    assert body["baseline"] is None
    repo_id = body["repository"]["id"]

    decided = client.post(
        f"/api/repositories/{repo_id}/workspace-decision",
        json={"decision": "accept_uncommitted"},
        headers=csrf_headers(csrf),
    )
    assert decided.status_code == 200, decided.text
    baseline = decided.json()["baseline"]
    assert baseline["workspace_decision"] == "accept_uncommitted"
    assert baseline["available"] is True


def test_link_invalid_and_non_git(tmp_path, app_factory) -> None:
    app = app_factory(authorized_roots=(str(tmp_path),))
    client, csrf = login_client(app)
    resp = client.post(
        "/api/repositories/link",
        json={"path": str(tmp_path / "nope")},
        headers=csrf_headers(csrf),
    )
    assert resp.status_code == 400 and resp.json()["code"] == "invalid_path"

    plain = tmp_path / "plain"
    plain.mkdir()
    resp = client.post(
        "/api/repositories/link",
        json={"path": str(plain)},
        headers=csrf_headers(csrf),
    )
    assert resp.status_code == 400 and resp.json()["code"] == "not_git_repository"


def test_link_unauthorized_root(tmp_path, app_factory) -> None:
    repo = make_repo(tmp_path)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    app = app_factory(authorized_roots=(str(allowed),))
    client, csrf = login_client(app)
    resp = client.post(
        "/api/repositories/link", json={"path": str(repo)}, headers=csrf_headers(csrf)
    )
    assert resp.status_code == 400 and resp.json()["code"] == "path_not_authorized"


def test_link_requires_auth_and_csrf(tmp_path, app_factory) -> None:
    repo = make_repo(tmp_path)
    app = app_factory(authorized_roots=(str(tmp_path),))
    anonymous = TestClient(app)
    assert (
        anonymous.post("/api/repositories/link", json={"path": str(repo)}).status_code
        == 401
    )
    client, _csrf = login_client(app)
    assert (
        client.post("/api/repositories/link", json={"path": str(repo)}).status_code
        == 403
    )


def test_active_repository(tmp_path, app_factory) -> None:
    repo = make_repo(tmp_path)
    app = app_factory(authorized_roots=(str(tmp_path),))
    client, csrf = login_client(app)
    client.post(
        "/api/repositories/link", json={"path": str(repo)}, headers=csrf_headers(csrf)
    )
    resp = client.get("/api/repositories/active")
    assert resp.status_code == 200
    body = resp.json()
    assert body["repository"]["active"] is True
    assert body["baseline"]["available"] is True