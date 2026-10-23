"""出站授权 API：创建/查询/撤销 + 撤销后零发送。"""
from __future__ import annotations

import hashlib

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
        json={"receiver": "mock://local", "send_scope": {"paths": ["a.txt"]}},
        headers=csrf_headers(csrf, "auth-1"),
    )
    assert created.status_code == 200, created.text
    auth = created.json()["authorization"]
    assert auth["status"] == "approved"
    assert auth["receiver"] == "mock://local"

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
        json={"receiver": "mock://local", "send_scope": {"paths": ["a.txt"]}},
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
        json={"receiver": "mock://local"},
    )
    assert no_csrf.status_code == 403

    from fastapi.testclient import TestClient

    anonymous = TestClient(app)
    assert (
        anonymous.get(f"/api/tasks/{task['id']}/outbound-authorizations").status_code
        == 401
    )

def test_create_rejects_empty_scope_for_source(tmp_path, app_factory) -> None:
    _app, client, csrf, task, _repo = _setup(tmp_path, app_factory)
    resp = client.post(
        f"/api/tasks/{task['id']}/outbound-authorizations",
        json={"receiver": "mock://local", "data_types": ["requirement", "source"], "send_scope": {}},
        headers=csrf_headers(csrf, "auth-empty-scope"),
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "scope_required"


def test_create_rejects_bare_receiver_label(tmp_path, app_factory) -> None:
    _app, client, csrf, task, _repo = _setup(tmp_path, app_factory)
    resp = client.post(
        f"/api/tasks/{task['id']}/outbound-authorizations",
        json={"receiver": "dashscope", "send_scope": {"paths": ["a.txt"]}},
        headers=csrf_headers(csrf, "auth-bare-receiver"),
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_receiver"


def test_create_rejects_tool_return_and_paths_without_source(tmp_path, app_factory) -> None:
    _app, client, csrf, task, _repo = _setup(tmp_path, app_factory)
    tool = client.post(
        f"/api/tasks/{task['id']}/outbound-authorizations",
        json={"receiver": "mock://local", "data_types": ["requirement", "tool_return"],
              "send_scope": {"paths": ["a.txt"]}},
        headers=csrf_headers(csrf, "auth-tool"),
    )
    assert tool.status_code == 400

    mismatch = client.post(
        f"/api/tasks/{task['id']}/outbound-authorizations",
        json={"receiver": "mock://local", "data_types": ["requirement"],
              "send_scope": {"paths": ["a.txt"]}},
        headers=csrf_headers(csrf, "auth-paths-no-source"),
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["code"] == "invalid_scope"


def test_preview_shows_scope_and_digests_without_sending(tmp_path, app_factory) -> None:
    _app, client, csrf, task, _repo = _setup(tmp_path, app_factory)
    auth = client.post(
        f"/api/tasks/{task['id']}/outbound-authorizations",
        json={"receiver": "mock://local", "send_scope": {"paths": ["a.txt"]}},
        headers=csrf_headers(csrf, "auth-preview"),
    ).json()["authorization"]
    preview = client.post(
        f"/api/tasks/{task['id']}/generations/preview",
        json={"authorization_id": auth["id"]},
        headers=csrf_headers(csrf, "preview-1"),
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["receiver"] == "mock://local"
    assert body["testing"] is True  # 合成标识：Mock 模式不冒充真实服务商
    assert body["model"]
    assert [item["path"] for item in body["source"]] == ["a.txt"]
    assert len(body["request_digest"]) == 64
    assert len(body["snapshot"]["digest"]) == 64
    assert len(body["requirement"]["sha256"]) == 64
    # 逐字确认：必须返回真实内容，而不是只给哈希。
    repo_file = (_repo / "a.txt").read_text(encoding="utf-8")
    assert body["source"][0]["content"] == repo_file
    assert body["requirement"]["content"] == "需求"
    assert body["message"]["content"].startswith("## Requirement")
    assert repo_file in body["message"]["content"]
    assert (
        hashlib.sha256(body["message"]["content"].encode("utf-8")).hexdigest()
        == body["message"]["sha256"]
    )


def test_preview_digest_changes_when_feedback_changes(tmp_path, app_factory) -> None:
    """预览后修改反馈：摘要必须变化，旧确认随之失效。"""
    _app, client, csrf, task, _repo = _setup(tmp_path, app_factory)
    auth = client.post(
        f"/api/tasks/{task['id']}/outbound-authorizations",
        json={"receiver": "mock://local", "send_scope": {"paths": ["a.txt"]}},
        headers=csrf_headers(csrf, "auth-preview-2"),
    ).json()["authorization"]

    def preview(feedback: list[str]) -> dict:
        resp = client.post(
            f"/api/tasks/{task['id']}/generations/preview",
            json={"authorization_id": auth["id"], "feedback": feedback},
            headers=csrf_headers(csrf, "preview-fb"),
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    first = preview([])
    second = preview(["补充说明"])
    assert first["request_digest"] != second["request_digest"]
    assert second["feedback"][0]["content"] == "补充说明"
    assert "补充说明" in second["message"]["content"]


def test_outbound_receiver_endpoint(tmp_path, app_factory) -> None:
    _app, client, _csrf, _task, _repo = _setup(tmp_path, app_factory)
    body = client.get("/api/outbound/receiver").json()
    assert body["receiver"] == "mock://local"
    assert body["testing"] is True
