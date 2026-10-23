"""Git 仓库关联与分析基准（T012/T013）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow


class GitRepository(Base):
    __tablename__ = "git_repositories"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    repo_identity: Mapped[str] = mapped_column(String(1024), nullable=False)
    object_format: Mapped[str] = mapped_column(String(8), nullable=False)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class AnalysisBaseline(Base):
    """不可变分析基准：绑定 repo/object_format/完整 commit SHA/工作区决定。"""

    __tablename__ = "analysis_baselines"

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("git_repositories.id"), nullable=False
    )
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    object_format: Mapped[str] = mapped_column(String(8), nullable=False)
    workspace_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    unavailable_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    inventory_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )