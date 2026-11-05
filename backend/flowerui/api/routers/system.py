"""系统级操作：重启后端进程等。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...core.security import get_current_user
from ...services import restart as restart_service

router = APIRouter(tags=["system"])


class RestartResponse(BaseModel):
    ok: bool = True
    message: str = "后端正在重启，请稍候刷新页面"


@router.post("/api/system/restart", response_model=RestartResponse)
async def restart_system(_user: str = Depends(get_current_user)) -> RestartResponse:
    """重启后端 API 进程，使需要重启才生效的配置（监听端口、CORS、持久化、
    认证、演示模式、事件采集等）真正落地。

    实现上由后端进程原地 re-exec 自身；Celery worker 属于独立进程，
    其相关配置需另行重启 worker。
    """
    restart_service.restart_later()
    return RestartResponse()
