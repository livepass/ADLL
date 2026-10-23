"""生成执行与核验尝试（T019 必需的证据结构；本批不接真实生成）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow


class GenerationExecution(Base):
    __tablename__ = "generation_executions"
    __table_args__ = (
        Index(
            "ux_active_generation",
            "task_id",
            unique=True,
            sqlite_where=text("status = 'running'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    baseline_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_baselines.id"), nullable=False
    )
    requirement_version_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_versions.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cancel_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outbound_authorization_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    usage_basis: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cost: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VerificationAttempt(Base):
    __tablename__ = "verification_attempts"
    __table_args__ = (
        UniqueConstraint("execution_id", "attempt_no", name="uq_verification_exec_attempt"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    execution_id: Mapped[int] = mapped_column(
        ForeignKey("generation_executions.id"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # verified/unconfirmed/failed
    pre_baseline_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    post_compare_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    coverage_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    isolation_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evidence_sufficiency: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )