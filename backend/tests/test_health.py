"""健康检查测试（依赖 fastapi/httpx 运行时可用；本批未安装则如实记录未运行）。"""
from __future__ import annotations


def test_health_ok(client) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    # 仅暴露运行模式开关（前端据此标识离线/Mock 与真实发送关闭），不含凭据。
    assert body["testing"] is True
    assert body["real_ai_enabled"] is False