"""方案版本链、审批（批准/驳回/历史）与反馈（T019–T025）。

- 批准/驳回/反馈：服务端身份 + role=user + CSRF（失败记 SecurityEvent）+ 持久化幂等。
- 批准：单事务 BEGIN IMMEDIATE 前置复核 + INSERT 不可变事件 + 任务投影。
"""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..models.enums import SessionRole
from ..models.session import UserSession
from ..security.deps import get_current_session, get_db, require_user_role
from ..services import approval_service, task_service
from ..services.approval_service import ApprovalError
from .common import http_error, idempotent
from .serializers import approval_dict, feedback_dict, proposal_dict

router = APIRouter(prefix="/api/tasks", tags=["proposals"])
ANONYMOUS_METHODS = {"GET", "HEAD", "OPTIONS"}


def _authorize_approval(request: Request, db, session: UserSession) -> None:
    if session.role != SessionRole.USER.value:
        approval_service.record_security_event(
            db, "approval_role_denied", {"role": session.role}
        )
        http_error(403, "forbidden", "需要用户主体（role=user）")
    if request.method not in ANONYMOUS_METHODS:
        header = request.headers.get("X-CSRF-Token")
        if not header or not hmac.compare_digest(header, session.csrf_token):
            approval_service.record_security_event(db, "approval_csrf_denied", {})
            http_error(403, "csrf_failed", "CSRF 校验失败")


def _task_or_404(db, task_id: int):
    task = task_service.get_task(db, task_id)
    if task is None:
        http_error(404, "not_found", "任务不存在")
    return task


class ApproveBody(BaseModel):
    reason: str | None = None


@router.get("/{task_id}/proposals")
def list_proposals(
    task_id: int,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_role),
):
    task = _task_or_404(db, task_id)
    rows = approval_service.list_proposals(db, task)
    return {
        "proposals": [
            {
                **proposal_dict(proposal),
                "has_approved_event": approved is not None,
                "approval_effective": effective,
            }
            for proposal, approved, effective in rows
        ]
    }


@router.get("/{task_id}/approvals")
def list_approvals(
    task_id: int,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_role),
):
    task = _task_or_404(db, task_id)
    history = approval_service.history(db, task)
    return {
        "approvals": [
            {**approval_dict(event), "effective": effective} for event, effective in history
        ]
    }


@router.post("/{task_id}/proposals/{version}/approve")
def approve(
    task_id: int,
    version: int,
    body: ApproveBody,
    request: Request,
    db=Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    _authorize_approval(request, db, session)
    task = _task_or_404(db, task_id)

    def handler():
        try:
            event = approval_service.approve(db, task, version, session.role)
        except ApprovalError as exc:
            return exc.status, {"code": exc.code, "message": exc.message}
        return 200, {"approval": approval_dict(event), "task_id": task.id, "task_status": task.status}

    return idempotent(
        request, db, {"task_id": task_id, "version": version, "reason": body.reason}, handler
    )


@router.post("/{task_id}/proposals/{version}/reject")
def reject(
    task_id: int,
    version: int,
    body: ApproveBody,
    request: Request,
    db=Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    _authorize_approval(request, db, session)
    task = _task_or_404(db, task_id)

    def handler():
        try:
            event = approval_service.reject(db, task, version, body.reason, session.role)
        except ApprovalError as exc:
            return exc.status, {"code": exc.code, "message": exc.message}
        return 200, {"approval": approval_dict(event), "task_id": task.id, "task_status": task.status}

    return idempotent(
        request, db, {"task_id": task_id, "version": version, "reason": body.reason}, handler
    )


class FeedbackBody(BaseModel):
    content: str


@router.post("/{task_id}/proposals/{version}/feedback")
def submit_feedback(
    task_id: int,
    version: int,
    body: FeedbackBody,
    request: Request,
    db=Depends(get_db),
    session: UserSession = Depends(get_current_session),
):
    _authorize_approval(request, db, session)
    task = _task_or_404(db, task_id)

    def handler():
        try:
            feedback, regeneration = approval_service.submit_feedback(
                db, task, version, body.content
            )
        except ApprovalError as exc:
            return exc.status, {"code": exc.code, "message": exc.message}
        return 200, {
            "feedback": feedback_dict(feedback),
            "regeneration": regeneration,
        }

    return idempotent(
        request, db, {"task_id": task_id, "version": version, "content": body.content}, handler
    )