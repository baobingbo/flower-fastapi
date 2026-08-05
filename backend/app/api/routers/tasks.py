"""任务查询与下发接口，全面对齐 flower 的 /api/task* 系列。"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ...core.config import settings
from ...core.security import get_current_user
from ...services.manager import ControlError, manager
from ...services.task_filter import (
    count_tasks,
    get_task_by_id,
    iter_tasks,
    task_to_dict,
)

router = APIRouter(prefix="/api", tags=["tasks"], dependencies=[Depends(get_current_user)])

ALL = "All"


def _none_if_all(value: Optional[str]) -> Optional[str]:
    return None if not value or value == ALL else value


class ApplyPayload(BaseModel):
    """POST body，字段语义与 flower 一致（args / kwargs / 其余作为 apply_async 选项）。"""

    args: List[Any] = Field(default_factory=list)
    kwargs: Dict[str, Any] = Field(default_factory=dict)
    options: Dict[str, Any] = Field(default_factory=dict)

    # 便捷字段（也可直接放进 options）
    queue: Optional[str] = None
    countdown: Optional[float] = None
    eta: Optional[str] = None
    expires: Optional[Any] = None
    routing_key: Optional[str] = None
    priority: Optional[int] = None

    def apply_options(self) -> Dict[str, Any]:
        opts = dict(self.options or {})
        for key in ("queue", "countdown", "eta", "expires", "routing_key", "priority"):
            value = getattr(self, key)
            if value is not None:
                opts.setdefault(key, value)
        return opts


# ----------------------------------------------------------------------
# 查询
# ----------------------------------------------------------------------
@router.get("/tasks")
async def list_tasks(
    limit: Optional[int] = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    workername: Optional[str] = Query(None),
    taskname: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    received_start: Optional[str] = Query(None, description="%Y-%m-%d %H:%M"),
    received_end: Optional[str] = Query(None),
    started_start: Optional[str] = Query(None),
    started_end: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    root_id: Optional[str] = Query(None),
    parent_id: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """对应 flower GET /api/tasks，返回 {task_id: task} 映射。"""
    result = []
    for task_id, task in iter_tasks(
        manager.state,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        type=_none_if_all(taskname),
        worker=_none_if_all(workername),
        task_state=_none_if_all(state),
        received_start=received_start,
        received_end=received_end,
        started_start=started_start,
        started_end=started_end,
        search=search,
        root_id=root_id,
        parent_id=parent_id,
    ):
        result.append((task_id, task_to_dict(task)))
    return OrderedDict(result)


@router.get("/tasks/table")
async def tasks_table(
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    workername: Optional[str] = Query(None),
    taskname: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    received_start: Optional[str] = Query(None),
    received_end: Optional[str] = Query(None),
    started_start: Optional[str] = Query(None),
    started_end: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("-received"),
    search: Optional[str] = Query(None),
    root_id: Optional[str] = Query(None),
    parent_id: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """前端表格分页接口：返回 data + total（对应 flower /tasks/datatable）。"""
    criteria = dict(
        type=_none_if_all(taskname),
        worker=_none_if_all(workername),
        task_state=_none_if_all(state),
        received_start=received_start,
        received_end=received_end,
        started_start=started_start,
        started_end=started_end,
        search=search,
        root_id=root_id,
        parent_id=parent_id,
    )
    total = count_tasks(manager.state, sort_by=None, **criteria)
    rows = [
        task_to_dict(task)
        for _, task in iter_tasks(
            manager.state, limit=limit, offset=offset, sort_by=sort_by, **criteria
        )
    ]
    return {
        "data": rows,
        "total": total,
        "offset": offset,
        "limit": limit,
        "columns": settings.task_columns_list,
    }


@router.get("/task/types")
async def task_types() -> Dict[str, List[str]]:
    """已出现过的任务类型（对齐 flower /api/task/types）。"""
    return {"task-types": manager.state.task_types()}


@router.get("/task/registered")
async def registered_tasks(refresh: bool = Query(False)) -> Dict[str, Any]:
    """worker 注册的可下发任务列表，附带每个任务的默认队列与可选队列。

    前端"下发任务"表单据此实现：选任务 → 自动预填其默认队列；队列下拉展示可选队列。

    真实模式下，若首屏检测到列表为空（inspector 尚未完成首次探测），自动触发一次
    inspect 再返回，避免前端下拉初始为空、需要手动刷新。
    """
    if refresh or (not manager.mock_mode and not manager.registered_tasks()):
        await manager.refresh_workers()
    return {
        "tasks": manager.registered_tasks(),
        "tasks_detail": manager.registered_tasks_detail(),
        "queues": manager.available_queues(),
    }


@router.get("/task/info/{taskid}")
async def task_info(taskid: str) -> Dict[str, Any]:
    task = get_task_by_id(manager.state, taskid)
    if task is None:
        raise HTTPException(404, f"Unknown task '{taskid}'")
    data = task_to_dict(task)
    data["task-id"] = taskid
    # 附带子任务，便于前端展示调用链
    data["children_tasks"] = [
        task_to_dict(t)
        for _, t in iter_tasks(manager.state, parent_id=taskid)
    ]
    return data


@router.get("/queues/length")
async def queues_length() -> Dict[str, Any]:
    try:
        return {"active_queues": await manager.broker_queues()}
    except ControlError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


# ----------------------------------------------------------------------
# 下发 / 结果 / 中止
# ----------------------------------------------------------------------
@router.post("/task/apply/{taskname:path}")
async def task_apply(
    taskname: str,
    payload: ApplyPayload = Body(default_factory=ApplyPayload),
    timeout: Optional[float] = Query(None, description="等待结果的秒数"),
) -> Dict[str, Any]:
    """执行任务并等待结果。"""
    try:
        return await manager.apply_task(
            taskname,
            payload.args,
            payload.kwargs,
            payload.apply_options(),
            wait=True,
            timeout=timeout,
        )
    except ControlError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.post("/task/async-apply/{taskname:path}")
async def task_async_apply(
    taskname: str,
    payload: ApplyPayload = Body(default_factory=ApplyPayload),
) -> Dict[str, Any]:
    """异步执行任务，立即返回 task-id。"""
    try:
        return await manager.apply_task(
            taskname, payload.args, payload.kwargs, payload.apply_options()
        )
    except ControlError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.post("/task/send-task/{taskname:path}")
async def task_send(
    taskname: str,
    payload: ApplyPayload = Body(default_factory=ApplyPayload),
) -> Dict[str, Any]:
    """按名称下发任务，不要求本地注册任务源。"""
    try:
        return await manager.apply_task(
            taskname,
            payload.args,
            payload.kwargs,
            payload.apply_options(),
            require_registered=False,
        )
    except ControlError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.get("/task/result/{taskid}")
async def task_result(
    taskid: str, timeout: Optional[float] = Query(None)
) -> Dict[str, Any]:
    try:
        return await manager.task_result(taskid, timeout)
    except ControlError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.post("/task/abort/{taskid}")
async def task_abort(taskid: str) -> Dict[str, str]:
    try:
        return {"message": await manager.task_abort(taskid)}
    except ControlError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
