"""运维接口：Prometheus 指标与健康检查（对齐 flower /metrics、/healthcheck）。"""
from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ...core.celery_app import broker_uri, mask_url_password, transport_driver
from ...services.manager import manager

# 这两个端点不做鉴权，方便被 Prometheus / K8s 探针直接抓取
router = APIRouter(tags=["monitor"])


@router.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/healthcheck")
async def healthcheck() -> Dict[str, str]:
    return {"status": "OK"}


@router.get("/api/system")
async def system_info() -> Dict[str, Any]:
    """系统信息面板：运行模式、broker、容量配置。"""
    import platform
    import sys

    import celery

    from ...core.config import settings

    return {
        "mock_mode": manager.mock_mode,
        "broker_url": broker_uri(),
        "transport": transport_driver(),
        # 未配置 result backend 时 /api/task/apply 与 /api/task/result 无法取回结果，
        # 这里显式暴露，避免用户对着 503 猜原因。
        # 与 broker_url 一样必须脱敏：结果后端连接串常带密码，直接回显会泄露。
        "result_backend": (
            mask_url_password(settings.result_backend)
            if settings.result_backend else None
        ),
        "result_backend_configured": manager.backend_configured(),
        "events_connected": bool(manager.events and manager.events.connected),
        "uptime": int(time.time() - manager.started_at),
        "python_version": sys.version.split()[0],
        "celery_version": celery.__version__,
        "platform": platform.platform(),
        # 只统计当前 broker_url 中的 worker；事件广播会混入其它 broker/db 的
        # 心跳，foreign_workers_hidden 记录被隔离的数量，便于排障。
        "workers_in_memory": manager.configured_worker_count(),
        "foreign_workers_hidden": manager.foreign_worker_count(),
        "tasks_in_memory": len(manager.state.tasks),
    }
