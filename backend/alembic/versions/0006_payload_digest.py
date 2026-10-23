"""Add payload_digest to send_audit_records.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("send_audit_records") as batch:
        batch.add_column(sa.Column("payload_digest", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("send_audit_records") as batch:
        batch.drop_column("payload_digest")