"""收据证据并发幂等（S9-2 收口）：receipt_signature 列 + 唯一索引。

应用层 record_late_receipt 的「先查后插」在并发下会让两个写入者都通过检查，
从而产生重复可信证据。本迁移增加独立的 `receipt_signature` 列并建立
(attempt_id, kind, receipt_signature) 唯一索引，由数据库兜底拒绝第二次。

`receipt_signature` 允许 NULL（历史/非收据类证据），部分唯一索引只约束非 NULL 行。

Revision ID: 0011
Revises: 0010
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("send_receipt_evidence") as batch:
        batch.add_column(sa.Column("receipt_signature", sa.String(128), nullable=True))
    op.create_index(
        "ux_receipt_evidence_signature",
        "send_receipt_evidence",
        ["attempt_id", "kind", "receipt_signature"],
        unique=True,
        sqlite_where=sa.text("receipt_signature IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_receipt_evidence_signature", table_name="send_receipt_evidence")
    with op.batch_alter_table("send_receipt_evidence") as batch:
        batch.drop_column("receipt_signature")
