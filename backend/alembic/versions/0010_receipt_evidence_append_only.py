"""收据证据表 append-only 触发器（S9-2 收口）：禁止 UPDATE/DELETE。

SendReceiptEvidence 一旦写入即不可变（append-only），防止迟到收据证据被改写或
删除后伪造「可信发送事实」。与既有 append-only 触发器模式一致（SQLite RAISE(ABORT)）。

Revision ID: 0010
Revises: 0009
"""
from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

APPEND_ONLY_TRIGGERS = (
    ("send_receipt_evidence_no_update", "send_receipt_evidence", "UPDATE", "send_receipt_evidence is append-only"),
    ("send_receipt_evidence_no_delete", "send_receipt_evidence", "DELETE", "send_receipt_evidence is append-only"),
)


def upgrade() -> None:
    for name, table, event, message in APPEND_ONLY_TRIGGERS:
        op.execute(
            f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE {event} ON {table} "
            f"BEGIN SELECT RAISE(ABORT,'{message}'); END"
        )


def downgrade() -> None:
    for name, _table, _event, _message in APPEND_ONLY_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
