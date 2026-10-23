"""批 8：敏感 canary 全链路扫描（日志、序列化 worker job/result、SQLite 字节）。

只使用合成仓库与临时数据库；不读取真实凭据或真实业务仓库。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import uuid
from pathlib import Path

import pytest

from app.agents.worker import WorkerAgentAdapter
from app.models.outbound import OutboundAuthorization
from app.models.task import Task
from app.services import generation_service
from app.services.outbound_pipeline import prepare as prepare_outbound
from tests.helpers import (
    RECEIVER_WORKER,
    csrf_headers,
    git,
    login_client,
    make_repo,
    seed_authorization,
)

pytestmark = [pytest.mark.skipif(os.name != "nt", reason="Windows-only worker")]

BACKEND = Path(__file__).resolve().parents[1]
CANARY = "CANARY-SECRET-8f2c1d-DO-NOT-LEAK"


@pytest.fixture()
def iso_root():
    root = Path(tempfile.mkdtemp(prefix=f"adll-iso-{uuid.uuid4().hex[:8]}-", dir=BACKEND))
    try:
        yield root
    finally:
        import shutil

        shutil.rmtree(root, ignore_errors=True)


def test_sensitive_canary_absent_from_logs_serialization_and_db(
    tmp_path, app_factory, caplog
) -> None:
    repo = make_repo(tmp_path)
    (repo / ".env").write_text(f"API_KEY={CANARY}\n", encoding="utf-8", newline="\n")
    git(repo, "add", ".env")
    git(repo, "commit", "-m", "canary")

    app = app_factory(authorized_roots=(str(tmp_path),), testing=False)
    client, csrf = login_client(app)
    linked = client.post(
        "/api/repositories/link", json={"path": str(repo)}, headers=csrf_headers(csrf)
    ).json()
    task = client.post(
        "/api/tasks",
        json={
            "repository_id": linked["repository"]["id"],
            "baseline_id": linked["baseline"]["id"],
            "title": "canary",
        },
        headers=csrf_headers(csrf, "canary-task"),
    ).json()["task"]
    client.put(
        f"/api/tasks/{task['id']}/requirement",
        json={"content": "仅发送 a.txt"},
        headers=csrf_headers(csrf, "canary-req"),
    )
    auth_id = seed_authorization(
        app, task["id"], scope={"paths": ["a.txt"]}, receiver=RECEIVER_WORKER
    )

    worker_root = tmp_path / "worker"
    worker_root.mkdir()
    adapter = WorkerAgentAdapter(
        endpoint="https://example.invalid/v1/messages",
        model="m",
        sandbox_root=worker_root,
        acl_root=tmp_path,
        deny_read=(str(repo), str(tmp_path / "test.db")),
        deny_write=(str(tmp_path / "test.db"),),
        synthetic=True,
    )

    db = app.state.db.session()
    try:
        task_obj = db.get(Task, task["id"])
        auth = db.get(OutboundAuthorization, auth_id)
        content = (repo / "a.txt").read_text(encoding="utf-8")
        items = [
            {
                "path": "a.txt",
                "content": content,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
        ]
        preview = prepare_outbound(
            task=task_obj,
            auth=auth,
            receiver=adapter.endpoint,
            requirement_text="仅发送 a.txt",
            feedback_texts=[],
            source_items=items,
            model="m",
        )
        with caplog.at_level(logging.DEBUG):
            execution, _verification, _proposal = generation_service.start(
                db,
                task_obj,
                auth,
                requirement_text="仅发送 a.txt",
                feedback_texts=[],
                source_items=items,
                model="m",
                adapter=adapter,
                preview_digest=preview.request_digest,
                testing=False,
            )
        assert execution.status == "completed"
    finally:
        db.close()

    assert adapter.last_job is not None and adapter.last_result is not None
    serialized = json.dumps(
        {"job": adapter.last_job, "result": adapter.last_result}, ensure_ascii=False
    )
    assert CANARY not in serialized
    assert CANARY not in caplog.text
    assert CANARY not in Path(tmp_path / "test.db").read_bytes().decode(
        "latin-1", errors="ignore"
    )
    # worker 只接收 payload，不接收仓库路径/凭据。
    job_text = json.dumps(adapter.last_job, ensure_ascii=False)
    assert str(repo) not in job_text
    assert "DASHSCOPE_API_KEY" not in job_text