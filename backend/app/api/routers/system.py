"""系统级操作：重启后端进程、重启状态查询。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ...core.security import get_current_user, require_permission
from ...services import audit, restart as restart_service

router = APIRouter(tags=["system"])


class RestartResponse(BaseModel):
    ok: bool = True
    message: str = "后端正在重启，请稍候刷新页面"
    status: dict = {}


@router.post("/api/system/restart", response_model=RestartResponse)
async def restart_system(
    request: Request,
    _user: str = Depends(require_permission("config.manage")),
) -> RestartResponse:
    """重启后端 API 进程，使需要重启才生效的配置（监听端口、CORS、持久化、
    认证、演示模式、事件采集等）真正落地。

    实现上由后端执行 manage.sh restart 先停后起；触发前会写入重启状态
    文件，可通过 GET /api/system/restart/status 查询重启结果
    （pending → success / failed / timeout）。Celery worker 属于独立进程，
    其相关配置需另行重启 worker。
    """
    state = restart_service.restart_later()
    audit.record(
        "system.restart",
        user=_user,
        detail={
            "pid": state.get("pid"),
            "script": state.get("script"),
            "interpreter": state.get("interpreter"),
        },
        request=request,
    )
    return RestartResponse(status={k: state.get(k) for k in ("status", "requested_at", "pid")})


@router.get("/api/system/restart/status")
async def restart_status():
    """重启状态机查询（重启健康检查用，刻意不鉴权）。

    重启后旧令牌可能因 secret_key 重新生成而失效，前端重载页面时需要
    免鉴权地确认服务是否真正重启成功。返回字段：

    - status: idle | in_progress | success | failed | timeout
    - requested_at / completed_at / failed_at: epoch 秒
    - pid: 发起重启的进程；current_pid / started_at: 当前进程（
      started_at > requested_at 即已换新进程）
    - script / interpreter / error / hint
    """
    return restart_service.status()
