"""initial foundational tables

Revision ID: 0001
Revises:
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_sessions_token_hash", "user_sessions", ["token_hash"], unique=True)

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_idempotency_records_key", "idempotency_records", ["key"], unique=True)

    op.create_table(
        "outbound_authorizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("requirement_version_id", sa.Integer(), nullable=True),
        sa.Column("baseline_commit", sa.String(length=64), nullable=True),
        sa.Column("receiver", sa.String(length=200), nullable=False),
        sa.Column("data_types", sa.JSON(), nullable=False),
        sa.Column("send_scope", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "send_audit_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "authorization_id",
            sa.Integer(),
            sa.ForeignKey("outbound_authorizations.id"),
            nullable=False,
        ),
        sa.Column("execution_id", sa.String(length=64), nullable=True),
        sa.Column("payload_manifest", sa.JSON(), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.execute(
        "CREATE TRIGGER IF NOT EXISTS send_audit_no_update BEFORE UPDATE ON send_audit_records "
        "BEGIN SELECT RAISE(ABORT,'send_audit is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS send_audit_no_delete BEFORE DELETE ON send_audit_records "
        "BEGIN SELECT RAISE(ABORT,'send_audit is append-only'); END"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS send_audit_no_update")
    op.execute("DROP TRIGGER IF EXISTS send_audit_no_delete")
    op.drop_table("send_audit_records")
    op.drop_table("outbound_authorizations")
    op.drop_index("ix_idempotency_records_key", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("ix_user_sessions_token_hash", table_name="user_sessions")
    op.drop_table("user_sessions")