"""告警系统 API 路由。"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from ...core.config import settings
from ...core.security import get_current_user, require_permission
from ...services.alert import (
    AlertEngine,
    AlertNotification,
    AlertRule,
    ConsoleChannel,
    WebhookChannel,
    get_engine,
)

router = APIRouter(prefix="/api/alerts", tags=["alerts"], dependencies=[Depends(get_current_user)])


class RuleCreate(BaseModel):
    name: str = Field(..., description="规则名称")
    task_name: str = Field(..., description="任务名称")
    metric: str = Field("state", description="监测指标")
    op: str = Field(">", description="比较操作: >, <, ==, !=, >=, <=, *")
    threshold: Any = Field(0, description="阈值")
    duration: float = Field(0.0, description="持续触发时长(秒)")
    enabled: bool = Field(True, description="是否启用")


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    task_name: Optional[str] = None
    metric: Optional[str] = None
    op: Optional[str] = None
    threshold: Optional[Any] = None
    duration: Optional[float] = None
    enabled: Optional[bool] = None


# ----------------------------------------------------------------------
# 规则管理
# ----------------------------------------------------------------------
@router.get("/rules")
async def list_rules() -> Dict[str, Any]:
    """获取所有告警规则列表。"""
    engine = get_engine()
    return {"rules": engine.get_rules(), "count": len(engine.rules)}


@router.post("/rules", status_code=201)
async def create_rule(
    payload: RuleCreate,
    _user: str = Depends(require_permission("config.manage")),
) -> Dict[str, Any]:
    """新增告警规则。"""
    engine = get_engine()
    rule = AlertRule(
        id=str(uuid.uuid4())[:8],
        name=payload.name,
        task_name=payload.task_name,
        metric=payload.metric,
        op=payload.op,
        threshold=payload.threshold,
        duration=payload.duration,
        enabled=payload.enabled,
    )
    engine.add_rule(rule)
    return rule.to_dict()


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: str,
    payload: RuleUpdate,
    _user: str = Depends(require_permission("config.manage")),
) -> Dict[str, Any]:
    """更新告警规则。"""
    engine = get_engine()
    rule = next((r for r in engine.rules if r.id == rule_id), None)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"规则 '{rule_id}' 不存在")

    if payload.name is not None:
        rule.name = payload.name
    if payload.task_name is not None:
        rule.task_name = payload.task_name
    if payload.metric is not None:
        rule.metric = payload.metric
    if payload.op is not None:
        rule.op = payload.op
    if payload.threshold is not None:
        rule.threshold = payload.threshold
    if payload.duration is not None:
        rule.duration = float(payload.duration)
    if payload.enabled is not None:
        rule.enabled = payload.enabled

    return rule.to_dict()


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: str,
    _user: str = Depends(require_permission("config.manage")),
) -> Dict[str, str]:
    """删除告警规则。"""
    engine = get_engine()
    removed = engine.remove_rule(rule_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"规则 '{rule_id}' 不存在")
    return {"message": f"规则 '{rule_id}' 已删除"}


# ----------------------------------------------------------------------
# 通道管理
# ----------------------------------------------------------------------
@router.post("/channels/webhook")
async def add_webhook_channel(
    url: str = Body(..., embed=True),
    _user: str = Depends(require_permission("config.manage")),
) -> Dict[str, Any]:
    """添加 Webhook 通道。"""
    engine = get_engine()
    # 避免重复添加相同 URL
    for ch in engine.channels:
        if isinstance(ch, WebhookChannel) and ch.url == url:
            return {"message": "该 Webhook 通道已存在", "channel": {"name": "webhook", "url": url}}
    channel = WebhookChannel(url)
    engine.channels.append(channel)
    return {"message": "Webhook 通道已添加", "channel": {"name": "webhook", "url": url}}


@router.get("/channels")
async def list_channels() -> List[Dict[str, str]]:
    """获取所有通道列表。"""
    engine = get_engine()
    result = []
    for ch in engine.channels:
        entry = {"name": ch.name}
        if isinstance(ch, WebhookChannel):
            entry["url"] = ch.url
        result.append(entry)
    return result


# ----------------------------------------------------------------------
# 测试告警
# ----------------------------------------------------------------------
@router.post("/test")
async def test_alert(
    _user: str = Depends(require_permission("config.manage")),
) -> Dict[str, Any]:
    """测试告警：向所有通道发送一条测试告警。"""
    engine = get_engine()
    test_alert = AlertNotification(
        rule_id="__test__",
        rule_name="测试告警",
        task_name="__test__",
        metric="state",
        op="*",
        threshold="test",
        current_value="test",
        triggered_at=__import__("time").time(),
        message="[测试] 这是一条测试告警",
    )
    engine.notify(test_alert)
    return {"message": "测试告警已发送到所有通道"}


# ----------------------------------------------------------------------
# 引擎状态
# ----------------------------------------------------------------------
@router.get("/status")
async def engine_status() -> Dict[str, Any]:
    """获取告警引擎状态。"""
    engine = get_engine()
    return {
        "alert_enabled": settings.alert_enabled,
        "rules_count": len(engine.rules),
        "channels_count": len(engine.channels),
        "channels": [
            {"name": ch.name, "url": getattr(ch, "url", None)}
            for ch in engine.channels
        ],
    }
