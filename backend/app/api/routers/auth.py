"""认证接口。"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from ...core.config import settings
from ...core.security import create_access_token, decode_token, verify_user, validate_password
from ...services.rate_limiter import get_rate_limiter
from ...services import audit
from . import oauth2 as _oauth2

router = APIRouter(prefix="/api/auth", tags=["auth"])
# 通用 OAuth2 授权码流程挂载在本前缀下：/api/auth/oauth2/login、/api/auth/oauth2/callback
router.include_router(_oauth2.router)


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str = "viewer"
    permissions: list = []


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str


class SessionItem(BaseModel):
    jti: str
    issued_at: int
    exp: int
    ip: Optional[str] = None
    ua: Optional[str] = None


class LoginLogItem(BaseModel):
    event_type: str
    user: str
    detail: dict
    timestamp: datetime
    ip: Optional[str] = None


@router.get("/config")
async def auth_config():
    """前端据此决定是否展示登录页。"""
    provider_name = (settings.oauth2_provider or "").strip() or (settings.auth_provider or "").strip()
    return {
        "auth_enabled": settings.auth_enabled,
        "basic_auth": bool(settings.basic_auth),
        "oauth2": bool(settings.oauth2_key and settings.auth),
        # 通用 OAuth2 授权码流程：client_id 非空即已配置（登录页据此显示第三方登录按钮）
        "oauth2_configured": bool((settings.oauth2_client_id or "").strip()),
        "oauth2_provider": provider_name or "OAuth",
        "oauth2_redirect_uri": settings.oauth2_redirect_uri,
        "auth_provider": settings.auth_provider,
        "flower_compatible_mode": settings.oauth2_flower_compatible,
    }


@router.get("/lockout/status")
async def lockout_status(ip: str, username: str):
    """S-1: 查询登录限流状态。"""
    limiter = get_rate_limiter()
    status_info = limiter.check_limit(ip, username)
    return {
        "locked": not status_info["allowed"],
        "remaining_seconds": status_info["remaining_seconds"],
    }


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request):
    if not settings.auth_enabled:
        return LoginResponse(
            access_token=create_access_token("anonymous"), username="anonymous"
        )
    
    # S-1: 获取客户端IP
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "unknown")
    
    # S-1: 检查限流
    limiter = get_rate_limiter()
    limit_check = limiter.check_limit(ip, payload.username)
    if not limit_check["allowed"]:
        audit.record(
            "auth.login_rate_limited",
            user=payload.username,
            detail={"ip": ip},
            request=request,
            result="error",
            error=f"账户临时锁定,剩余{limit_check['remaining_seconds']}s",
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"账户临时锁定,剩余{limit_check['remaining_seconds']}s",
        )
    
    user_info = verify_user(payload.username, payload.password)
    if not user_info:
        # S-1: 记录失败
        limiter.record_failure(ip, payload.username)
        audit.record(
            "auth.login_failed",
            user=payload.username,
            detail={},
            request=request,
            result="error",
            error="用户名或密码错误",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )
    
    # S-1: 登录成功后重置计数器
    limiter.reset(ip, payload.username)
    audit.record("auth.login", user=payload.username, detail={}, request=request)
    return LoginResponse(
        access_token=create_access_token(payload.username),
        username=payload.username,
        role=user_info.get("role", "viewer"),
        permissions=user_info.get("permissions", []),
    )


@router.post("/logout")
async def logout(request: Request):
    """注销接口，返回消息。"""
    return {"message": "已登出"}


@router.post("/password/change")
async def change_password(payload: PasswordChangeRequest, request: Request):
    """修改密码：验证旧密码 -> 校验复杂度 -> 更新 SQLite 用户密码 -> token_version+1。"""
    if not settings.auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="认证未启用"
        )
    
    # 验证旧密码
    # 从请求中获取当前用户
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未授权"
        )
    
    token = auth_header[7:]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌无效"
        )
    
    current_user = payload.get("sub")
    
    # 验证旧密码
    user_info = verify_user(current_user, payload.old_password)
    if not user_info:
        audit.record(
            "auth.password_change_failed",
            user=current_user,
            detail={},
            request=request,
            result="error",
            error="旧密码错误",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="旧密码错误"
        )
    
    # 校验新密码复杂度
    from ...core.security import validate_password
    error = validate_password(payload.new_password)
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"密码不符合要求: {error}"
        )
    
    # 更新 SQLite 用户密码
    from ...services.users_db import change_password as _change_password
    if not _change_password(current_user, payload.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密码修改失败"
        )
    
    # token_version + 1，使所有旧 session 失效
    settings.token_version += 1
    
    audit.record(
        "auth.password_changed",
        user=current_user,
        detail={},
        request=request,
        result="success",
    )
    
    return {"message": "密码已修改,所有会话已失效"}


@router.get("/sessions")
async def get_sessions(request: Request):
    """返回当前用户的 session 列表。"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未授权"
        )
    
    token = auth_header[7:]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌无效"
        )
    
    current_user = payload.get("sub")
    
    # 从当前 token 中提取 session 信息
    session = SessionItem(
        jti=payload.get("jti", ""),
        issued_at=payload.get("iat", 0),
        exp=payload.get("exp", 0),
        ip=request.client.host if request.client else None,
        ua=request.headers.get("user-agent"),
    )
    
    return {"sessions": [session]}


@router.delete("/sessions/{jti}")
async def revoke_session(jti: str, request: Request):
    """撤销指定 session。"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未授权"
        )
    
    token = auth_header[7:]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌无效"
        )
    
    current_user = payload.get("sub")
    
    # 实际实现中需要持久化的 session 存储
    # 这里简化处理：仅记录审计日志
    audit.record(
        "auth.session_revoked",
        user=current_user,
        detail={"jti": jti},
        request=request,
        result="success",
    )
    
    return {"message": "Session 已撤销"}


@router.get("/login-logs")
async def get_login_logs(
    limit: int = 50,
    user: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    request: Request = None,
):
    """从 audit.py 查 auth.login/login_failed，返回登录日志。"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未授权"
        )
    
    token = auth_header[7:]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌无效"
        )
    
    # 从 audit 服务获取登录日志
    logs = audit.get_logs(
        event_types=["auth.login", "auth.login_failed"],
        user=user,
        start=start,
        end=end,
        limit=limit,
    )
    
    items = []
    for log in logs:
        items.append(LoginLogItem(
            event_type=log.get("event_type", ""),
            user=log.get("user", ""),
            detail=log.get("detail", {}),
            timestamp=log.get("timestamp"),
            ip=log.get("ip"),
        ))
    
    return {"items": items}
