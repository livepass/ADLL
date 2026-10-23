"""生成执行 API（T031/T033）：异步发起、查询、取消、审计、事件（最小）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..adapters.git import GitAdapter
from ..agents.factory import NoRealAdapterAvailable
from ..models.generation import GenerationExecution, VerificationAttempt
from ..models.outbound import OutboundAuthorization
from ..models.proposal import ProposalVersion
from ..models.repository import AnalysisBaseline, GitRepository
from ..models.session import UserSession
from ..models.task import Task
from ..security.deps import get_db, require_user_action, require_user_role
from ..services import generation_service, snapshot, task_service
from ..services.generation_service import GenerationBlocked
from ..services.outbound_pipeline import OutboundDenied
from .common import http_error, idempotent
from .serializers import proposal_dict

router = APIRouter(prefix="/api", tags=["generations"])


def _git(request: Request) -> GitAdapter:
    settings = request.app.state.settings
    return GitAdapter(list(settings.authorized_roots), settings.git_timeout_seconds)


class GenerateBody(BaseModel):
    authorization_id: int
    feedback: list[str] = []


def _materialize_sources(request: Request, db, task, auth):
    repo = db.get(GitRepository, task.repository_id)
    baseline = db.get(AnalysisBaseline, task.baseline_id)
    if repo is None or baseline is None:
        raise GenerationBlocked("baseline_unavailable")
    paths = (auth.send_scope or {}).get("paths")
    git = _git(request)
    materialization = snapshot.materialize(
        git, repo.path, baseline.commit_sha, authorized_paths=paths
    )
    if not materialization.available:
        raise GenerationBlocked(f"snapshot_unavailable:{materialization.reason}")
    items = []
    binary_skipped = []
    for entry in materialization.files:
        blob = git.blob_bytes(repo.path, entry["object"])
        try:
            content = blob.decode("utf-8")
        except UnicodeDecodeError:
            # 二进制内容不进入发送面（显式跳过并记录，避免快照与实际请求不一致）。
            binary_skipped.append(entry["path"])
            continue
        items.append({"path": entry["path"], "content": content, "sha256": entry["sha256"]})
    return materialization, items, binary_skipped


@router.post("/tasks/{task_id}/generations")
def start_generation(
    task_id: int,
    body: GenerateBody,
    request: Request,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_action),
):
    task = db.get(Task, task_id)
    if task is None:
        http_error(404, "not_found", "任务不存在")
    auth = db.get(OutboundAuthorization, body.authorization_id)
    if auth is None:
        http_error(404, "not_found", "出站授权不存在")

    def handler():
        try:
            adapter = request.app.state.adapter_factory()
        except NoRealAdapterAvailable:
            return 503, {"code": "ai_disabled", "message": "真实 AI 发送默认关闭（fail-closed）"}
        requirement = task_service.current_requirement(db, task)
        if requirement is None:
            return 409, {"code": "no_requirement", "message": "尚无正式需求版本"}
        baseline = db.get(AnalysisBaseline, task.baseline_id)
        if baseline is None or not baseline.available:
            # FR-048：基准不可验证时阻止发起，不回退 HEAD。
            return 423, {
                "code": "baseline_unavailable",
                "message": "分析基准不可用，已阻止生成（fail-closed）",
            }
        try:
            materialization, items, binary_skipped = _materialize_sources(request, db, task, auth)
            execution_id = generation_service.start_async(
                db,
                request.app.state.db.session,
                task,
                auth,
                receiver=auth.receiver,
                data_types=list(auth.data_types or []),
                scope=dict(auth.send_scope or {}),
                requirement_text=requirement.content,
                feedback_texts=body.feedback,
                source_items=items,
                model=request.app.state.settings.dashscope_model,
                adapter=adapter,
                testing=request.app.state.settings.testing,
            )
        except GenerationBlocked as exc:
            status = 423 if exc.code == "baseline_unavailable" else 409
            return status, {"code": exc.code, "message": exc.code}
        except OutboundDenied as exc:
            return 403, {"code": "outbound_denied", "message": exc.code}
        except Exception as exc:  # noqa: BLE001
            return 500, {"code": "generation_error", "message": type(exc).__name__}
        return 202, {
            "execution_id": execution_id,
            "status": "running",
            "snapshot": {
                "digest": materialization.digest,
                "authorized_paths": list((auth.send_scope or {}).get("paths") or []),
                # snapshot_files 为快照原始文件；files 为实际进入请求的文本文件。
                "snapshot_files": [f["path"] for f in materialization.files],
                "files": [item["path"] for item in items],
                "excluded": list(materialization.excluded)
                + [{"path": path, "reason": "binary"} for path in binary_skipped],
                "warnings": materialization.warnings,
                "lfs_pointers": materialization.lfs_pointers,
            },
        }

    return idempotent(
        request,
        db,
        {"task_id": task_id, "authorization_id": body.authorization_id, "feedback": body.feedback},
        handler,
    )


def _execution_dict(execution: GenerationExecution) -> dict:
    return {
        "id": execution.id,
        "task_id": execution.task_id,
        "baseline_id": execution.baseline_id,
        "status": execution.status,
        "provider": execution.provider,
        "cancel_requested": execution.cancel_requested,
        "cancel_outcome": execution.cancel_outcome,
        "failure_reason": execution.failure_reason,
        "usage": execution.usage,
        "usage_basis": execution.usage_basis,
        "cost": execution.cost,
    }


@router.get("/generations/{execution_id}")
def get_generation(
    execution_id: int,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_role),
):
    execution = db.get(GenerationExecution, execution_id)
    if execution is None:
        http_error(404, "not_found", "执行不存在")
    verification = (
        db.query(VerificationAttempt)
        .filter_by(execution_id=execution_id)
        .order_by(VerificationAttempt.attempt_no.desc())
        .first()
    )
    proposal = db.query(ProposalVersion).filter_by(execution_id=execution_id).first()
    return {
        "execution": _execution_dict(execution),
        "verification": (
            {
                "id": verification.id,
                "execution_id": verification.execution_id,
                "status": verification.status,
                "evidence_sufficiency": verification.evidence_sufficiency,
                "coverage_note": verification.coverage_note,
            }
            if verification
            else None
        ),
        "proposal": proposal_dict(proposal) if proposal else None,
    }


@router.post("/generations/{execution_id}/cancel")
def cancel_generation(
    execution_id: int,
    request: Request,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_action),
):
    outcome = generation_service.request_cancel(db, execution_id)
    if outcome is None:
        http_error(404, "not_found", "执行不存在")
    execution = db.get(GenerationExecution, execution_id)
    return {
        "outcome": outcome,
        "status": execution.status,
        "cancel_outcome": execution.cancel_outcome,
        "note": "取消仅在发送前可阻止发送；请求已发出时无法撤回已发送数据",
    }


@router.get("/generations/{execution_id}/send-audit")
def send_audit(
    execution_id: int,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_role),
):
    from ..models.outbound import SendAuditRecord

    records = (
        db.query(SendAuditRecord)
        .filter_by(execution_id=str(execution_id))
        .order_by(SendAuditRecord.id)
        .all()
    )
    return {
        "audits": [
            {
                "id": record.id,
                "authorization_id": record.authorization_id,
                "payload_manifest": record.payload_manifest,
                "content_digest": record.content_digest,
                "payload_digest": record.payload_digest,
            }
            for record in records
        ]
    }


@router.get("/generations/{execution_id}/events")
def events(
    execution_id: int,
    db=Depends(get_db),
    session: UserSession = Depends(require_user_role),
):
    execution = db.get(GenerationExecution, execution_id)
    if execution is None:
        http_error(404, "not_found", "执行不存在")
    return {"events": [{"type": "final", "status": execution.status}]}