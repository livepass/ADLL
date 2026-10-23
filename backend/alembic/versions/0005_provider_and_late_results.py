"""Provider marker + LateResultRecord (cancellation/late results)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generation_executions", sa.Column("provider", sa.String(length=32), nullable=True)
    )
    op.create_table(
        "late_result_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "execution_id",
            sa.Integer(),
            sa.ForeignKey("generation_executions.id"),
            nullable=False,
        ),
        sa.Column("arrival_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("disposition", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS late_no_update BEFORE UPDATE ON late_result_records "
        "BEGIN SELECT RAISE(ABORT,'late_result_records is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER IF NOT EXISTS late_no_delete BEFORE DELETE ON late_result_records "
        "BEGIN SELECT RAISE(ABORT,'late_result_records is append-only'); END"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS late_no_update")
    op.execute("DROP TRIGGER IF EXISTS late_no_delete")
    op.drop_table("late_result_records")
    with op.batch_alter_table("generation_executions") as batch:
        batch.drop_column("provider")