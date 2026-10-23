"""基础枚举（与 data-model.md / 契约口径一致）。"""
from __future__ import annotations

from enum import StrEnum


class SessionRole(StrEnum):
    USER = "user"
    AGENT = "agent"


class IdempotencyState(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"


class OutboundStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REVOKED = "revoked"


class CostBasis(StrEnum):
    ACTUAL = "actual"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class UsageBasis(StrEnum):
    ACTUAL = "actual"
    UNAVAILABLE = "unavailable"


class CancelOutcome(StrEnum):
    CANCELLED = "cancelled"
    NOT_CANCELLED = "not_cancelled"
    ALREADY_FINISHED = "already_finished"