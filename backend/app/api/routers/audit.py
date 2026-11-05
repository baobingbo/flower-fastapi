"""审计日志查询接口。

- ``GET /api/audit``  分页查询操作审计记录（最新在前）

参数：
- ``limit``  每页条数（1~500，默认 100）
- ``offset`` 跳过条数（默认 0）
- ``user``   精确匹配用户
- ``action`` 精确匹配动作（config.update / config.reset / config.materialize /
             config.backup_restore / config.backup_delete / system.restart /
             auth.login / auth.login_failed / theme.create / theme.delete）
- ``start`` / ``end``  时间范围，ISO 8601 或 epoch 秒
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from ...core.security import get_current_user
from ...services import audit

router = APIRouter(tags=["audit"])


@router.get("/api/audit/actions")
async def audit_actions(_user: str = Depends(get_current_user)):
    """已出现过的 action 列表，供前端筛选下拉。"""
    return {"actions": audit.actions()}


@router.get("/api/audit")
async def audit_list(
    _user: str = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: Optional[str] = None,
    action: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """审计记录分页查询（倒序，最新在前）。"""
    return audit.query(
        limit=limit,
        offset=offset,
        user=user,
        action=action,
        start=start,
        end=end,
    )
