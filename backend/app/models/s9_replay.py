"""S9-3A 合成链路：持久化防重放登记。

`(consumer, attempt_id)` 唯一约束保证同一消费方对同一发送尝试只处理一次；
重启后从数据库恢复「已见过」集合，不依赖内存状态。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow


class S9ReplayGuard(Base):
    __tablename__ = "s9_replay_guard"
    __table_args__ = (
        UniqueConstraint("consumer", "attempt_id", name="ux_s9_replay_consumer_attempt"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # "launcher" | "egress"
    consumer: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    nonce: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
