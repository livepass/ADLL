"""S9-3A 合成链路的持久化防重放登记（append-only）。

每个消费方（launcher / egress）对同一 `attempt_id` 只允许处理一次；重复提交在
数据库层被 (consumer, attempt_id) 唯一索引拒绝，因此重启后仍能恢复「已见过」集合，
不依赖进程内存。

Revision ID: 0012
Revises: 0011
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

APPEND_ONLY_TRIGGERS = (
    ("s9_replay_no_update", "UPDATE"),
    ("s9_replay_no_delete", "DELETE"),
)


def upgrade() -> None:
    op.create_table(
        "s9_replay_guard",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("consumer", sa.String(32), nullable=False),
        sa.Column("attempt_id", sa.String(36), nullable=False),
        sa.Column("nonce", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "consumer", "attempt_id", name="ux_s9_replay_consumer_attempt"
        ),
    )
    op.create_index("ix_s9_replay_attempt_id", "s9_replay_guard", ["attempt_id"])
    # 删改登记即可绕过单次处理，必须 append-only。
    for name, event in APPEND_ONLY_TRIGGERS:
        op.execute(
            f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE {event} ON s9_replay_guard "
            f"BEGIN SELECT RAISE(ABORT,'s9_replay_guard is append-only'); END"
        )


def downgrade() -> None:
    for name, _event in APPEND_ONLY_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_index("ix_s9_replay_attempt_id", table_name="s9_replay_guard")
    op.drop_table("s9_replay_guard")
