"""应用配置——路径与凭据经环境配置注入（AGENTS.md §3：不硬编码绝对路径）。

本批新增：认证凭据（env 注入）、会话 TTL、Cookie Secure 开关、测试开关。
未注入 `ADLL_ADMIN_PASSWORD` 时登录能力默认关闭（fail-closed）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str
    database_url: str
    cors_origins: tuple[str, ...]
    dashscope_base_url: str
    admin_password: str | None
    session_ttl_seconds: int
    cookie_secure: bool
    testing: bool
    authorized_roots: tuple[str, ...] = ()
    git_timeout_seconds: int = 30
    real_ai_enabled: bool = False
    dashscope_model: str = "qwen3.7-flash-2026-07-15"
    dashscope_endpoint: str = (
        "https://dashscope.aliyuncs.com/apps/anthropic/v1/messages"
    )
    worker_sandbox_root: str | None = None
    worker_acl_root: str | None = None
    worker_deny_read: tuple[str, ...] = ()
    worker_deny_write: tuple[str, ...] = ()
    worker_python: str | None = None
    worker_real_transport: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        roots = tuple(
            r.strip() for r in os.getenv("ADLL_AUTHORIZED_ROOTS", "").split(os.pathsep) if r.strip()
        )
        return cls(
            app_name=os.getenv("ADLL_APP_NAME", "ADLL"),
            database_url=os.getenv("ADLL_DATABASE_URL", "sqlite:///./data/adll.db"),
            cors_origins=tuple(
                o.strip() for o in os.getenv("ADLL_CORS_ORIGINS", "").split(",") if o.strip()
            ),
            dashscope_base_url=os.getenv(
                "ADLL_DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/apps/anthropic"
            ),
            admin_password=os.getenv("ADLL_ADMIN_PASSWORD") or None,
            session_ttl_seconds=int(os.getenv("ADLL_SESSION_TTL_SECONDS", "3600")),
            cookie_secure=_env_bool("ADLL_COOKIE_SECURE", False),
            testing=_env_bool("ADLL_TESTING", False),
            authorized_roots=roots,
            git_timeout_seconds=int(os.getenv("ADLL_GIT_TIMEOUT_SECONDS", "30")),
            real_ai_enabled=_env_bool("ADLL_REAL_AI_ENABLED", False),
            dashscope_model=os.getenv(
                "ADLL_DASHSCOPE_MODEL", "qwen3.7-flash-2026-07-15"
            ),
            dashscope_endpoint=os.getenv(
                "ADLL_DASHSCOPE_ENDPOINT",
                "https://dashscope.aliyuncs.com/apps/anthropic/v1/messages",
            ),
            worker_sandbox_root=os.getenv("ADLL_WORKER_SANDBOX_ROOT") or None,
            worker_acl_root=os.getenv("ADLL_WORKER_ACL_ROOT") or None,
            worker_deny_read=tuple(
                p.strip()
                for p in os.getenv("ADLL_WORKER_DENY_READ", "").split(os.pathsep)
                if p.strip()
            ),
            worker_deny_write=tuple(
                p.strip()
                for p in os.getenv("ADLL_WORKER_DENY_WRITE", "").split(os.pathsep)
                if p.strip()
            ),
            worker_python=os.getenv("ADLL_WORKER_PYTHON") or None,
            worker_real_transport=_env_bool("ADLL_WORKER_REAL_TRANSPORT", False),
        )


SETTINGS = Settings.from_env()