"""nonce 防重放（S9-3A 问题 C）：`(consumer, nonce)` 部分唯一索引。

`(consumer, attempt_id)` 只能防止「同一 attempt 重复提交」；不同 attempt 若复用
同一 nonce，仍会被放行。nonce 是一次性值，必须在消费方维度全局唯一。

历史行 `nonce` 可能为 NULL（早期写入），部分索引只约束非 NULL 行。

Revision ID: 0013
Revises: 0012
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ux_s9_replay_consumer_nonce",
        "s9_replay_guard",
        ["consumer", "nonce"],
        unique=True,
        sqlite_where=sa.text("nonce IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_s9_replay_consumer_nonce", table_name="s9_replay_guard")
