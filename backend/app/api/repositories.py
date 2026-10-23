"""仓库关联 / 工作区决定 / 当前仓库（US1，T013）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..adapters.git import GitAdapter, GitError
from ..models.repository import AnalysisBaseline, GitRepository
from ..models.session import UserSession
from ..security.deps import get_db, require_user_action, require_user_role
from ..services import repository_service
from .common import http_error, idempotent
from .serializers import baseline_dict, repo_dict

router = APIRouter(prefix="/api/repositories", tags=["repositories"])


def _git(request: Request) -> GitAdapter:
    settings = request.app.state.settings
    return GitAdapter(list(settings.authorized_roots), settings.git_timeout_seconds)


class LinkBody(BaseModel):
    path: str


@router.post("/link")
def link(
    body: LinkBody,
    request: Request,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_action),
):
    def handler():
        try:
            repo, baseline, status, needs_decision = repository_service.link(
                db, _git(request), body.path
            )
        except GitError as exc:
            return 400, {"code": exc.code, "message": exc.message}
        return 200, {
            "repository": repo_dict(repo),
            "baseline": baseline_dict(baseline) if baseline else None,
            "workspace_status": status,
            "needs_decision": needs_decision,
        }

    return idempotent(request, db, {"path": body.path}, handler)


@router.get("/active")
def active(
    request: Request,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_role),
):
    repo = (
        db.query(GitRepository)
        .filter_by(active=True)
        .order_by(GitRepository.id.desc())
        .first()
    )
    if repo is None:
        return {"repository": None, "baseline": None}
    baseline = repository_service.latest_baseline(db, repo)
    return {
        "repository": repo_dict(repo),
        "baseline": baseline_dict(baseline) if baseline else None,
    }


class DecisionBody(BaseModel):
    decision: str


@router.post("/{repo_id}/workspace-decision")
def workspace_decision(
    repo_id: int,
    body: DecisionBody,
    request: Request,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_action),
):
    repo = db.get(GitRepository, repo_id)
    if repo is None:
        http_error(404, "not_found", "仓库不存在")

    def handler():
        try:
            baseline = repository_service.apply_decision(
                db, _git(request), repo, body.decision
            )
        except GitError as exc:
            return 400, {"code": exc.code, "message": exc.message}
        except ValueError as exc:
            return 400, {"code": "invalid_decision", "message": str(exc)}
        return 200, {"baseline": baseline_dict(baseline)}

    return idempotent(
        request, db, {"repo_id": repo_id, "decision": body.decision}, handler
    )