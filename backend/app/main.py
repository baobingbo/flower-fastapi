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
    audit as audit_router,
    auth,
    broker,
    config as config_router,
    control,
    dashboard,
    dag,
    monitor,
    system as system_router,
    tasks,
    themes as themes_router,
    workers,
    alerts,
    ws,
    beats,
    users as users_router,
    init as init_router,
)
from .core.config import settings
from .services import restart as restart_service, runtime_config, theme_manager
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
    restart_service.settle_on_startup()  # #4：收口上一次重启的 pending 状态
    theme_manager.start_watcher()  # 启动主题目录监控线程
    await manager.startup()
    # 初始化用户数据库
    from .services.init_db import init_database
    init_database()
    # 初始化配置数据库表并迁移旧数据
    from .services.config_db import init_config_tables, migrate_from_env
    init_config_tables()
    migrate_from_env()
    # F-01: 初始化告警引擎
    from .services.alert import get_engine, reset_engine
    reset_engine()
    _alert_engine = get_engine()
    if settings.alert_enabled and settings.alert_rules:
        _n = _alert_engine.add_rules_from_config(settings.alert_rules)
        logger.info("告警引擎已初始化: %d 条规则从配置加载", _n)
    elif settings.alert_enabled:
        logger.info("告警引擎已启用，但未配置规则")
    else:
        logger.info("告警系统未启用")
    _apply_capacity()
    # B-10：启动醒目日志——打印 pid / 端口 / 模式，便于识别多实例静默抢占
    logger.info("=" * 62)
    logger.info(
        "FlowerUI 已启动 | pid=%d | 端口=%s | 模式=%s | broker=%s",
        os.getpid(),
        settings.port,
        "演示" if manager.mock_mode else "真实集群",
        settings.broker_url,
    )
    logger.info("=" * 62)
    try:
        yield
    finally:
        # 清理：关闭数据库连接等
        pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="FlowerUI",
        description="Flower 的增强 Web UI，支持多集群、RBAC 权限管理与配置热更新",
        version="2.0.0",
        lifespan=lifespan,
    )

    # 挂载所有路由
    app.include_router(auth.router)
    app.include_router(users_router.router)
    # 用户模块拆分的角色 / 权限管理路由
    from .api.routers import users as _users_mod
    app.include_router(_users_mod.roles_router)
    app.include_router(_users_mod.permissions_router)
    app.include_router(init_router.router)  # 新增初始化接口
    app.include_router(config_router.router)
    app.include_router(dashboard.router)
    app.include_router(tasks.router)
    app.include_router(workers.router)
    app.include_router(control.router)
    app.include_router(broker.router)
    app.include_router(dag.router)
    app.include_router(ws.router)
    app.include_router(beats.router)
    app.include_router(alerts.router)
    app.include_router(audit_router.router)
    app.include_router(themes_router.router)
    app.include_router(monitor.router)
    app.include_router(system_router.router)

    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 基础端点（须在静态文件挂载前注册，否则会被 "/" 前缀的静态路由拦截）
    @app.get("/health")
    async def health():
        """健康检查端点。"""
        return {"status": "ok", "service": "flowerui"}

    @app.get("/api/info")
    async def info():
        """系统信息端点。"""
        return {
            "name": "FlowerUI",
            "version": "2.0.0",
            "description": "Flower 增强 Web UI",
            "features": ["RBAC 权限管理", "SQLite 配置存储", "配置热更新"],
        }

    # 静态文件服务（必须最后挂载，否则会拦截其后注册的路由）
    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
    else:
        logger.warning("前端构建目录不存在: %s", FRONTEND_DIST)

    return app


app = create_app()
