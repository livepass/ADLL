"""Send audit becomes an append-only attempt log.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("send_audit_records") as batch:
        batch.add_column(sa.Column("attempt_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column(
                "phase",
                sa.String(length=24),
                nullable=False,
                server_default="confirmed_sent",
            )
        )
        batch.add_column(sa.Column("receiver", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("request_digest", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("error_code", sa.String(length=120), nullable=True))
    op.create_index(
        "ix_send_audit_records_attempt_id", "send_audit_records", ["attempt_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_send_audit_records_attempt_id", table_name="send_audit_records")
    with op.batch_alter_table("send_audit_records") as batch:
        batch.drop_column("error_code")
        batch.drop_column("request_digest")
        batch.drop_column("receiver")
        batch.drop_column("phase")
        batch.drop_column("attempt_id")
