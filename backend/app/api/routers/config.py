"""配置查看与修改接口。

- GET  /api/config             分组返回全部配置项（敏感值脱敏）
- PUT  /api/config             批量修改可热更新项，落盘后立即生效（留审计）
- POST /api/config/reset       恢复到进程启动时的取值（留审计）
- GET  /api/config/ui          免鉴权，供前端启动时读取界面默认值
- GET  /api/config/backups     列出配置备份（新→旧，含差异键）
- POST /api/config/backups/restore  回滚到指定备份（留审计）
- DELETE /api/config/backups   删除指定备份（留审计）
- POST /api/config/materialize 生成完整配置模板（改写前自动备份）
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ...core.security import get_current_user, require_permission
from ...services import audit, runtime_config

router = APIRouter(prefix="/api/config", tags=["config"])


class UpdateRequest(BaseModel):
    changes: Dict[str, Any] = Field(default_factory=dict)


class ResetRequest(BaseModel):
    keys: Optional[List[str]] = None


class BackupNameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


@router.get("/ui")
async def get_ui_defaults():
    """界面默认值。刻意不鉴权：登录页本身也需要按服务端默认主题渲染。"""
    return runtime_config.ui_defaults()


@router.get("")
async def get_config(_user: str = Depends(get_current_user)):
    return runtime_config.describe()


@router.put("")
async def update_config(
    payload: UpdateRequest,
    request: Request,
    _user: str = Depends(require_permission("config.manage")),
):
    try:
        applied = runtime_config.update(payload.changes)
    except runtime_config.ConfigError as exc:
        audit.record(
            "config.update",
            user=_user,
            detail={"changes": payload.changes, "applied": []},
            request=request,
            result="error",
            error=exc,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit.record(
        "config.update",
        user=_user,
        detail={"changes": payload.changes, "applied": sorted(applied.keys())},
        request=request,
    )
    return {
        "ok": True,
        "applied": applied,
        "message": f"已更新 {len(applied)} 项配置",
        "config": runtime_config.describe(),
    }


@router.post("/reset")
async def reset_config(
    payload: ResetRequest,
    request: Request,
    _user: str = Depends(require_permission("config.manage")),
):
    restored = runtime_config.reset(payload.keys)
    audit.record(
        "config.reset",
        user=_user,
        detail={"restored": restored},
        request=request,
    )
    return {
        "ok": True,
        "restored": restored,
        "message": f"已恢复 {len(restored)} 项配置的启动值" if restored else "当前没有被修改过的配置项",
        "config": runtime_config.describe(),
    }


@router.post("/materialize")
async def materialize_config(
    request: Request,
    _user: str = Depends(require_permission("config.manage")),
):
    """生成一份完整带中文注释的默认配置模板（保留手工键；改写前自动备份）。"""
    result = runtime_config.materialize()
    audit.record(
        "config.materialize",
        user=_user,
        detail={"runtime_file": str(runtime_config.RUNTIME_FILE)},
        request=request,
    )
    return result


@router.get("/backups")
async def list_backups(_user: str = Depends(get_current_user)):
    """配置备份列表（新→旧）。diff_keys 为该备份与当前文件的差异键。"""
    return {
        "backups": runtime_config.list_backups(),
        "runtime_file": str(runtime_config.RUNTIME_FILE),
        "keep": runtime_config.BACKUP_KEEP,
    }


@router.post("/backups/restore")
async def restore_backup(
    payload: BackupNameRequest,
    request: Request,
    _user: str = Depends(require_permission("config.manage")),
):
    """回滚运行时配置到指定备份（回滚本身会先给当前文件建新备份）。"""
    try:
        result = runtime_config.restore_backup(payload.name)
    except runtime_config.ConfigError as exc:
        audit.record(
            "config.backup_restore",
            user=_user,
            detail={"name": payload.name},
            request=request,
            result="error",
            error=exc,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit.record(
        "config.backup_restore",
        user=_user,
        detail={"name": payload.name, "applied": result["applied"]},
        request=request,
    )
    return {
        "ok": True,
        **result,
        "message": f"已回滚到备份 {payload.name}",
        "config": runtime_config.describe(),
    }


@router.delete("/backups")
async def delete_backup(
    payload: BackupNameRequest,
    request: Request,
    _user: str = Depends(require_permission("config.manage")),
):
    """删除指定备份。"""
    try:
        runtime_config.delete_backup(payload.name)
    except runtime_config.ConfigError as exc:
        audit.record(
            "config.backup_delete",
            user=_user,
            detail={"name": payload.name},
            request=request,
            result="error",
            error=exc,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit.record(
        "config.backup_delete",
        user=_user,
        detail={"name": payload.name},
        request=request,
    )
    return {"ok": True, "deleted": payload.name}
