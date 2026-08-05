"""Broker 队列视图（对应 flower 的 /broker 页面）。"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from ...core.celery_app import broker_uri, transport_driver
from ...core.security import get_current_user
from ...services.manager import ControlError, manager

router = APIRouter(prefix="/api", tags=["broker"], dependencies=[Depends(get_current_user)])


@router.get("/broker")
async def broker_overview() -> Dict[str, Any]:
    try:
        queues = await manager.broker_queues()
    except ControlError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc

    return {
        "broker_url": broker_uri(),
        "transport": transport_driver(),
        "mock_mode": manager.mock_mode,
        "queues": queues,
        "totals": {
            "queues": len(queues),
            "messages": sum(q.get("messages") or 0 for q in queues),
            "consumers": sum(q.get("consumers") or 0 for q in queues),
            "unacked": sum(q.get("messages_unacknowledged") or 0 for q in queues),
        },
    }
