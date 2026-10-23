"""FastAPI 入口：应用工厂 + 健康检查 + 认证路由（测试路由仅 testing 模式挂载）。

本批（Foundational）不接入真实仓库/真实 AI。
"""
from __future__ import annotations

from fastapi import FastAPI

from .agents.factory import get_adapter
from .api.auth import router as auth_router
from .api.authorizations import router as authorizations_router
from .api.generations import router as generations_router
from .api.proposals import router as proposals_router
from .api.repositories import router as repositories_router
from .api.tasks import router as tasks_router
from .config import SETTINGS, Settings
from .core.errors import install_error_handlers
from .db import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or SETTINGS
    app = FastAPI(title=settings.app_name)
    install_error_handlers(app)

    app.state.settings = settings
    app.state.db = Database(settings.database_url)
    app.state.adapter_factory = lambda: get_adapter(settings)
    app.state.counter = {"n": 0}

    app.include_router(auth_router)
    app.include_router(repositories_router)
    app.include_router(tasks_router)
    app.include_router(proposals_router)
    app.include_router(generations_router)
    app.include_router(authorizations_router)
    if settings.testing:
        from .api.testing import router as testing_router

        app.include_router(testing_router)

    @app.get("/api/health")
    def health() -> dict:
        # 仅暴露运行模式开关，用于前端明确标识“离线/Mock”与真实发送是否关闭；不含凭据。
        return {
            "status": "ok",
            "app": settings.app_name,
            "testing": settings.testing,
            "real_ai_enabled": settings.real_ai_enabled,
        }

    # 重启恢复：遗留 running 执行标记 failed（证据不足不判 verified）
    try:
        from .services import generation_service

        reconcile_db = app.state.db.session()
        try:
            generation_service.reconcile_after_restart(reconcile_db)
        finally:
            reconcile_db.close()
    except Exception:  # noqa: BLE001 — 表未迁移时跳过
        pass

    return app


app = create_app()