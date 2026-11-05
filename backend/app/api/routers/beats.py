"""Beat 定时任务管理接口。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core.security import get_current_user, require_permission
from ...core.celery_app import get_celery_app

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/beats", tags=["beats"], dependencies=[Depends(get_current_user)])


class BeatEntry(BaseModel):
    """Beat 调度条目。"""
    name: str
    task: str
    schedule: str = ""
    args: List[Any] = []
    kwargs: Dict[str, Any] = {}
    options: Dict[str, Any] = {}


class CreateBeatPayload(BaseModel):
    """新增/更新 beat 的请求体。"""
    name: str
    task: str
    schedule: Optional[str] = None
    args: List[Any] = []
    kwargs: Dict[str, Any] = {}
    options: Dict[str, Any] = {}


def _get_beat_schedule() -> Dict[str, Any]:
    """从 Celery app 获取 beat schedule。"""
    app = get_celery_app()
    # 尝试从 app.conf 获取 schedule
    schedule = getattr(app.conf, "beat_schedule", {})
    return schedule or {}


def _format_beat_entry(name: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """格式化 beat 条目为统一结构。"""
    return {
        "name": name,
        "task": entry.get("task", ""),
        "schedule": str(entry.get("schedule", "")),
        "args": entry.get("args", []),
        "kwargs": entry.get("kwargs", {}),
        "options": entry.get("options", {}),
    }


@router.get("")
async def list_beats():
    """获取所有 beat 调度条目列表。"""
    try:
        schedule = _get_beat_schedule()
        beats = [_format_beat_entry(name, entry) for name, entry in schedule.items()]
        return {"beats": beats, "total": len(beats)}
    except Exception as exc:
        logger.error("获取 beat 列表失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"获取 beat 列表失败: {exc}")


@router.post("")
async def create_beat(
    payload: CreateBeatPayload,
    _user: str = Depends(require_permission("worker.manage")),
):
    """新增 beat 调度条目。"""
    try:
        app = get_celery_app()
        schedule = getattr(app.conf, "beat_schedule", {})
        
        # 构造 entry
        entry: Dict[str, Any] = {
            "task": payload.task,
        }
        if payload.schedule:
            entry["schedule"] = payload.schedule
        if payload.args:
            entry["args"] = payload.args
        if payload.kwargs:
            entry["kwargs"] = payload.kwargs
        if payload.options:
            entry["options"] = payload.options
        
        schedule[payload.name] = entry
        app.conf.beat_schedule = schedule
        
        return {"message": f"Beat '{payload.name}' 已创建", "name": payload.name}
    except Exception as exc:
        logger.error("创建 beat 失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"创建 beat 失败: {exc}")


@router.put("/{name}")
async def update_beat(
    name: str,
    payload: CreateBeatPayload,
    _user: str = Depends(require_permission("worker.manage")),
):
    """更新 beat 调度条目。"""
    try:
        app = get_celery_app()
        schedule = getattr(app.conf, "beat_schedule", {})
        
        if name not in schedule:
            raise HTTPException(status_code=404, detail=f"Beat '{name}' 不存在")
        
        # 构造 entry
        entry: Dict[str, Any] = {
            "task": payload.task,
        }
        if payload.schedule:
            entry["schedule"] = payload.schedule
        if payload.args:
            entry["args"] = payload.args
        if payload.kwargs:
            entry["kwargs"] = payload.kwargs
        if payload.options:
            entry["options"] = payload.options
        
        schedule[name] = entry
        app.conf.beat_schedule = schedule
        
        return {"message": f"Beat '{name}' 已更新", "name": name}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("更新 beat 失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"更新 beat 失败: {exc}")


@router.delete("/{name}")
async def delete_beat(
    name: str,
    _user: str = Depends(require_permission("worker.manage")),
):
    """删除 beat 调度条目。"""
    try:
        app = get_celery_app()
        schedule = getattr(app.conf, "beat_schedule", {})
        
        if name not in schedule:
            raise HTTPException(status_code=404, detail=f"Beat '{name}' 不存在")
        
        del schedule[name]
        app.conf.beat_schedule = schedule
        
        return {"message": f"Beat '{name}' 已删除", "name": name}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("删除 beat 失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"删除 beat 失败: {exc}")
