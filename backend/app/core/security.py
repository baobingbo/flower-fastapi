"""认证：HTTP Basic + JWT 会话，兼容 flower 的 --basic_auth 语义。"""
from __future__ import annotations

import base64
import hmac
import secrets
import time
from typing import Optional, Dict, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=False)

import logging
logger = logging.getLogger(__name__)

# S-2: 扩展的弱密码黑名单
_WEAK_PASSWORDS = frozenset({
    "password", "123456", "admin", "qwerty", "letmein",
    "welcome", "monkey", "dragon", "master", "login",
})

def verify_basic_credentials(username: str, password: str) -> bool:
    """验证用户名密码组合是否在 basic_auth 列表中。

    优先使用运行时配置（支持界面修改后动态生效），回退到启动时设置。
    B-03：若开启了认证但凭据列表为空，则拒绝所有登录（原 admin:admin 后门已移除）。
    """
    from .config import settings
    # 尝试从运行时配置获取（支持界面修改后热生效）
    try:
        import app.services.runtime_config as rc
        # basic_auth 在配置文件中存储为逗号分隔字符串（无引号），直接解析
        basic_auth_str = rc._raw_value('basic_auth')
        if isinstance(basic_auth_str, str) and basic_auth_str:
            # 检查是否是 JSON 数组格式
            if basic_auth_str.startswith('['):
                import json
                basic_auth_list = json.loads(basic_auth_str)
            else:
                # 逗号分隔格式：admin:admin,user1:pass1
                basic_auth_list = [x.strip() for x in basic_auth_str.split(',') if x.strip()]
        elif isinstance(basic_auth_str, list):
            basic_auth_list = basic_auth_str
        else:
            basic_auth_list = settings.basic_auth
        # B-05：不再把明文凭据写入日志，仅以 debug 级别记录条目数
        _n = (
            len(basic_auth_list)
            if isinstance(basic_auth_list, (list, tuple))
            else (1 if basic_auth_list else 0)
        )
        logger.debug(
            "basic_auth 条目数: runtime=%d settings=%d", _n, len(settings.basic_auth)
        )
    except Exception:  # noqa: BLE001
        basic_auth_list = settings.basic_auth
    if isinstance(basic_auth_list, str):
        basic_auth_list = [basic_auth_list]
    # B-03：开启认证但凭据为空 → 拒绝所有登录（移除原 admin:admin 后门）
    if not basic_auth_list:
        logger.error(
            "已开启认证但 basic_auth 凭据列表为空，拒绝用户 '%s' 的登录尝试",
            username,
        )
        return False

    candidate = f"{username}:{password}"
    result = False
    # S-4: 时序侧信道防御 — 遍历全部凭据，无 early-exit
    for stored in basic_auth_list:
        matched = hmac.compare_digest(stored, candidate)
        result = result or matched
    return result


def verify_user(username: str, password: str) -> dict:
    """验证用户密码，返回用户信息（包含角色和权限）。

    使用 SQLite 用户存储进行验证。
    """
    from ..services.users_db import verify_user as _verify_user
    return _verify_user(username, password)

def create_access_token(subject: str) -> str:
    """创建 JWT token，包含 jti 和 ver claim。"""
    now = int(time.time())
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + settings.token_expire_minutes * 60,
        "jti": secrets.token_urlsafe(16),
        "ver": settings.token_version,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """解码 JWT token，返回完整 payload，并校验版本。"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        # 校验 token 版本
        if payload.get("ver", 0) < settings.token_version:
            return None
        return payload
    except jwt.PyJWTError:
        return None



def validate_password(password: str) -> Optional[str]:
    """校验密码复杂度，返回错误信息（无错误返回 None）。"""
    from .config import settings
    
    # 检查最小长度
    if len(password) < settings.password_min_length:
        return f"密码长度至少 {settings.password_min_length} 位"
    
    # 检查大写
    if settings.password_require_upper and not any(c.isupper() for c in password):
        return "密码需包含大写字母"
    
    # 检查数字
    if settings.password_require_digit and not any(c.isdigit() for c in password):
        return "密码需包含数字"
    
    # 检查特殊字符
    if settings.password_require_special and not any(not c.isalnum() for c in password):
        return "密码需包含特殊字符"
    
    # S-2: 弱密码黑名单扩展
    if password.lower() in _WEAK_PASSWORDS:
        return "密码过于简单"
    
    return None


def require_permission(permission: str):
    """权限检查依赖工厂：无 token 或未登录 → 401/403，缺权限 → 403。

    用法：``Depends(require_permission("config.manage"))``。
    """

    async def _check(current_user: str = Depends(get_current_user)):
        if not settings.auth_enabled:
            return current_user
        if current_user == "anonymous":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要认证")
        if not has_permission(current_user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"缺少权限: {permission}",
            )
        return current_user

    return _check


def has_permission(username: str, permission_name: str) -> bool:
    """检查用户是否拥有指定权限（委托 SQLite 用户库）。"""
    from ..services.users_db import has_permission as _has_permission
    try:
        return _has_permission(username, permission_name)
    except Exception:  # noqa: BLE001
        logger.exception("has_permission 检查失败: %s / %s", username, permission_name)
        return False


async def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    """未开启认证时直接放行，返回 anonymous。

    仅支持 Bearer JWT 认证。
    """
    if not settings.auth_enabled:
        return "anonymous"

    if creds is not None and creds.scheme.lower() == "bearer":
        payload = decode_token(creds.credentials)
        if payload:
            return payload.get("sub")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Access denied",
    )


CurrentUser = Depends(get_current_user)