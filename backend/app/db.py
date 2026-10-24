"""数据库底座（ADR-C1 SQLite + ADR-C2 SQLAlchemy 2.0）。

- 连接串由配置注入（不硬编码绝对路径）。
- SQLite 启用外键约束（PRAGMA foreign_keys=ON）与 WAL。
- 为 append-only 审计表安装数据库级保护触发器（UPDATE/DELETE 拒绝）。
"""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .models.base import Base

SQLITE_GUARDS: tuple[str, ...] = (
    "CREATE TRIGGER IF NOT EXISTS send_audit_no_update BEFORE UPDATE ON send_audit_records "
    "BEGIN SELECT RAISE(ABORT,'send_audit is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS send_audit_no_delete BEFORE DELETE ON send_audit_records "
    "BEGIN SELECT RAISE(ABORT,'send_audit is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS proposal_no_update BEFORE UPDATE ON proposal_versions "
    "BEGIN SELECT RAISE(ABORT,'proposal_versions is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS proposal_no_delete BEFORE DELETE ON proposal_versions "
    "BEGIN SELECT RAISE(ABORT,'proposal_versions is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS approval_no_update BEFORE UPDATE ON approval_events "
    "BEGIN SELECT RAISE(ABORT,'approval_events is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS approval_no_delete BEFORE DELETE ON approval_events "
    "BEGIN SELECT RAISE(ABORT,'approval_events is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS feedback_no_update BEFORE UPDATE ON feedbacks "
    "BEGIN SELECT RAISE(ABORT,'feedbacks is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS feedback_no_delete BEFORE DELETE ON feedbacks "
    "BEGIN SELECT RAISE(ABORT,'feedbacks is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS verification_no_update BEFORE UPDATE ON verification_attempts "
    "BEGIN SELECT RAISE(ABORT,'verification_attempts is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS verification_no_delete BEFORE DELETE ON verification_attempts "
    "BEGIN SELECT RAISE(ABORT,'verification_attempts is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_logs "
    "BEGIN SELECT RAISE(ABORT,'audit_logs is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_logs "
    "BEGIN SELECT RAISE(ABORT,'audit_logs is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS execution_terminal_freeze BEFORE UPDATE ON generation_executions "
    "WHEN OLD.status IN ('completed','failed','timeout','cancelled','late_result_discarded') "
    "AND NEW.status <> OLD.status "
    "BEGIN SELECT RAISE(ABORT,'generation execution terminal state frozen'); END",
    "CREATE TRIGGER IF NOT EXISTS late_no_update BEFORE UPDATE ON late_result_records "
    "BEGIN SELECT RAISE(ABORT,'late_result_records is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS late_no_delete BEFORE DELETE ON late_result_records "
    "BEGIN SELECT RAISE(ABORT,'late_result_records is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS send_receipt_evidence_no_update BEFORE UPDATE ON send_receipt_evidence "
    "BEGIN SELECT RAISE(ABORT,'send_receipt_evidence is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS send_receipt_evidence_no_delete BEFORE DELETE ON send_receipt_evidence "
    "BEGIN SELECT RAISE(ABORT,'send_receipt_evidence is append-only'); END",
    # 防重放登记一旦删改即可绕过单次处理，必须同样 append-only。
    "CREATE TRIGGER IF NOT EXISTS s9_replay_no_update BEFORE UPDATE ON s9_replay_guard "
    "BEGIN SELECT RAISE(ABORT,'s9_replay_guard is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS s9_replay_no_delete BEFORE DELETE ON s9_replay_guard "
    "BEGIN SELECT RAISE(ABORT,'s9_replay_guard is append-only'); END",
)


def _install_sqlite_pragmas(engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record):  # noqa: ANN001
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        try:
            cur.execute("PRAGMA journal_mode=WAL")
        except Exception:  # noqa: BLE001
            pass
        cur.close()


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30},
            future=True,
        )
        if url.startswith("sqlite"):
            _install_sqlite_pragmas(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)
        self.install_guards()

    def install_guards(self) -> None:
        if not self.url.startswith("sqlite"):
            return
        with self.engine.begin() as conn:
            for sql in SQLITE_GUARDS:
                conn.exec_driver_sql(sql)

    def session(self):
        return self.Session()