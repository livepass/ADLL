"""会话认证与 CSRF：正常 + 异常（未认证/缺 CSRF/非用户主体/localhost 不豁免）。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.helpers import ADMIN_PW


def test_login_wrong_password(client) -> None:
    resp = client.post("/api/auth/login", json={"password": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "invalid_credentials"


def test_login_ok_sets_httponly_cookie(client) -> None:
    resp = client.post("/api/auth/login", json={"password": ADMIN_PW})
    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert "adll_session=" in set_cookie
    assert "httponly" in set_cookie
    assert resp.json()["role"] == "user"


def test_me_requires_login(client) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_login(client) -> None:
    login = client.post("/api/auth/login", json={"password": ADMIN_PW})
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["role"] == "user"
    # 刷新后由已认证同源会话重新下发 CSRF 同步器令牌（不落持久化存储）。
    assert resp.json()["csrf_token"] == login.json()["csrf_token"]


def test_localhost_not_trusted(client) -> None:
    # 测试客户端来自回环地址，但未认证 → 仍 401
    assert client.get("/_test/secure").status_code == 401


def test_csrf_missing_rejected(client, auth) -> None:
    resp = client.post("/_test/csrf-action")
    assert resp.status_code == 403
    assert resp.json()["code"] == "csrf_failed"


def test_csrf_invalid_rejected(client, auth) -> None:
    resp = client.post("/_test/csrf-action", headers={"X-CSRF-Token": "bad"})
    assert resp.status_code == 403


def test_csrf_valid_accepted(client, auth) -> None:
    resp = client.post("/_test/csrf-action", headers={"X-CSRF-Token": auth["csrf_token"]})
    assert resp.status_code == 200


def test_agent_role_rejected(app, client) -> None:
    created = client.post("/_test/session-role", params={"role": "agent"})
    assert created.status_code == 200
    token = created.json()["token"]
    csrf = created.json()["csrf_token"]
    agent_client = TestClient(app)
    agent_client.cookies.set("adll_session", token)
    assert agent_client.get("/_test/secure").status_code == 403
    assert (
        agent_client.post(
            "/_test/csrf-action", headers={"X-CSRF-Token": csrf}
        ).status_code
        == 403
    )


def test_logout_revokes_session(client, auth) -> None:
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401