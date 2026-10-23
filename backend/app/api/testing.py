"""测试专用路由（仅 `settings.testing=True` 时挂载；不进入正式业务面）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..agents.base import GenerationRequest
from ..models.outbound import OutboundAuthorization
from ..models.session import UserSession
from ..security.deps import get_db, require_user_action, require_user_role
from ..services import idempotency, outbound

router = APIRouter(prefix="/_test", tags=["testing"])


@router.get("/secure")
def secure(session: UserSession = Depends(require_user_role)) -> dict:
    return {"ok": True, "role": session.role}


@router.post("/csrf-action")
def csrf_action(session: UserSession = Depends(require_user_action)) -> dict:
    return {"ok": True, "role": session.role}


@router.post("/idempotent")
async def idempotent(
    request: Request,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_action),
) -> JSONResponse:
    key = request.headers.get("Idempotency-Key")
    payload = await request.body()

    def handler() -> tuple[int, dict]:
        request.app.state.counter["n"] += 1
        return 200, {"counter": request.app.state.counter["n"]}

    status, body, replayed = idempotency.execute(
        db, key, f"POST {request.url.path}", payload, handler
    )
    return JSONResponse(status_code=status, content={**body, "replayed": replayed})


class OutboundEvalBody(BaseModel):
    authorization_id: int | None = None
    task_id: int | None = None
    baseline_id: int | None = None
    receiver: str
    data_types: list[str]
    scope: dict


@router.post("/outbound-eval")
def outbound_eval(
    body: OutboundEvalBody,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_role),
) -> dict:
    auth = None
    if body.authorization_id is not None:
        auth = db.get(OutboundAuthorization, body.authorization_id)
    decision = outbound.evaluate(
        auth,
        task_id=body.task_id,
        baseline_id=body.baseline_id,
        receiver=body.receiver,
        data_types=body.data_types,
        scope=body.scope,
    )
    return {"allowed": decision.allowed, "code": decision.code}


class AuditBody(BaseModel):
    authorization_id: int
    task_id: int | None = None
    baseline_id: int | None = None
    execution_id: str | None = None
    requirement: list | None = None
    feedback: list | None = None
    source: list | None = None


@router.post("/audit-record")
def audit_record(
    body: AuditBody,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_role),
) -> dict:
    auth = db.get(OutboundAuthorization, body.authorization_id)
    if auth is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "授权不存在"})
    try:
        rec = outbound.record_send(
            db,
            auth,
            task_id=body.task_id,
            baseline_id=body.baseline_id,
            execution_id=body.execution_id,
            requirement=body.requirement,
            feedback=body.feedback,
            source=body.source,
        )
    except PermissionError as exc:
        raise HTTPException(
            403, detail={"code": "outbound_denied", "message": str(exc)}
        ) from exc
    return {
        "id": rec.id,
        "payload_manifest": rec.payload_manifest,
        "content_digest": rec.content_digest,
    }


class AgentGenBody(BaseModel):
    requirement_text: str = "synthetic"


@router.post("/agent-generate")
def agent_generate(
    body: AgentGenBody,
    request: Request,
    session: UserSession = Depends(require_user_role),
) -> dict:
    adapter = request.app.state.adapter_factory()
    result = adapter.generate(
        GenerationRequest(subset_path=None, requirement_text=body.requirement_text)
    )
    return {
        "text": result.text,
        "usage": result.usage,
        "usage_basis": result.usage_basis,
        "cost": result.cost,
        "terminal_status": result.terminal_status,
        "tool_call_log": result.tool_call_log,
    }


@router.post("/session-role")
def session_role(
    request: Request,
    role: str = "agent",
    db=Depends(get_db),
) -> dict:
    from ..security.sessions import create_session

    raw, session = create_session(db, role, request.app.state.settings.session_ttl_seconds)
    return {"token": raw, "csrf_token": session.csrf_token, "role": session.role}