"""Alembic 迁移复验：upgrade → 表/触发器 → downgrade（回滚）→ 再 upgrade。"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

BACKEND = Path(__file__).resolve().parents[1]

ALL_TABLES = {
    "user_sessions",
    "idempotency_records",
    "outbound_authorizations",
    "send_audit_records",
    "git_repositories",
    "analysis_baselines",
    "tasks",
    "requirement_versions",
    "generation_executions",
    "verification_attempts",
    "proposal_versions",
    "feedbacks",
    "approval_events",
    "security_events",
    "audit_logs",
    "late_result_records",
}


def _cfg(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("prepend_sys_path", str(BACKEND))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_upgrade_and_downgrade(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ADLL_DATABASE_URL", raising=False)
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    cfg = _cfg(url)

    command.upgrade(cfg, "head")
    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert ALL_TABLES <= tables
        assert "alembic_version" in tables
        audit_columns = {
            column["name"]
            for column in inspect(engine).get_columns("send_audit_records")
        }
        assert "content_digest" in audit_columns
        assert "payload_digest" in audit_columns
        with engine.connect() as conn:
            triggers = {
                r[0]
                for r in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='trigger'")
                )
            }
        assert "send_audit_no_update" in triggers
        assert "send_audit_no_delete" in triggers
        assert "execution_terminal_freeze" in triggers
        assert "verification_no_update" in triggers
        assert "audit_no_update" in triggers
        assert "late_no_update" in triggers
    finally:
        engine.dispose()

    command.downgrade(cfg, "base")
    engine = create_engine(url)
    try:
        remaining = set(inspect(engine).get_table_names())
        assert not (ALL_TABLES & remaining)
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")