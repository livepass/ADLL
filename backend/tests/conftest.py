"""pytest 夹具：隔离临时 SQLite；不操作既有用户数据。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.helpers import ADMIN_PW, make_settings


@pytest.fixture()
def db_path(tmp_path) -> str:
    return str(tmp_path / "test.db")


@pytest.fixture()
def app_factory(db_path):
    created = []

    def make(database_url: str | None = None, testing: bool = True, authorized_roots=()):
        application = create_app(
            make_settings(database_url or f"sqlite:///{db_path}", testing, tuple(authorized_roots))
        )
        application.state.db.create_all()
        created.append(application)
        return application

    yield make
    for application in created:
        application.state.db.engine.dispose()


@pytest.fixture()
def app(app_factory):
    return app_factory()


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def auth(client) -> dict:
    resp = client.post("/api/auth/login", json={"password": ADMIN_PW})
    assert resp.status_code == 200, resp.text
    return resp.json()