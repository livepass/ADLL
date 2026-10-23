"""测试共享工具。"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings

ADMIN_PW = "test-password-123"

# 接收方必须是完整端点；Mock 与测试用适配器各自有固定端点。
RECEIVER_MOCK = "mock://local"
RECEIVER_WORKER = "https://example.invalid/v1/messages"


def make_settings(
    database_url: str,
    testing: bool = True,
    authorized_roots: tuple[str, ...] = (),
    git_timeout_seconds: int = 30,
) -> Settings:
    return Settings(
        app_name="ADLL-Test",
        database_url=database_url,
        cors_origins=(),
        dashscope_base_url="https://example.invalid",
        admin_password=ADMIN_PW,
        session_ttl_seconds=3600,
        cookie_secure=False,
        testing=testing,
        authorized_roots=tuple(authorized_roots),
        git_timeout_seconds=git_timeout_seconds,
    )


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def make_repo(base: Path, name: str = "repo", object_format: str | None = None) -> Path:
    path = Path(base) / name
    path.mkdir(parents=True, exist_ok=True)
    init_args = ["init"]
    if object_format:
        init_args += ["--object-format", object_format]
    git(path, *init_args)
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "user.name", "t")
    git(path, "config", "core.autocrlf", "false")
    (path / "a.txt").write_text("hello\n", encoding="utf-8", newline="\n")
    git(path, "add", "a.txt")
    git(path, "commit", "-m", "init")
    return path


def login_client(app) -> tuple[TestClient, str]:
    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"password": ADMIN_PW})
    assert resp.status_code == 200, resp.text
    return client, resp.json()["csrf_token"]


def csrf_headers(csrf: str, idem: str | None = None) -> dict:
    headers = {"X-CSRF-Token": csrf}
    if idem:
        headers["Idempotency-Key"] = idem
    return headers


def seed_authorization(
    app,
    task_id: int,
    *,
    receiver: str = RECEIVER_MOCK,
    data_types=None,
    scope=None,
    status: str = "approved",
    revoked_at=None,
    expires_at=None,
):
    """测试专用：在隔离临时库中构造出站授权（不经生产 API）。"""
    from app.models.outbound import OutboundAuthorization
    from app.models.task import Task

    db = app.state.db.session()
    try:
        task = db.get(Task, task_id)
        auth = OutboundAuthorization(
            task_id=task.id,
            baseline_id=task.baseline_id,
            receiver=receiver,
            data_types=data_types or ["requirement", "feedback", "source"],
            send_scope=scope if scope is not None else {"paths": ["a.txt"]},
            status=status,
            revoked_at=revoked_at,
            expires_at=expires_at,
        )
        db.add(auth)
        db.commit()
        db.refresh(auth)
        return auth.id
    finally:
        db.close()


def seed_proposal(
    app,
    task_id: int,
    *,
    execution_status: str = "completed",
    verification_status: str = "verified",
    sufficient: bool = True,
    create_verification: bool = True,
    content: str | None = None,
):
    """测试专用：在隔离临时库中构造合成执行/核验/方案（不经生产 API）。"""
    import hashlib

    from app.models.generation import GenerationExecution, VerificationAttempt
    from app.models.proposal import ProposalVersion
    from app.models.repository import AnalysisBaseline
    from app.models.task import Task
    from app.services import task_service

    db = app.state.db.session()
    try:
        task = db.get(Task, task_id)
        requirement = task_service.current_requirement(db, task)
        baseline = db.get(AnalysisBaseline, task.baseline_id)
        execution = GenerationExecution(
            task_id=task.id,
            baseline_id=baseline.id,
            requirement_version_id=requirement.id,
            status=execution_status,
        )
        db.add(execution)
        db.flush()
        if create_verification:
            db.add(
                VerificationAttempt(
                    execution_id=execution.id,
                    attempt_no=1,
                    status=verification_status,
                    evidence_sufficiency={"sufficient": sufficient},
                    isolation_evidence={"probe": "synthetic"},
                    coverage_note="synthetic coverage",
                )
            )
            db.flush()
        last = (
            db.query(ProposalVersion)
            .filter_by(task_id=task.id)
            .order_by(ProposalVersion.seq.desc())
            .first()
        )
        seq = (last.seq if last else 0) + 1
        text = content or f"synthetic plan {seq}"
        proposal = ProposalVersion(
            task_id=task.id,
            seq=seq,
            requirement_version_id=requirement.id,
            baseline_id=baseline.id,
            execution_id=execution.id,
            content=text,
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
        db.add(proposal)
        db.commit()
        db.refresh(proposal)
        return proposal.id
    finally:
        db.close()