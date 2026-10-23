"""批 8：WorkerAgentAdapter 集成测试（真实受限进程、合成模式，无真实网络）。"""
from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from pathlib import Path

import pytest

from app.agents.base import GenerationRequest
from app.agents.dashscope import AdapterDisabled
from app.agents.worker import WorkerAgentAdapter
from app.models.outbound import OutboundAuthorization
from app.models.task import Task
from app.services import generation_service
from app.services.outbound_pipeline import prepare as prepare_outbound
from tests.helpers import (
    csrf_headers,
    login_client,
    make_repo,
    seed_authorization,
)

pytestmark = [
    pytest.mark.skipif(os.name != "nt", reason="Windows-only restricted worker"),
]

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture()
def iso_root():
    root = Path(tempfile.mkdtemp(prefix=f"adll-iso-{uuid.uuid4().hex[:8]}-", dir=BACKEND))
    try:
        yield root
    finally:
        import shutil

        shutil.rmtree(root, ignore_errors=True)


def _protected(root: Path) -> dict[str, Path]:
    repo = root / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    db = root / "approval.db"
    db.write_text("DB", encoding="utf-8")
    return {"repo": repo, "db": db}


def _adapter(root: Path, protected: dict[str, Path], **kwargs) -> WorkerAgentAdapter:
    worker_root = root / "worker"
    worker_root.mkdir(exist_ok=True)
    return WorkerAgentAdapter(
        endpoint="https://dashscope.aliyuncs.com/apps/anthropic/v1/messages",
        model="m",
        sandbox_root=worker_root,
        acl_root=root,
        deny_read=(str(protected["repo"]), str(protected["db"])),
        deny_write=(str(protected["db"]),),
        **kwargs,
    )


def _request(text: str = "REQ") -> GenerationRequest:
    return GenerationRequest(
        subset_path=None,
        requirement_text=text,
        feedback_texts=[],
        send_manifest={"source": []},
        payload={"model": "m", "max_tokens": 256, "messages": []},
    )


def test_self_check_is_evidence_based(iso_root) -> None:
    protected = _protected(iso_root)
    report = _adapter(iso_root, protected, synthetic=True).self_check()
    assert report.ok is True
    assert report.details["worker_isolation"] == "verified"
    evidence = report.details["evidence"]
    assert evidence["token_restricted"] is True
    assert evidence["allowed_digest_match"] is True
    assert all(item["denied"] for item in evidence["deny_read"].values())
    assert all(item["denied"] for item in evidence["deny_write"].values())


def test_self_check_fails_without_deny_objects(iso_root) -> None:
    adapter = WorkerAgentAdapter(
        endpoint="https://example.invalid",
        model="m",
        sandbox_root=iso_root,
        acl_root=iso_root,
        synthetic=True,
    )
    report = adapter.self_check()
    assert report.ok is False
    assert report.details["error"] == "config"


def test_self_check_fails_when_deny_path_missing(iso_root) -> None:
    adapter = WorkerAgentAdapter(
        endpoint="https://example.invalid",
        model="m",
        sandbox_root=iso_root,
        acl_root=iso_root,
        deny_read=(str(iso_root / "missing"),),
        synthetic=True,
    )
    assert adapter.self_check().ok is False


def test_generate_synthetic_uses_restricted_worker(iso_root) -> None:
    protected = _protected(iso_root)
    adapter = _adapter(iso_root, protected, synthetic=True)
    result = adapter.generate(_request("HELLO"))
    assert result.text.startswith("SYNTHETIC_WORKER_PLAN: HELLO")
    assert result.usage_basis == "unavailable"
    assert result.cost["basis"] == "unknown"
    assert result.cost["amount"] is None
    assert result.tool_call_log == []
    assert adapter.capabilities().declares["tools"] is False


def test_real_mode_fails_closed_without_transport_flag(iso_root) -> None:
    protected = _protected(iso_root)
    adapter = _adapter(iso_root, protected, synthetic=False, real_transport=False)
    assert adapter.self_check().ok is True  # 隔离探针通过，但真实传输仍关闭
    with pytest.raises(AdapterDisabled):
        adapter.generate(_request())


def test_generate_refuses_when_probe_fails(iso_root) -> None:
    adapter = WorkerAgentAdapter(
        endpoint="https://example.invalid",
        model="m",
        sandbox_root=iso_root,
        acl_root=iso_root,
        deny_read=(str(iso_root / "missing"),),
        synthetic=True,
    )
    with pytest.raises(AdapterDisabled):
        adapter.generate(_request())


def test_generation_service_uses_worker_without_repo_access(tmp_path, app_factory) -> None:
    repo = make_repo(tmp_path)
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
            "title": "T",
        },
        headers=csrf_headers(csrf, "worker-task"),
    ).json()["task"]
    client.put(
        f"/api/tasks/{task['id']}/requirement",
        json={"content": "需求"},
        headers=csrf_headers(csrf, "worker-req"),
    )
    auth_id = seed_authorization(
        app,
        task["id"],
        scope={"paths": ["a.txt"]},
        receiver="https://dashscope.aliyuncs.com/apps/anthropic/v1/messages",
    )

    db = app.state.db.session()
    try:
        task_obj = db.get(Task, task["id"])
        auth = db.get(OutboundAuthorization, auth_id)
        protected = {"repo": repo, "db": tmp_path / "test.db"}
        adapter = _adapter(tmp_path, protected, synthetic=True)
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
            requirement_text="需求",
            feedback_texts=[],
            source_items=items,
            model="m",
        )
        execution, verification, proposal = generation_service.start(
            db,
            task_obj,
            auth,
            requirement_text="需求",
            feedback_texts=[],
            source_items=items,
            model="m",
            adapter=adapter,
            preview_digest=preview.request_digest,
            testing=False,
        )
        assert execution.status == "completed"
        assert verification.status == "unconfirmed"
        assert proposal is None  # 非 testing：worker 结果不自动判 verified
    finally:
        db.close()