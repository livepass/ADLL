"""出站授权与发送审计（T011）。

- `OutboundAuthorization`：receiver/data_types/send_scope/状态/有效期；默认未批准即拒绝。
- `SendAuditRecord`：append-only（数据库触发器保护）；一次发送尝试由多行事件组成，
  以 `attempt_id` 关联，`phase` 区分：
    prepared        —— 已持久化请求摘要与载荷清单，尚未调用网络
    possibly_sent   —— 请求可能已写出（超时/HTTP 错误/取消中断），无成功响应证据
    confirmed_sent  —— 收到成功响应，可确认已发送
    not_sent        —— 发送前失败或被取消，确认未写出
  四类 payload_manifest（需求/反馈/源码/工具返回），候选 C 下「工具返回」恒空。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow
from .enums import OutboundStatus

SEND_PHASES = ("prepared", "possibly_sent", "confirmed_sent", "not_sent")


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
    __table_args__ = (
        # 一次尝试最多一个终态：即使应用层检查与并发终结发生竞态，
        # 数据库也会拒绝第二个终态，避免审计历史自相矛盾。
        Index(
            "ux_send_attempt_terminal",
            "attempt_id",
            unique=True,
            sqlite_where=text("attempt_id IS NOT NULL AND phase <> 'prepared'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    authorization_id: Mapped[int] = mapped_column(
        ForeignKey("outbound_authorizations.id"), nullable=False
    )
    execution_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 同一次发送尝试的所有事件共享 attempt_id。
    attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    phase: Mapped[str] = mapped_column(
        String(24), nullable=False, default="confirmed_sent"
    )
    receiver: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payload_manifest: Mapped[dict] = mapped_column(JSON, nullable=False)
    # manifest 摘要（四类内容）与完整 HTTP JSON 请求体摘要分开记录。
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SendReceiptEvidence(Base):
    """append-only 收据证据（S9-2）：不参与一次尝试的唯一终态约束。

    迟到收据（宿主重启后，attempt 已被 reconcile 补记 possibly_sent）必须以
    追加证据方式保留，而不是写入第二条终态。本表独立于
    `ux_send_attempt_terminal` 部分唯一索引，可安全容纳多条证据行。
    """
    __tablename__ = "send_receipt_evidence"
    __table_args__ = (
        # 并发幂等兜底：同一 attempt 的同一收据签名只能有一条可信证据。
        # 应用层「先查后插」在并发下会双双通过检查，数据库唯一索引负责拒绝第二次。
        Index(
            "ux_receipt_evidence_signature",
            "attempt_id",
            "kind",
            "receipt_signature",
            unique=True,
            sqlite_where=text("receipt_signature IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # "host_authorization" | "egress_send" | "late_receipt"
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # 收据签名的独立列（可空）：供数据库唯一索引做并发幂等，不依赖 JSON 查询。
    receipt_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 完整原始收据（含 signature/key_id 等），供离线复核；不重写 SendAuditRecord。
    receipt: Mapped[dict] = mapped_column(JSON, nullable=False)
    # 宿主验签结论：verified / signature_invalid / expired / mismatch / replayed
    verification: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
