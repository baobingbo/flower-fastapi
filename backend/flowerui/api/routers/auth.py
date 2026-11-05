"""认证接口。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ...core.config import settings
from ...core.security import create_access_token, verify_basic_credentials

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


@router.get("/config")
async def auth_config():
    """前端据此决定是否展示登录页。"""
    return {
        "auth_enabled": settings.auth_enabled,
        "basic_auth": bool(settings.basic_auth),
        "oauth2": bool(settings.oauth2_key and settings.auth),
        "oauth2_redirect_uri": settings.oauth2_redirect_uri,
        "auth_provider": settings.auth_provider,
    }


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest):
    if not settings.auth_enabled:
        return LoginResponse(
            access_token=create_access_token("anonymous"), username="anonymous"
        )
    if not verify_basic_credentials(payload.username, payload.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )
    return LoginResponse(
        access_token=create_access_token(payload.username), username=payload.username
    )
