"""出站授权 API：创建/查询/撤销 + 撤销后零发送。"""
from __future__ import annotations

from tests.helpers import csrf_headers, login_client, make_repo


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
    return app, client, csrf, task, repo


def test_create_list_revoke(tmp_path, app_factory) -> None:
    app, client, csrf, task, _repo = _setup(tmp_path, app_factory)
    created = client.post(
        f"/api/tasks/{task['id']}/outbound-authorizations",
        json={"receiver": "dashscope", "send_scope": {"paths": ["a.txt"]}},
        headers=csrf_headers(csrf, "auth-1"),
    )
    assert created.status_code == 200, created.text
    auth = created.json()["authorization"]
    assert auth["status"] == "approved"
    assert auth["receiver"] == "dashscope"

    listed = client.get(f"/api/tasks/{task['id']}/outbound-authorizations").json()
    assert len(listed["authorizations"]) == 1

    revoked = client.post(
        f"/api/outbound-authorizations/{auth['id']}/revoke",
        headers=csrf_headers(csrf, "revoke-1"),
    )
    assert revoked.status_code == 200
    assert revoked.json()["authorization"]["status"] == "revoked"


def test_revoked_authorization_blocks_generation_zero_send(tmp_path, app_factory) -> None:
    app, client, csrf, task, _repo = _setup(tmp_path, app_factory)
    created = client.post(
        f"/api/tasks/{task['id']}/outbound-authorizations",
        json={"receiver": "dashscope", "send_scope": {"paths": ["a.txt"]}},
        headers=csrf_headers(csrf, "auth-2"),
    ).json()["authorization"]
    client.post(
        f"/api/outbound-authorizations/{created['id']}/revoke",
        headers=csrf_headers(csrf, "revoke-2"),
    )
    resp = client.post(
        f"/api/tasks/{task['id']}/generations",
        json={"authorization_id": created["id"]},
        headers=csrf_headers(csrf, "gen-revoked"),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "outbound_denied"


def test_authorization_requires_auth_and_csrf(tmp_path, app_factory) -> None:
    app, client, csrf, task, _repo = _setup(tmp_path, app_factory)
    no_csrf = client.post(
        f"/api/tasks/{task['id']}/outbound-authorizations",
        json={"receiver": "dashscope"},
    )
    assert no_csrf.status_code == 403

    from fastapi.testclient import TestClient

    anonymous = TestClient(app)
    assert (
        anonymous.get(f"/api/tasks/{task['id']}/outbound-authorizations").status_code
        == 401
    )