"""Worker 查询接口。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.security import get_current_user
from ...services.manager import manager

router = APIRouter(prefix="/api", tags=["workers"], dependencies=[Depends(get_current_user)])


@router.get("/workers")
async def list_workers(
    refresh: bool = Query(False, description="重新执行 inspect"),
    status_only: bool = Query(False, alias="status", description="仅返回在线状态"),
    workername: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """对应 flower GET /api/workers。"""
    if refresh:
        await manager.refresh_workers(workername)

    if status_only:
        # 只返回当前 broker_url 中的 worker（事件层会混入其它 broker 的心跳）
        return manager.worker_status_map()

    if workername:
        if workername in manager.workers:
            return {workername: manager.workers[workername]}
        raise HTTPException(404, f"Unknown worker '{workername}'")

    # 真实模式下，若 inspector 尚未完成首次探测（首屏前 ~10s）则自动触发一次，
    # 避免 Workers 页初始空白需要手动刷新。
    if not manager.mock_mode and not manager.workers:
        await manager.refresh_workers()
    return dict(manager.workers)


@router.get("/workers/table")
async def workers_table(refresh: bool = False) -> Dict[str, Any]:
    """Dashboard 表格：worker 概览行。"""
    if refresh:
        await manager.refresh_workers()
    elif not manager.mock_mode and not manager.workers:
        await manager.refresh_workers()
    return {"data": manager.worker_rows()}


@router.get("/worker/{workername:path}")
async def get_worker(workername: str, refresh: bool = True) -> Dict[str, Any]:
    """Worker 详情，聚合 stats / queues / tasks / config。"""
    if refresh:
        await manager.refresh_workers(workername)

    info = manager.workers.get(workername)
    if info is None:
        raise HTTPException(404, f"Unknown worker '{workername}'")
    if "stats" not in info:
        raise HTTPException(404, f"Unable to get stats for '{workername}' worker")

    stats: Dict[str, Any] = info.get("stats") or {}
    reserved_keys = {
        "pool", "pid", "prefetch_count", "autoscaler", "consumer",
        "broker", "clock", "total", "rusage",
    }
    other = {k: v for k, v in stats.items() if k not in reserved_keys}
    broker_info = (stats.get("consumer") or stats).get("broker", {})

    state_worker = manager.state.workers.get(workername)

    return {
        "name": workername,
        "online": bool(state_worker.alive) if state_worker else True,
        "timestamp": info.get("timestamp"),
        "pool": stats.get("pool", {}),
        "pid": stats.get("pid"),
        "prefetch_count": stats.get("prefetch_count"),
        "autoscaler": stats.get("autoscaler"),
        "broker": broker_info,
        "rusage": stats.get("rusage") if isinstance(stats.get("rusage"), dict) else {},
        "total": stats.get("total", {}),
        "other": other,
        "active_queues": info.get("active_queues") or [],
        "registered": info.get("registered") or [],
        "active": info.get("active") or [],
        "scheduled": info.get("scheduled") or [],
        "reserved": info.get("reserved") or [],
        "revoked": info.get("revoked") or [],
        "conf": info.get("conf") or {},
    }
