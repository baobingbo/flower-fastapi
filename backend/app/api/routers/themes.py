"""主题管理接口。

- ``GET  /api/themes``            列出目录中全部用户主题（免鉴权，登录页也用得到）
- ``GET  /api/themes/files/<f>``  直接返回某个 .css 文件（base.css / 模板 / 用户主题）
- ``POST /api/themes``            上传一个主题 CSS（需鉴权）
- ``DELETE /api/themes/<id>``     删除一个用户主题（需鉴权）
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import PlainTextResponse

from ...core.security import get_current_user
from ...services import theme_manager

router = APIRouter(prefix="/api/themes", tags=["themes"])

logger = logging.getLogger(__name__)


@router.get("")
async def list_themes(_user: Optional[str] = Depends(get_current_user)):
    """用户主题列表。即便未登录（auth 未开启）也能拿到，方便主题切换器渲染。"""
    return {"themes": theme_manager.scan(), "dir": str(theme_manager.THEMES_DIR)}


@router.get("/files/{filename}")
async def get_theme_file(filename: str):
    """返回主题目录下的某个 css 文件（base.css / _template.css / 用户主题）。"""
    content = theme_manager.get_css(filename)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="主题文件不存在")
    return PlainTextResponse(content, media_type="text/css; charset=utf-8")


@router.post("")
async def upload_theme(
    file: UploadFile = File(...),
    _user: str = Depends(get_current_user),
):
    try:
        content = (await file.read()).decode("utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"文件读取失败：{exc}"
        )
    try:
        meta = theme_manager.upload(file.filename or "theme.css", content)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "ok": True,
        "message": f"主题「{meta['name']}」已添加，可在主题切换器中选择",
        "theme": meta,
        "themes": theme_manager.scan(),
    }


@router.delete("/{theme_id}")
async def delete_theme(theme_id: str, _user: str = Depends(get_current_user)):
    try:
        theme_manager.delete(theme_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {
        "ok": True,
        "message": f"主题「{theme_id}」已删除",
        "themes": theme_manager.scan(),
    }
