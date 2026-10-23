"""模型注册（导入使 Base.metadata 完整，供 Alembic/测试使用）。"""
from __future__ import annotations

from .base import Base, utcnow
from .enums import (
    CancelOutcome,
    CostBasis,
    IdempotencyState,
    OutboundStatus,
    SessionRole,
    UsageBasis,
)
from .audit import AuditLog, SecurityEvent
from .generation import GenerationExecution, VerificationAttempt
from .idempotency import IdempotencyRecord
from .late_result import LateResultRecord
from .outbound import OutboundAuthorization, SendAuditRecord
from .proposal import ApprovalEvent, Feedback, ProposalVersion
from .repository import AnalysisBaseline, GitRepository
from .session import UserSession
from .task import RequirementVersion, Task

__all__ = [
    "Base",
    "utcnow",
    "CancelOutcome",
    "CostBasis",
    "IdempotencyState",
    "OutboundStatus",
    "SessionRole",
    "UsageBasis",
    "AuditLog",
    "GenerationExecution",
    "VerificationAttempt",
    "IdempotencyRecord",
    "LateResultRecord",
    "OutboundAuthorization",
    "SendAuditRecord",
    "ApprovalEvent",
    "Feedback",
    "ProposalVersion",
    "AnalysisBaseline",
    "GitRepository",
    "UserSession",
    "RequirementVersion",
    "Task",
]