"""远程控制接口：worker 生命周期、进程池、队列消费、任务限流与撤销。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.security import get_current_user
from ...services.manager import ControlError, manager

router = APIRouter(prefix="/api", tags=["control"], dependencies=[Depends(get_current_user)])


def _wrap(fn):
    async def runner(*args, **kwargs):
        try:
            return {"message": await fn(*args, **kwargs)}
        except ControlError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc

    return runner


# ----------------------------------------------------------------------
# Worker 控制
# ----------------------------------------------------------------------
@router.post("/worker/shutdown/{workername:path}")
async def worker_shutdown(workername: str):
    return await _wrap(manager.worker_shutdown)(workername)


@router.post("/worker/pool/restart/{workername:path}")
async def worker_pool_restart(workername: str):
    return await _wrap(manager.worker_pool_restart)(workername)


@router.post("/worker/pool/grow/{workername:path}")
async def worker_pool_grow(workername: str, n: int = Query(1, ge=1)):
    return await _wrap(manager.worker_pool_grow)(workername, n)


@router.post("/worker/pool/shrink/{workername:path}")
async def worker_pool_shrink(workername: str, n: int = Query(1, ge=1)):
    return await _wrap(manager.worker_pool_shrink)(workername, n)


@router.post("/worker/pool/autoscale/{workername:path}")
async def worker_pool_autoscale(
    workername: str,
    min: int = Query(..., ge=1, alias="min"),
    max: int = Query(..., ge=1, alias="max"),
):
    return await _wrap(manager.worker_pool_autoscale)(workername, min, max)


@router.post("/worker/queue/add-consumer/{workername:path}")
async def worker_queue_add_consumer(workername: str, queue: str = Query(...)):
    return await _wrap(manager.worker_add_consumer)(workername, queue)


@router.post("/worker/queue/cancel-consumer/{workername:path}")
async def worker_queue_cancel_consumer(workername: str, queue: str = Query(...)):
    return await _wrap(manager.worker_cancel_consumer)(workername, queue)


# ----------------------------------------------------------------------
# 任务控制
# ----------------------------------------------------------------------
@router.post("/task/revoke/{taskid}")
async def task_revoke(
    taskid: str,
    terminate: bool = Query(False),
    signal: str = Query("SIGTERM"),
):
    return await _wrap(manager.task_revoke)(taskid, terminate, signal)


@router.post("/task/rate-limit/{taskname:path}")
async def task_rate_limit(
    taskname: str,
    workername: str = Query(...),
    ratelimit: str = Query(...),
):
    return await _wrap(manager.task_rate_limit)(taskname, workername, ratelimit)


@router.post("/task/timeout/{taskname:path}")
async def task_timeout(
    taskname: str,
    workername: str = Query(...),
    soft: Optional[float] = Query(None),
    hard: Optional[float] = Query(None),
):
    if soft is None and hard is None:
        raise HTTPException(400, "soft 与 hard 至少提供一个")
    return await _wrap(manager.task_time_limit)(taskname, workername, soft, hard)
