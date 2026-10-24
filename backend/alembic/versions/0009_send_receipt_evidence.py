"""收据证据表（S9-2）：迟到收据追加证据，不参与唯一终态约束。

宿主重启后，attempt 可能已被 reconcile 补记 possibly_sent；此时再收到有效迟到
收据，不得写入第二条终态（会触发 0008 部分唯一索引），只能以 append-only 证据行
保留。本表独立于 `ux_send_attempt_terminal`，可安全容纳多条证据。

Revision ID: 0009
Revises: 0008
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "send_receipt_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("attempt_id", sa.String(36), nullable=False, index=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("receipt", sa.JSON(), nullable=False),
        sa.Column("verification", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("send_receipt_evidence")
