"""US1 tables: repositories, baselines, tasks, requirement versions

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "git_repositories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("repo_identity", sa.String(length=1024), nullable=False),
        sa.Column("object_format", sa.String(length=8), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "analysis_baselines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "repository_id", sa.Integer(), sa.ForeignKey("git_repositories.id"), nullable=False
        ),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column("object_format", sa.String(length=8), nullable=False),
        sa.Column("workspace_decision", sa.String(length=32), nullable=False),
        sa.Column("snapshot_digest", sa.String(length=64), nullable=True),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("unavailable_reason", sa.String(length=255), nullable=True),
        sa.Column("inventory_summary", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "repository_id", sa.Integer(), sa.ForeignKey("git_repositories.id"), nullable=False
        ),
        sa.Column(
            "baseline_id", sa.Integer(), sa.ForeignKey("analysis_baselines.id"), nullable=False
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "requirement_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "seq", name="uq_requirement_task_seq"),
    )

    op.add_column(
        "outbound_authorizations", sa.Column("task_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "outbound_authorizations", sa.Column("baseline_id", sa.Integer(), nullable=True)
    )
    op.create_index("ix_outbound_task_id", "outbound_authorizations", ["task_id"])
    op.create_index("ix_outbound_baseline_id", "outbound_authorizations", ["baseline_id"])


def downgrade() -> None:
    op.drop_index("ix_outbound_baseline_id", table_name="outbound_authorizations")
    op.drop_index("ix_outbound_task_id", table_name="outbound_authorizations")
    with op.batch_alter_table("outbound_authorizations") as batch:
        batch.drop_column("baseline_id")
        batch.drop_column("task_id")
    op.drop_table("requirement_versions")
    op.drop_table("tasks")
    op.drop_table("analysis_baselines")
    op.drop_table("git_repositories")