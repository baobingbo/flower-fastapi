"""Dashboard 聚合接口：概览卡片、趋势时间线、筛选项、任务分布。"""
from __future__ import annotations

import collections
import time
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

from ...core.config import settings
from ...core.security import get_current_user
from ...services.hub import hub
from ...services.manager import manager

router = APIRouter(prefix="/api", tags=["dashboard"], dependencies=[Depends(get_current_user)])


@router.get("/dashboard/summary")
async def summary() -> Dict[str, Any]:
    return manager.dashboard_summary()


@router.get("/dashboard/snapshot")
async def snapshot(
    since: int = Query(0, ge=0, description="事件游标，传上一次返回的 cursor 做增量拉取"),
    timeline_limit: int = Query(120, ge=1, le=720),
    events: bool = Query(True, description="是否附带事件流"),
    event_limit: int = Query(120, ge=1, le=500),
) -> Dict[str, Any]:
    """一次请求拿齐 Dashboard 所需的全部实时数据。

    这是「HTTP 轮询」模式的主力接口：语义与 WebSocket 首帧 snapshot 对齐，
    额外带上事件游标，让轮询也能做到事件不重不漏。
    """
    payload: Dict[str, Any] = {
        "summary": manager.dashboard_summary(),
        "workers": manager.worker_rows(),
        "timeline": manager.state.get_timeline(timeline_limit),
        "server_time": time.time(),
    }
    if events:
        payload.update(hub.recent(since=since, limit=event_limit))
    else:
        payload.update({"cursor": hub.cursor, "events": []})
    return payload


@router.get("/dashboard/timeline")
async def timeline(limit: int = Query(120, ge=1, le=720)) -> Dict[str, Any]:
    return {"points": manager.state.get_timeline(limit)}


@router.get("/dashboard/filters")
async def filters() -> Dict[str, Any]:
    """前端下拉框选项：worker / 任务类型 / 状态 / 队列。"""
    states = sorted(manager.state.totals().keys())
    return {
        "workers": manager.state.worker_names(),
        "task_types": manager.state.task_types(),
        "states": states or [
            "PENDING", "RECEIVED", "STARTED", "SUCCESS",
            "FAILURE", "RETRY", "REVOKED",
        ],
        "queues": manager.active_queue_names(),
        "columns": settings.task_columns_list,
    }


@router.get("/dashboard/task-distribution")
async def task_distribution(top: int = Query(10, ge=1, le=50)) -> Dict[str, Any]:
    """按任务名统计成功 / 失败 / 平均耗时，用于饼图与柱状图。"""
    agg: Dict[str, Dict[str, Any]] = collections.defaultdict(
        lambda: {"total": 0, "succeeded": 0, "failed": 0, "retried": 0,
                 "revoked": 0, "runtime_sum": 0.0, "runtime_n": 0}
    )
    for task in list(manager.state.tasks.values()):
        name = task.name or "unknown"
        item = agg[name]
        item["total"] += 1
        if task.state == "SUCCESS":
            item["succeeded"] += 1
        elif task.state == "FAILURE":
            item["failed"] += 1
        elif task.state == "RETRY":
            item["retried"] += 1
        elif task.state == "REVOKED":
            item["revoked"] += 1
        runtime = getattr(task, "runtime", None)
        if runtime:
            item["runtime_sum"] += runtime
            item["runtime_n"] += 1

    rows: List[Dict[str, Any]] = []
    for name, item in agg.items():
        rows.append({
            "name": name,
            "total": item["total"],
            "succeeded": item["succeeded"],
            "failed": item["failed"],
            "retried": item["retried"],
            "revoked": item["revoked"],
            "avg_runtime": round(item["runtime_sum"] / item["runtime_n"], 4)
            if item["runtime_n"] else None,
        })
    rows.sort(key=lambda r: r["total"], reverse=True)
    return {"data": rows[:top]}
