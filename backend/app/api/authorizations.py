"""出站授权 API（T035 前端工作流所需）：查询 / 创建 / 撤销。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..models.base import utcnow
from ..models.outbound import OutboundAuthorization
from ..models.session import UserSession
from ..models.task import Task
from ..security.deps import get_db, require_user_action, require_user_role
from .common import http_error, idempotent

router = APIRouter(prefix="/api", tags=["authorizations"])


def _auth_dict(auth: OutboundAuthorization) -> dict:
    return {
        "id": auth.id,
        "task_id": auth.task_id,
        "baseline_id": auth.baseline_id,
        "receiver": auth.receiver,
        "data_types": auth.data_types,
        "send_scope": auth.send_scope,
        "status": auth.status,
        "revoked_at": auth.revoked_at.isoformat() if auth.revoked_at else None,
        "expires_at": auth.expires_at.isoformat() if auth.expires_at else None,
    }


@router.get("/tasks/{task_id}/outbound-authorizations")
def list_authorizations(
    task_id: int,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_role),
):
    task = db.get(Task, task_id)
    if task is None:
        http_error(404, "not_found", "任务不存在")
    rows = (
        db.query(OutboundAuthorization)
        .filter_by(task_id=task_id)
        .order_by(OutboundAuthorization.id.desc())
        .all()
    )
    return {"authorizations": [_auth_dict(row) for row in rows]}


class AuthorizationBody(BaseModel):
    receiver: str
    data_types: list[str] = ["requirement", "feedback", "source"]
    send_scope: dict = {}


@router.post("/tasks/{task_id}/outbound-authorizations")
def create_authorization(
    task_id: int,
    body: AuthorizationBody,
    request: Request,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_action),
):
    task = db.get(Task, task_id)
    if task is None:
        http_error(404, "not_found", "任务不存在")
    if not body.receiver:
        http_error(400, "invalid_receiver", "接收方必填")

    def handler():
        auth = OutboundAuthorization(
            task_id=task.id,
            baseline_id=task.baseline_id,
            receiver=body.receiver,
            data_types=list(body.data_types),
            send_scope=dict(body.send_scope),
            status="approved",
        )
        db.add(auth)
        db.commit()
        db.refresh(auth)
        return 200, {"authorization": _auth_dict(auth)}

    return idempotent(
        request,
        db,
        {"task_id": task_id, "receiver": body.receiver, "data_types": body.data_types,
         "send_scope": body.send_scope},
        handler,
    )


@router.post("/outbound-authorizations/{authorization_id}/revoke")
def revoke_authorization(
    authorization_id: int,
    request: Request,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_action),
):
    auth = db.get(OutboundAuthorization, authorization_id)
    if auth is None:
        http_error(404, "not_found", "授权不存在")

    def handler():
        auth.status = "revoked"
        auth.revoked_at = utcnow()
        db.commit()
        db.refresh(auth)
        return 200, {"authorization": _auth_dict(auth)}

    return idempotent(
        request, db, {"authorization_id": authorization_id}, handler
    )