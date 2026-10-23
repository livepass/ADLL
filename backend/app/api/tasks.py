"""任务与需求版本（US1，T012/T013）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..adapters.git import GitAdapter
from ..models.repository import AnalysisBaseline, GitRepository
from ..models.session import UserSession
from ..security.deps import get_db, require_user_action, require_user_role
from ..services import task_service
from .common import http_error, idempotent
from .serializers import baseline_dict, requirement_dict, task_dict

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _git(request: Request) -> GitAdapter:
    settings = request.app.state.settings
    return GitAdapter(list(settings.authorized_roots), settings.git_timeout_seconds)


class CreateBody(BaseModel):
    repository_id: int
    baseline_id: int
    title: str
    description: str | None = None


@router.post("")
def create_task(
    body: CreateBody,
    request: Request,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_action),
):
    def handler():
        repo = db.get(GitRepository, body.repository_id)
        baseline = db.get(AnalysisBaseline, body.baseline_id)
        if repo is None:
            return 404, {"code": "not_found", "message": "仓库不存在"}
        if baseline is None:
            return 404, {"code": "not_found", "message": "基准不存在"}
        if baseline.repository_id != repo.id:
            return 409, {"code": "baseline_repo_mismatch", "message": "基准不属于该仓库"}
        if not baseline.available:
            return 409, {"code": "baseline_unavailable", "message": "基准不可用"}
        task = task_service.create_task(db, repo, baseline, body.title, body.description)
        return 200, {"task": task_dict(db, task)}

    return idempotent(
        request,
        db,
        {
            "repository_id": body.repository_id,
            "baseline_id": body.baseline_id,
            "title": body.title,
            "description": body.description,
        },
        handler,
    )


@router.get("")
def list_tasks(
    request: Request,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_role),
):
    return {"tasks": [task_dict(db, t) for t in task_service.list_tasks(db)]}


@router.get("/{task_id}")
def get_task(
    task_id: int,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_role),
):
    task = task_service.get_task(db, task_id)
    if task is None:
        http_error(404, "not_found", "任务不存在")
    return {"task": task_dict(db, task)}


class RequirementBody(BaseModel):
    content: str


@router.put("/{task_id}/requirement")
def save_requirement(
    task_id: int,
    body: RequirementBody,
    request: Request,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_action),
):
    task = task_service.get_task(db, task_id)
    if task is None:
        http_error(404, "not_found", "任务不存在")

    def handler():
        version = task_service.save_requirement(db, task, body.content)
        return 200, {"requirement_version": requirement_dict(version)}

    return idempotent(
        request, db, {"task_id": task_id, "content": body.content}, handler
    )


class BaselineBody(BaseModel):
    commit_sha: str | None = None


@router.post("/{task_id}/baseline")
def change_baseline(
    task_id: int,
    body: BaselineBody,
    request: Request,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_action),
):
    task = task_service.get_task(db, task_id)
    if task is None:
        http_error(404, "not_found", "任务不存在")

    def handler():
        baseline = task_service.change_baseline(db, _git(request), task, body.commit_sha)
        return 200, {
            "baseline": baseline_dict(baseline),
            "task_id": task.id,
            "baseline_id": task.baseline_id,
        }

    return idempotent(
        request, db, {"task_id": task_id, "commit_sha": body.commit_sha}, handler
    )