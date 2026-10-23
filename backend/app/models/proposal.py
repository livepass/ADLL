"""方案版本链、反馈与审批事件（T019–T025）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow


class ProposalVersion(Base):
    """不可变方案版本（seq 在任务内唯一）。"""

    __tablename__ = "proposal_versions"
    __table_args__ = (UniqueConstraint("task_id", "seq", name="uq_proposal_task_seq"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    requirement_version_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_versions.id"), nullable=False
    )
    baseline_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_baselines.id"), nullable=False
    )
    execution_id: Mapped[int] = mapped_column(
        ForeignKey("generation_executions.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Feedback(Base):
    """修改意见（append-only；驱动新版本，但本批无真实 Adapter 不生成）。"""

    __tablename__ = "feedbacks"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    proposal_version_id: Mapped[int] = mapped_column(
        ForeignKey("proposal_versions.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ApprovalEvent(Base):
    """不可变审批事件，绑定五要素。"""

    __tablename__ = "approval_events"
    __table_args__ = (
        Index(
            "ux_approval_once",
            "proposal_version_id",
            unique=True,
            sqlite_where=text("decision = 'approved'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    proposal_version_id: Mapped[int] = mapped_column(
        ForeignKey("proposal_versions.id"), nullable=False
    )
    requirement_version_id: Mapped[int] = mapped_column(Integer, nullable=False)
    repo_identity: Mapped[str] = mapped_column(String(1024), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    proposal_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)  # approved/rejected
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )