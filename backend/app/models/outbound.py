"""出站授权与发送审计（T011）。

- `OutboundAuthorization`：receiver/data_types/send_scope/状态/有效期；默认未批准即拒绝。
- `SendAuditRecord`：append-only（数据库触发器保护）；四类 payload_manifest
  （需求/反馈/源码/工具返回），候选 C 下「工具返回」恒空。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow
from .enums import OutboundStatus


class OutboundAuthorization(Base):
    __tablename__ = "outbound_authorizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    baseline_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    requirement_version_id: Mapped[int | None] = mapped_column(nullable=True)
    baseline_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receiver: Mapped[str] = mapped_column(String(200), nullable=False)
    data_types: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    send_scope: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=OutboundStatus.PENDING.value, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SendAuditRecord(Base):
    __tablename__ = "send_audit_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    authorization_id: Mapped[int] = mapped_column(
        ForeignKey("outbound_authorizations.id"), nullable=False
    )
    execution_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_manifest: Mapped[dict] = mapped_column(JSON, nullable=False)
    # manifest 摘要（四类内容）与完整 HTTP JSON 请求体摘要分开记录。
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)