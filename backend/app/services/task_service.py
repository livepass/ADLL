"""任务与需求版本服务（T012/T013）。"""
from __future__ import annotations

import hashlib

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from ..models.repository import AnalysisBaseline, GitRepository
from ..models.task import RequirementVersion, Task
from . import repository_service


def create_task(db, repo: GitRepository, baseline: AnalysisBaseline, title: str, description: str | None):
    if baseline.repository_id != repo.id:
        raise ValueError("baseline_repo_mismatch")
    if not baseline.available:
        raise ValueError("baseline_unavailable")
    task = Task(
        repository_id=repo.id,
        baseline_id=baseline.id,
        title=title,
        description=description,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def list_tasks(db) -> list[Task]:
    return db.query(Task).order_by(Task.id).all()


def get_task(db, task_id: int) -> Task | None:
    return db.get(Task, task_id)


def current_requirement(db, task: Task) -> RequirementVersion | None:
    return (
        db.query(RequirementVersion)
        .filter_by(task_id=task.id)
        .order_by(RequirementVersion.seq.desc())
        .first()
    )


def save_requirement(db, task: Task, content: str, max_attempts: int = 5) -> RequirementVersion:
    """正式保存 → 新的不可变版本（seq 并发由唯一约束 + 重试保证）。"""
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    for _ in range(max_attempts):
        current_max = (
            db.query(func.max(RequirementVersion.seq)).filter_by(task_id=task.id).scalar() or 0
        )
        version = RequirementVersion(
            task_id=task.id,
            seq=current_max + 1,
            content=content,
            content_hash=content_hash,
        )
        db.add(version)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            continue
        db.refresh(version)
        return version
    raise RuntimeError("requirement seq contention")


def change_baseline(db, git, task: Task, commit_sha: str | None = None) -> AnalysisBaseline:
    """主动更换基准 → 新记录（不继承旧审批；审批模块 T019+）。"""
    repo = db.get(GitRepository, task.repository_id)
    sha = commit_sha or git.commit_sha(repo.path)
    baseline = repository_service.create_baseline(db, git, repo, sha, "rebased")
    task.baseline_id = baseline.id
    db.commit()
    db.refresh(task)
    return baseline