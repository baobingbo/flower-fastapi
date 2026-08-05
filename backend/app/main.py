"""FastAPI 应用入口：装配路由、生命周期、CORS 与前端静态资源。"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.routers import (
    auth,
    broker,
    config as config_router,
    control,
    dashboard,
    monitor,
    system as system_router,
    tasks,
    themes as themes_router,
    workers,
    ws,
)
from .core.config import settings
from .services import runtime_config, theme_manager
from .services.manager import manager

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("flowerui")

FRONTEND_DIST = Path(
    os.environ.get(
        "FLOWER_FRONTEND_DIST",
        Path(__file__).resolve().parents[2] / "frontend" / "dist",
    )
)


def _apply_capacity(_value=None) -> None:
    """容量类配置改动后同步到已经建好的 state 对象上，无需重启。"""
    state = getattr(manager, "state", None)
    if state is None:
        return
    state.max_workers_in_memory = settings.max_workers
    state.max_tasks_in_memory = settings.max_tasks


def _apply_debug(value) -> None:
    logging.getLogger().setLevel(logging.DEBUG if value else logging.INFO)


runtime_config.on_change("max_workers", _apply_capacity)
runtime_config.on_change("max_tasks", _apply_capacity)
runtime_config.on_change("debug", _apply_debug)


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime_config.load()
    theme_manager.start_watcher()  # 启动主题目录监控线程
    await manager.startup()
    _apply_capacity()
    logger.info(
        "FlowerUI 已启动 | 模式=%s | broker=%s",
        "演示" if manager.mock_mode else "真实集群",
        settings.broker_url,
    )
    try:
        yield
    finally:
        await manager.shutdown()


app = FastAPI(
    title="FlowerUI - Celery 实时监控",
    description="Flower 的 FastAPI + Vue 3 前后端分离重构版，功能对齐 Flower 2.0.1。",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (
    auth.router,
    config_router.router,
    workers.router,
    tasks.router,
    control.router,
    broker.router,
    dashboard.router,
    monitor.router,
    system_router.router,
    themes_router.router,
    ws.router,
):
    app.include_router(r)


@app.exception_handler(404)
async def spa_fallback(request, exc):
    """前端使用 history 路由，非 API 的 404 交还 index.html。"""
    path = request.url.path
    if path.startswith(("/api", "/ws", "/docs", "/redoc", "/openapi.json", "/metrics")):
        return JSONResponse({"detail": getattr(exc, "detail", "Not Found")}, status_code=404)
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"detail": "前端未构建，请先执行 npm run build"}, status_code=404)


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="static")
    logger.info("已挂载前端静态资源: %s", FRONTEND_DIST)
else:
    @app.get("/", include_in_schema=False)
    async def root():
        return {
            "name": "FlowerUI",
            "docs": "/docs",
            "hint": "前端尚未构建，运行 cd frontend && npm install && npm run build",
        }
