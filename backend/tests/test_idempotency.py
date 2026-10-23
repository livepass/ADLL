"""幂等：重放 / 异摘要冲突 / 并发不重复执行 / 重启后仍可重放。"""
from __future__ import annotations

import threading

import pytest

from app.services.idempotency import execute


def _headers(auth, key):
    return {"X-CSRF-Token": auth["csrf_token"], "Idempotency-Key": key}


def test_replay_same_request(client, auth) -> None:
    h = _headers(auth, "k-replay")
    r1 = client.post("/_test/idempotent", json={"v": 1}, headers=h)
    r2 = client.post("/_test/idempotent", json={"v": 1}, headers=h)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["counter"] == 1
    assert r2.json()["counter"] == 1
    assert r2.json()["replayed"] is True


def test_conflict_different_request(client, auth) -> None:
    h = _headers(auth, "k-conflict")
    assert client.post("/_test/idempotent", json={"v": 1}, headers=h).status_code == 200
    r2 = client.post("/_test/idempotent", json={"v": 2}, headers=h)
    assert r2.status_code == 409
    assert r2.json()["code"] == "idempotency_conflict"


def test_no_key_executes_each_time(client, auth) -> None:
    h = {"X-CSRF-Token": auth["csrf_token"]}
    r1 = client.post("/_test/idempotent", json={"v": 1}, headers=h)
    r2 = client.post("/_test/idempotent", json={"v": 1}, headers=h)
    assert r1.json()["counter"] != r2.json()["counter"]


def test_concurrent_same_key_executes_once(app) -> None:
    db1 = app.state.db.session()
    db2 = app.state.db.session()
    started = threading.Event()
    release = threading.Event()
    calls = {"n": 0}

    def handler():
        calls["n"] += 1
        started.set()
        release.wait(timeout=10)
        return 200, {"ok": True}

    results = {}

    def run1():
        results["1"] = execute(db1, "k-conc", "scope", b"payload", handler)

    def run2():
        results["2"] = execute(db2, "k-conc", "scope", b"payload", handler)

    t1 = threading.Thread(target=run1)
    t2 = threading.Thread(target=run2)
    try:
        t1.start()
        assert started.wait(timeout=10), "handler did not start"
        t2.start()  # 在 winner 仍处理中时发起
        t2.join(timeout=10)
        assert calls["n"] == 1, "handler must run once"
        assert results["2"][0] == 409
        assert results["2"][1]["code"] == "idempotency_in_progress"
        release.set()
        t1.join(timeout=10)
        assert results["1"][0] == 200
    finally:
        release.set()
        db1.close()
        db2.close()


def test_restart_replay(app_factory, db_path) -> None:
    app1 = app_factory()
    db1 = app1.state.db.session()
    try:
        r1 = execute(db1, "k-restart", "scope", b"p", lambda: (201, {"v": 1}))
        assert r1 == (201, {"v": 1}, False)
    finally:
        db1.close()
    app1.state.db.engine.dispose()

    app2 = app_factory()  # 同一 SQLite 文件的新进程/新引擎
    db2 = app2.state.db.session()
    calls = {"n": 0}

    def handler():
        calls["n"] += 1
        return 200, {"v": 2}

    try:
        status, body, replayed = execute(db2, "k-restart", "scope", b"p", handler)
        assert (status, body, replayed) == (201, {"v": 1}, True)
        assert calls["n"] == 0
    finally:
        db2.close()