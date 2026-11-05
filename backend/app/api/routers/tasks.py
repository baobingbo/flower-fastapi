"""任务查询与下发接口，全面对齐 flower 的 /api/task* 系列。"""
from __future__ import annotations

import ast
import csv
import datetime
import io
import json
from collections import OrderedDict
from typing import Any, Dict, Iterator, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from ...core.config import settings
from ...core.security import get_current_user, require_permission
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


# ----------------------------------------------------------------------
# 导出（F-05）
# ----------------------------------------------------------------------
# CSV 固定列（与前端表格主要列对齐，表头用中文便于 Excel 阅读）
TASK_EXPORT_COLUMNS = [
    ("uuid", "任务 ID"),
    ("name", "任务名"),
    ("state", "状态"),
    ("args", "位置参数"),
    ("kwargs", "关键字参数"),
    ("worker", "Worker"),
    ("received", "接收时间"),
    ("started", "开始时间"),
    ("runtime", "耗时(秒)"),
    ("retries", "重试次数"),
    ("exchange", "Exchange"),
    ("routing_key", "Routing Key"),
    ("root_id", "根任务"),
    ("parent_id", "父任务"),
    ("result", "结果"),
    ("exception", "异常"),
]

# 需要格式化为本地时间的 epoch 字段
_TS_FIELDS = {"received", "started"}


@router.get("/tasks/export")
async def export_tasks(
    format: str = Query("csv", pattern="^(csv|json)$"),
    limit: int = Query(10000, ge=1, le=10000, alias="max", description="导出行数上限（防滥用）"),
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
):
    """按当前筛选条件导出任务列表，csv（utf-8-sig，Excel 中文不乱码）或 json 数组。"""
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
    rows = [
        task_to_dict(task)
        for _, task in iter_tasks(
            manager.state, limit=limit, offset=0, sort_by=sort_by, **criteria
        )
    ]
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if format == "json":
        body = json.dumps(rows, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="tasks-{stamp}.json"'},
        )

    def _cell(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            return repr(value)
        return str(value)

    def _gen() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([header for _, header in TASK_EXPORT_COLUMNS])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        for row in rows:
            writer.writerow([
                _fmt_ts(row.get(key)) if key in _TS_FIELDS else _cell(row.get(key))
                for key, _ in TASK_EXPORT_COLUMNS
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    # utf-8-sig：首个 BOM 由流头部补上，保证 Excel 识别 UTF-8 中文
    def _gen_with_bom() -> Iterator[bytes]:
        yield b"\xef\xbb\xbf"
        for chunk in _gen():
            yield chunk.encode("utf-8")

    return StreamingResponse(
        _gen_with_bom(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="tasks-{stamp}.csv"'},
    )


def _fmt_ts(value: Any) -> str:
    if not value:
        return ""
    try:
        return datetime.datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(value)


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
    # B-06：默认 30s，限制 1~300s，防止无限等待耗尽共享线程池（DoS）
    timeout: float = Query(30.0, ge=1, le=300, description="等待结果的秒数（1~300）"),
    _: str = Depends(require_permission("task.apply")),
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
    _: str = Depends(require_permission("task.apply")),
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
    _: str = Depends(require_permission("task.apply")),
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


# ----------------------------------------------------------------------
# 一键重试（F-04）
# ----------------------------------------------------------------------
def _parse_task_args(task) -> tuple:
    """取任务的原始 args/kwargs。

    真实模式下事件里的 args/kwargs 是 list/dict；mock 模式（以及部分历史
    数据）里存的是 Python 字面量字符串，这里解析回真实结构再重新投递。
    """
    args = getattr(task, "args", None)
    kwargs = getattr(task, "kwargs", None)
    if isinstance(args, str):
        try:
            args = ast.literal_eval(args)
        except (ValueError, SyntaxError):
            args = [args]
    if isinstance(kwargs, str):
        try:
            kwargs = ast.literal_eval(kwargs)
        except (ValueError, SyntaxError):
            kwargs = {}
    if not isinstance(args, (list, tuple)):
        args = [args] if args is not None else []
    if not isinstance(kwargs, dict):
        kwargs = {}
    return list(args), dict(kwargs)


def _task_route_options(task) -> Dict[str, Any]:
    """恢复原任务的路由信息，供重新投递复用（不携带 eta/countdown 等调度字段）。"""
    options: Dict[str, Any] = {}
    for key in ("routing_key", "exchange"):
        value = getattr(task, key, None)
        if value:
            options[key] = value
    return options


@router.post("/task/retry/{taskid}")
async def task_retry(
    taskid: str,
    wait: bool = Query(False, description="是否等待结果（与 /task/apply 一致）"),
    timeout: float = Query(30.0, ge=1, le=300, description="等待结果的秒数（1~300）"),
    _: str = Depends(require_permission("task.apply")),
) -> Dict[str, Any]:
    """一键重试：复用原任务的 name/args/kwargs/路由重新投递，返回新 task-id。"""
    task = get_task_by_id(manager.state, taskid)
    if task is None:
        raise HTTPException(
            404,
            f"任务 '{taskid}' 已不在内存中（超出保留上限），请手动下发",
        )
    args, kwargs = _parse_task_args(task)
    options = _task_route_options(task)
    try:
        return await manager.apply_task(
            task.name,
            args,
            kwargs,
            options,
            wait=wait,
            timeout=timeout,
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
async def task_abort(
    taskid: str,
    _: str = Depends(require_permission("task.apply")),
) -> Dict[str, str]:
    try:
        return {"message": await manager.task_abort(taskid)}
    except ControlError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


# ----------------------------------------------------------------------
# F-02a: 历史数据归档
# ----------------------------------------------------------------------
@router.get("/tasks/history")
async def list_task_history(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    state: Optional[str] = Query(None),
    worker: Optional[str] = Query(None),
    task_name: Optional[str] = Query(None),
    start_time: Optional[float] = Query(None, description="Unix timestamp"),
    end_time: Optional[float] = Query(None, description="Unix timestamp"),
) -> Dict[str, Any]:
    """查询历史任务列表。"""
    if not manager.history_store:
        return {"tasks": [], "total": 0}
    
    tasks = manager.history_store.get_tasks(
        limit=limit,
        offset=offset,
        state=state,
        worker=worker,
        task_name=task_name,
        start_time=start_time,
        end_time=end_time,
    )
    return {"tasks": tasks, "total": len(tasks)}


@router.get("/tasks/timeline")
async def get_task_timeline(
    task_name: Optional[str] = Query(None),
    start: Optional[float] = Query(None, description="Unix timestamp"),
    end: Optional[float] = Query(None, description="Unix timestamp"),
    interval_seconds: int = Query(60, ge=1, le=3600),
) -> List[Dict[str, Any]]:
    """查询任务时间线数据。"""
    if not manager.history_store:
        return []
    
    return manager.history_store.get_timeline(
        task_name=task_name,
        start=start,
        end=end,
        interval_seconds=interval_seconds,
    )


@router.post("/tasks/history/cleanup")
async def cleanup_task_history(
    retention_days: int = Query(None, description="保留天数，默认使用配置"),
    _: str = Depends(require_permission("config.manage")),
) -> Dict[str, Any]:
    """清理过期历史数据。"""
    if not manager.history_store:
        return {"deleted": 0, "message": "历史归档未启用"}
    
    days = retention_days if retention_days is not None else settings.history_retention_days
    deleted = manager.history_store.cleanup(retention_days=days)
    return {"deleted": deleted, "retention_days": days}
