"""人工审批门禁、方案版本链与反馈（T019–T025）。

批准事务在单个 `BEGIN IMMEDIATE` 内完成：前置复核 → INSERT ApprovalEvent →
更新任务投影（current_approval）。任一前置不成立 → 回滚，不落 approved 事件，
仅记 AuditLog。
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ..models.audit import AuditLog, SecurityEvent
from ..models.generation import GenerationExecution, VerificationAttempt
from ..models.proposal import ApprovalEvent, Feedback, ProposalVersion
from ..models.repository import AnalysisBaseline, GitRepository
from . import task_service


class ApprovalError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.status = status
        self.code = code
        self.message = message


def record_security_event(db, kind: str, detail: dict | None = None) -> None:
    try:
        db.add(SecurityEvent(kind=kind, detail=detail or {}))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def _audit(db, action: str, before: dict | None = None, after: dict | None = None) -> None:
    try:
        db.add(AuditLog(actor="system", action=action, before=before, after=after))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def _begin_immediate(db) -> None:
    if db.in_transaction():
        db.rollback()
    db.execute(text("BEGIN IMMEDIATE"))


def current_proposal(db, task) -> ProposalVersion | None:
    return (
        db.query(ProposalVersion)
        .filter_by(task_id=task.id)
        .order_by(ProposalVersion.seq.desc())
        .first()
    )


def latest_verification(db, execution_id: int) -> VerificationAttempt | None:
    return (
        db.query(VerificationAttempt)
        .filter_by(execution_id=execution_id)
        .order_by(VerificationAttempt.attempt_no.desc())
        .first()
    )


def _checks(db, task, version_no: int):
    proposal = current_proposal(db, task)
    if proposal is None or proposal.seq != version_no:
        raise ApprovalError(409, "approval_target_stale", "目标不是当前方案版本")
    requirement = task_service.current_requirement(db, task)
    if requirement is None or proposal.requirement_version_id != requirement.id:
        raise ApprovalError(409, "approval_target_stale", "需求版本已变更")
    baseline = db.get(AnalysisBaseline, task.baseline_id)
    if baseline is None or not baseline.available or proposal.baseline_id != baseline.id:
        raise ApprovalError(409, "approval_target_stale", "分析基准已变更或不可用")
    execution = db.get(GenerationExecution, proposal.execution_id)
    if execution is None or execution.status != "completed":
        raise ApprovalError(409, "verification_not_passed", "关联执行状态无效")
    verification = latest_verification(db, execution.id)
    if verification is None or verification.status != "verified":
        raise ApprovalError(409, "verification_not_passed", "最新核验未通过")
    if not (verification.evidence_sufficiency or {}).get("sufficient"):
        raise ApprovalError(409, "verification_not_passed", "核验证据不足")
    repo = db.get(GitRepository, task.repository_id)
    if repo is None:
        raise ApprovalError(409, "approval_target_stale", "仓库不存在")
    return proposal, requirement, baseline, repo


def approve(db, task, version_no: int, actor_role: str) -> ApprovalEvent:
    _begin_immediate(db)
    try:
        proposal, requirement, baseline, repo = _checks(db, task, version_no)
        event = ApprovalEvent(
            task_id=task.id,
            proposal_version_id=proposal.id,
            requirement_version_id=requirement.id,
            repo_identity=repo.repo_identity,
            commit_sha=baseline.commit_sha,
            proposal_content_hash=proposal.content_hash,
            decision="approved",
            actor_role=actor_role,
        )
        db.add(event)
        db.flush()
        task.current_approval_id = event.id
        task.status = "approved"
        db.commit()
        db.refresh(event)
        return event
    except ApprovalError as exc:
        db.rollback()
        _audit(db, f"approval_denied:{exc.code}", {"task_id": task.id, "version": version_no})
        raise
    except IntegrityError:
        db.rollback()
        _audit(db, "approval_duplicate", {"task_id": task.id, "version": version_no})
        raise ApprovalError(409, "approval_exists", "该方案版本已有有效批准") from None


def reject(db, task, version_no: int, reason: str | None, actor_role: str) -> ApprovalEvent:
    _begin_immediate(db)
    try:
        proposal = (
            db.query(ProposalVersion)
            .filter_by(task_id=task.id, seq=version_no)
            .one_or_none()
        )
        if proposal is None:
            raise ApprovalError(404, "not_found", "方案版本不存在")
        requirement = task_service.current_requirement(db, task)
        baseline = db.get(AnalysisBaseline, task.baseline_id)
        repo = db.get(GitRepository, task.repository_id)
        event = ApprovalEvent(
            task_id=task.id,
            proposal_version_id=proposal.id,
            requirement_version_id=requirement.id if requirement else 0,
            repo_identity=repo.repo_identity if repo else "",
            commit_sha=baseline.commit_sha if baseline else "",
            proposal_content_hash=proposal.content_hash,
            decision="rejected",
            reason=reason,
            actor_role=actor_role,
        )
        db.add(event)
        db.flush()
        task.status = "rejected"
        db.commit()
        db.refresh(event)
        return event
    except ApprovalError:
        db.rollback()
        raise


def is_effective(db, event: ApprovalEvent | None, task) -> bool:
    if event is None or event.decision != "approved":
        return False
    requirement = task_service.current_requirement(db, task)
    baseline = db.get(AnalysisBaseline, task.baseline_id)
    proposal = current_proposal(db, task)
    if requirement is None or baseline is None or proposal is None:
        return False
    return (
        event.requirement_version_id == requirement.id
        and event.commit_sha == baseline.commit_sha
        and event.proposal_version_id == proposal.id
    )


def history(db, task):
    events = (
        db.query(ApprovalEvent).filter_by(task_id=task.id).order_by(ApprovalEvent.id).all()
    )
    return [(event, is_effective(db, event, task)) for event in events]


def list_proposals(db, task):
    proposals = (
        db.query(ProposalVersion).filter_by(task_id=task.id).order_by(ProposalVersion.seq).all()
    )
    result = []
    for proposal in proposals:
        approved = (
            db.query(ApprovalEvent)
            .filter_by(proposal_version_id=proposal.id, decision="approved")
            .first()
        )
        result.append((proposal, approved, is_effective(db, approved, task) if approved else False))
    return result


def submit_feedback(db, task, version_no: int, content: str) -> tuple[Feedback, dict]:
    proposal = (
        db.query(ProposalVersion).filter_by(task_id=task.id, seq=version_no).one_or_none()
    )
    if proposal is None:
        raise ApprovalError(404, "not_found", "方案版本不存在")
    feedback = Feedback(task_id=task.id, proposal_version_id=proposal.id, content=content)
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    # 无真实 Adapter：如实标记无法自动生成新版本（不得假装已生成）
    return feedback, {
        "required": True,
        "available": False,
        "reason": "real_adapter_unavailable",
    }