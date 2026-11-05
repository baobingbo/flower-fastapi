"""WebSocket 实时推送：事件流、Dashboard 概览、趋势时间线。

前端连接后可发送 {"action": "subscribe", "types": ["event", "summary", "timeline"]}
调整订阅内容；默认全部订阅。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional, Set

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ...core.config import settings
from ...core.security import decode_token, verify_basic_credentials
from ...services.hub import hub
from ...services.manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

DEFAULT_TYPES = {"event", "summary", "timeline", "themes_updated"}


def _authorized(token: Optional[str]) -> bool:
    if not settings.auth_enabled:
        return True
    if not token:
        return False
    return decode_token(token) is not None


@router.websocket("/ws/events")
async def ws_events(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    worker: Optional[str] = Query(None),
    task: Optional[str] = Query(None),
) -> None:
    if not _authorized(token):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    queue = hub.subscribe()
    types: Set[str] = set(DEFAULT_TYPES)

    # 连接后先推一份当前快照，避免前端首屏空白
    await websocket.send_json(
        {
            "type": "snapshot",
            "summary": manager.dashboard_summary(),
            "workers": manager.worker_rows(),
            "timeline": manager.state.get_timeline(120),
        }
    )

    async def reader() -> None:
        """处理客户端下行指令（订阅调整 / ping）。"""
        nonlocal types
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            action = msg.get("action")
            ping = action == "ping" or msg.get("type") == "ping"
            if action == "subscribe":
                types = set(msg.get("types") or DEFAULT_TYPES)
            elif ping:
                await websocket.send_json({"type": "pong"})

    reader_task = asyncio.create_task(reader())
    try:
        while True:
            message = await queue.get()
            mtype = message.get("type")
            if mtype not in types:
                continue
            if mtype == "event":
                evt = message.get("event") or {}
                if worker and evt.get("hostname") != worker:
                    continue
                if task and evt.get("name") != task:
                    continue
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # 客户端异常断开
        logger.debug("WebSocket 关闭: %s", exc)
    finally:
        reader_task.cancel()
        hub.unsubscribe(queue)


@router.websocket("/ws/task/{taskid}")
async def ws_task(websocket: WebSocket, taskid: str, token: Optional[str] = Query(None)) -> None:
    """单个任务的状态跟踪流。"""
    if not _authorized(token):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    queue = hub.subscribe()
    try:
        while True:
            message = await queue.get()
            if message.get("type") != "event":
                continue
            evt = message.get("event") or {}
            if evt.get("uuid") != taskid:
                continue
            task = manager.state.tasks.get(taskid)
            await websocket.send_json(
                {
                    "type": "task",
                    "event": evt.get("type"),
                    "state": getattr(task, "state", None),
                    "runtime": getattr(task, "runtime", None),
                }
            )
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        hub.unsubscribe(queue)
