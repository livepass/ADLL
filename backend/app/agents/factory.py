"""适配器工厂：Mock 仅测试注入；真实适配器需显式启用且隔离核验通过（fail-closed）。"""
from __future__ import annotations

from ..config import Settings
from .base import AgentAdapter
from .mock import MockAgentAdapter


class NoRealAdapterAvailable(RuntimeError):
    pass


def get_adapter(settings: Settings) -> AgentAdapter:
    if settings.testing:
        return MockAgentAdapter()
    if settings.real_ai_enabled:
        from .worker import WorkerAgentAdapter

        return WorkerAgentAdapter(
            endpoint=settings.dashscope_endpoint,
            model=settings.dashscope_model,
            sandbox_root=settings.worker_sandbox_root,
            acl_root=settings.worker_acl_root,
            deny_read=settings.worker_deny_read,
            deny_write=settings.worker_deny_write,
            python_executable=settings.worker_python,
            synthetic=False,
            real_transport=settings.worker_real_transport,
        )
    raise NoRealAdapterAvailable(
        "real AI disabled (default fail-closed); Mock is test-only"
    )