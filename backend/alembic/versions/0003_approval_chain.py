"""Approval chain: generation, verification, proposals, feedback, approvals, audits

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

APPEND_ONLY_TRIGGERS = (
    ("proposal_no_update", "proposal_versions", "UPDATE", "proposal_versions is immutable"),
    ("proposal_no_delete", "proposal_versions", "DELETE", "proposal_versions is immutable"),
    ("approval_no_update", "approval_events", "UPDATE", "approval_events is immutable"),
    ("approval_no_delete", "approval_events", "DELETE", "approval_events is immutable"),
    ("feedback_no_update", "feedbacks", "UPDATE", "feedbacks is append-only"),
    ("feedback_no_delete", "feedbacks", "DELETE", "feedbacks is append-only"),
)


def upgrade() -> None:
    op.create_table(
        "generation_executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column(
            "baseline_id", sa.Integer(), sa.ForeignKey("analysis_baselines.id"), nullable=False
        ),
        sa.Column(
            "requirement_version_id",
            sa.Integer(),
            sa.ForeignKey("requirement_versions.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("failure_reason", sa.String(length=255), nullable=True),
        sa.Column("outbound_authorization_id", sa.Integer(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("usage_basis", sa.String(length=16), nullable=True),
        sa.Column("cost", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ux_active_generation",
        "generation_executions",
        ["task_id"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "verification_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "execution_id",
            sa.Integer(),
            sa.ForeignKey("generation_executions.id"),
            nullable=False,
        ),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("pre_baseline_ref", sa.String(length=255), nullable=True),
        sa.Column("post_compare_ref", sa.String(length=255), nullable=True),
        sa.Column("coverage_note", sa.Text(), nullable=True),
        sa.Column("isolation_evidence", sa.JSON(), nullable=True),
        sa.Column("evidence_sufficiency", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("execution_id", "attempt_no", name="uq_verification_exec_attempt"),
    )

    op.create_table(
        "proposal_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column(
            "requirement_version_id",
            sa.Integer(),
            sa.ForeignKey("requirement_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "baseline_id", sa.Integer(), sa.ForeignKey("analysis_baselines.id"), nullable=False
        ),
        sa.Column(
            "execution_id",
            sa.Integer(),
            sa.ForeignKey("generation_executions.id"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "seq", name="uq_proposal_task_seq"),
    )

    op.create_table(
        "feedbacks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column(
            "proposal_version_id",
            sa.Integer(),
            sa.ForeignKey("proposal_versions.id"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "approval_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column(
            "proposal_version_id",
            sa.Integer(),
            sa.ForeignKey("proposal_versions.id"),
            nullable=False,
        ),
        sa.Column("requirement_version_id", sa.Integer(), nullable=False),
        sa.Column("repo_identity", sa.String(length=1024), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column("proposal_content_hash", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ux_approval_once",
        "approval_events",
        ["proposal_version_id"],
        unique=True,
        sqlite_where=sa.text("decision = 'approved'"),
    )

    op.create_table(
        "security_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column("tasks", sa.Column("current_approval_id", sa.Integer(), nullable=True))
    op.create_index("ix_tasks_current_approval_id", "tasks", ["current_approval_id"])

    for name, table, event, message in APPEND_ONLY_TRIGGERS:
        op.execute(
            f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE {event} ON {table} "
            f"BEGIN SELECT RAISE(ABORT,'{message}'); END"
        )


def downgrade() -> None:
    for name, _table, _event, _message in APPEND_ONLY_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_index("ix_tasks_current_approval_id", table_name="tasks")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("current_approval_id")
    op.drop_index("ux_approval_once", table_name="approval_events")
    op.drop_table("audit_logs")
    op.drop_table("security_events")
    op.drop_table("approval_events")
    op.drop_table("feedbacks")
    op.drop_table("proposal_versions")
    op.drop_table("verification_attempts")
    op.drop_index("ux_active_generation", table_name="generation_executions")
    op.drop_table("generation_executions")