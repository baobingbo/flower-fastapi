"""启动与基础端点：健康检查、系统信息、静态资源、OpenAPI、Prometheus 指标。"""
from __future__ import annotations


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "flowerui"}


def test_healthcheck_alias(client):
    assert client.get("/healthcheck").status_code == 200


def test_api_info(client):
    r = client.get("/api/info")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "FlowerUI"
    assert body["version"]


def test_system(client, admin_headers):
    r = client.get("/api/system", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["mock_mode"] is True  # 测试环境固定 mock 模式
    assert body["pid"] > 0
    assert "started_at" in body and "uptime" in body


def test_frontend_served(client):
    """frontend/dist 存在时，根路径应返回前端首页（HTML）。"""
    r = client.get("/")
    if r.status_code == 404:  # dist 未构建的环境
        import pytest
        pytest.skip("frontend/dist 未构建")
    assert r.status_code == 200
    assert "<html" in r.text.lower() or "<!doctype" in r.text.lower()


def test_openapi_and_docs(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    # 关键 API 都应暴露在 OpenAPI 文档中
    # 新版 FastAPI 在 OpenAPI 文档里把 {x:path} 规范化为 {x}
    for p in ("/api/auth/login", "/api/config", "/api/tasks/table", "/api/worker/pool/grow/{workername}", "/api/task/apply/{taskname}"):
        assert p in paths, "OpenAPI 缺少 " + p
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200


def test_metrics(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    names = {
        line.split("{")[0].split(" ")[0]
        for line in r.text.splitlines()
        if line.startswith("flower_")
    }
    for metric in ("flower_events_total", "flower_worker_online"):
        assert any(n.startswith(metric) for n in names), "缺少指标 " + metric


def test_unknown_api_returns_json_404(client):
    r = client.get("/api/definitely-not-here")
    assert r.status_code == 404
    assert r.headers.get("content-type", "").startswith("application/json")
