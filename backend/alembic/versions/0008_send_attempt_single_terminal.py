"""一次发送尝试最多一个终态（并发终结保护）。

应用层在 `finish_attempt()` 里先查“是否已有终态”，但两个并发写入者可能同时
通过检查。该部分唯一索引在数据库层兜底：`attempt_id` 相同且 `phase <> 'prepared'`
的行只允许一行，第二个终态提交时触发 IntegrityError。

Revision ID: 0008
Revises: 0007
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ux_send_attempt_terminal",
        "send_audit_records",
        ["attempt_id"],
        unique=True,
        sqlite_where=sa.text("attempt_id IS NOT NULL AND phase <> 'prepared'"),
    )


def downgrade() -> None:
    op.drop_index("ux_send_attempt_terminal", table_name="send_audit_records")
