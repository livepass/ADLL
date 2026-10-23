"""响应序列化（显式字段，避免泄露内部对象/凭据）。"""
from __future__ import annotations

from ..models.repository import AnalysisBaseline, GitRepository
from ..models.proposal import ApprovalEvent, Feedback, ProposalVersion
from ..models.task import RequirementVersion, Task
from ..services import task_service


def repo_dict(repo: GitRepository) -> dict:
    return {
        "id": repo.id,
        "path": repo.path,
        "repo_identity": repo.repo_identity,
        "object_format": repo.object_format,
        "branch": repo.branch,
        "active": repo.active,
        "created_at": repo.created_at.isoformat(),
    }


def baseline_dict(baseline: AnalysisBaseline) -> dict:
    return {
        "id": baseline.id,
        "repository_id": baseline.repository_id,
        "commit_sha": baseline.commit_sha,
        "object_format": baseline.object_format,
        "workspace_decision": baseline.workspace_decision,
        "snapshot_digest": baseline.snapshot_digest,
        "available": baseline.available,
        "unavailable_reason": baseline.unavailable_reason,
        "inventory_summary": baseline.inventory_summary,
        "created_at": baseline.created_at.isoformat(),
    }


def requirement_dict(version: RequirementVersion) -> dict:
    return {
        "id": version.id,
        "task_id": version.task_id,
        "seq": version.seq,
        "content": version.content,
        "content_hash": version.content_hash,
        "created_at": version.created_at.isoformat(),
    }


def task_dict(db, task: Task) -> dict:
    current = task_service.current_requirement(db, task)
    return {
        "id": task.id,
        "repository_id": task.repository_id,
        "baseline_id": task.baseline_id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "current_approval_id": task.current_approval_id,
        "created_at": task.created_at.isoformat(),
        "current_requirement_version": requirement_dict(current) if current else None,
    }


def proposal_dict(proposal: ProposalVersion) -> dict:
    return {
        "id": proposal.id,
        "task_id": proposal.task_id,
        "seq": proposal.seq,
        "requirement_version_id": proposal.requirement_version_id,
        "baseline_id": proposal.baseline_id,
        "execution_id": proposal.execution_id,
        "content": proposal.content,
        "content_hash": proposal.content_hash,
        "created_at": proposal.created_at.isoformat(),
    }


def approval_dict(event: ApprovalEvent) -> dict:
    return {
        "id": event.id,
        "task_id": event.task_id,
        "proposal_version_id": event.proposal_version_id,
        "requirement_version_id": event.requirement_version_id,
        "repo_identity": event.repo_identity,
        "commit_sha": event.commit_sha,
        "proposal_content_hash": event.proposal_content_hash,
        "decision": event.decision,
        "reason": event.reason,
        "actor_role": event.actor_role,
        "created_at": event.created_at.isoformat(),
    }


def feedback_dict(feedback: Feedback) -> dict:
    return {
        "id": feedback.id,
        "task_id": feedback.task_id,
        "proposal_version_id": feedback.proposal_version_id,
        "content": feedback.content,
        "created_at": feedback.created_at.isoformat(),
    }