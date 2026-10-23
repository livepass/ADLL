"""Cancel fields + immutability/freeze triggers (minimal fix)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TRIGGERS = (
    (
        "verification_no_update",
        "verification_attempts",
        "UPDATE",
        "verification_attempts is append-only",
    ),
    (
        "verification_no_delete",
        "verification_attempts",
        "DELETE",
        "verification_attempts is append-only",
    ),
    ("audit_no_update", "audit_logs", "UPDATE", "audit_logs is append-only"),
    ("audit_no_delete", "audit_logs", "DELETE", "audit_logs is append-only"),
    (
        "execution_terminal_freeze",
        "generation_executions",
        "UPDATE",
        "generation execution terminal state frozen",
    ),
)


def upgrade() -> None:
    op.add_column(
        "generation_executions",
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "generation_executions", sa.Column("cancel_outcome", sa.String(length=32), nullable=True)
    )
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS verification_no_update BEFORE UPDATE ON verification_attempts "
        "BEGIN SELECT RAISE(ABORT,'verification_attempts is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS verification_no_delete BEFORE DELETE ON verification_attempts "
        "BEGIN SELECT RAISE(ABORT,'verification_attempts is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_logs "
        "BEGIN SELECT RAISE(ABORT,'audit_logs is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_logs "
        "BEGIN SELECT RAISE(ABORT,'audit_logs is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS execution_terminal_freeze BEFORE UPDATE ON generation_executions "
        "WHEN OLD.status IN ('completed','failed','timeout','cancelled','late_result_discarded') "
        "AND NEW.status <> OLD.status "
        "BEGIN SELECT RAISE(ABORT,'generation execution terminal state frozen'); END"
    )


def downgrade() -> None:
    for name, _table, _event, _message in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    with op.batch_alter_table("generation_executions") as batch:
        batch.drop_column("cancel_outcome")
        batch.drop_column("cancel_requested")