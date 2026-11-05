"""Worker 查询接口。"""
from __future__ import annotations

import csv
import datetime
import io
import json
from typing import Any, Dict, Iterator, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

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
        return {
            name: bool(w.alive) for name, w in manager.state.workers.items()
        }

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


# ----------------------------------------------------------------------
# 导出（F-05）
# ----------------------------------------------------------------------
WORKER_EXPORT_COLUMNS = [
    ("name", "Worker"),
    ("status", "状态"),
    ("active", "活跃"),
    ("processed", "已处理"),
    ("succeeded", "成功"),
    ("failed", "失败"),
    ("retried", "重试"),
    ("revoked", "撤销"),
    ("concurrency", "并发"),
    ("loadavg", "负载"),
    ("pid", "PID"),
    ("sw_ident", "软件"),
    ("sw_ver", "版本"),
    ("sw_sys", "系统"),
    ("freq", "心跳周期"),
    ("queues", "消费队列"),
]


@router.get("/workers/export")
async def export_workers(
    format: str = Query("csv", pattern="^(csv|json)$"),
    workername: Optional[str] = Query(None, description="按名称模糊过滤"),
    status: Optional[bool] = Query(None, description="仅导出在线/离线"),
) -> Any:
    """导出 Worker 列表，csv（utf-8-sig，Excel 中文不乱码）或 json 数组。"""
    rows = manager.worker_rows()
    if workername:
        kw = workername.strip().lower()
        rows = [r for r in rows if kw in str(r.get("name", "")).lower()]
    if status is not None:
        rows = [r for r in rows if bool(r.get("status")) == status]

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if format == "json":
        body = json.dumps(rows, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="workers-{stamp}.json"'},
        )

    def _cell(row: Dict[str, Any], key: str) -> str:
        value = row.get(key)
        if value is None:
            return ""
        if key == "status":
            return "在线" if value else "离线"
        if key == "loadavg" and isinstance(value, list):
            return " ".join(str(v) for v in value)
        if key == "queues" and isinstance(value, list):
            return ", ".join(str(v) for v in value)
        return str(value)

    def _gen() -> Iterator[bytes]:
        yield b"\xef\xbb\xbf"  # utf-8-sig BOM
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([header for _, header in WORKER_EXPORT_COLUMNS])
        yield buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate(0)
        for row in rows:
            writer.writerow([_cell(row, key) for key, _ in WORKER_EXPORT_COLUMNS])
            yield buf.getvalue().encode("utf-8")
            buf.seek(0)
            buf.truncate(0)

    return StreamingResponse(
        _gen(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="workers-{stamp}.csv"'},
    )


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
