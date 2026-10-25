"""S9-3A 合成链路：持久化防重放登记。

两道唯一约束，任一命中即拒绝再次放行：
- `(consumer, attempt_id)`：同一消费方对同一发送尝试只处理一次；
- `(consumer, nonce)`（部分索引，nonce 非空）：不同 attempt 复用同一已消费
  nonce 同样拒绝——nonce 是一次性值，不是 attempt 的附属标签。

重启后从数据库恢复「已见过」集合，不依赖内存状态。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow


class S9ReplayGuard(Base):
    __tablename__ = "s9_replay_guard"
    __table_args__ = (
        UniqueConstraint("consumer", "attempt_id", name="ux_s9_replay_consumer_attempt"),
        # nonce 复用检测：不同 attempt 复用同一 nonce 必须拒绝。
        Index(
            "ux_s9_replay_consumer_nonce",
            "consumer",
            "nonce",
            unique=True,
            sqlite_where=text("nonce IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # "launcher" | "egress"
    consumer: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    nonce: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
