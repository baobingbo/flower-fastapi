"""认证：HTTP Basic + JWT 会话，兼容 flower 的 --basic_auth 语义。"""
from __future__ import annotations

import base64
import hmac
import time
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=False)

import logging
logger = logging.getLogger(__name__)

def verify_basic_credentials(username: str, password: str) -> bool:
    """验证用户名密码组合是否在 basic_auth 列表中。

    优先使用运行时配置（支持界面修改后动态生效），回退到启动时设置。
    如果 basic_auth 为空但开启了认证，使用默认凭据 admin:admin。
    """
    from .config import settings
    # 尝试从运行时配置获取（支持界面修改后热生效）
    try:
        import flowerui.services.runtime_config as rc
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
        logger.info(f"basic_auth from runtime: {basic_auth_list}")
        logger.info(f"basic_auth from settings: {settings.basic_auth}")
    except Exception:  # noqa: BLE001
        basic_auth_list = settings.basic_auth
    # 如果没有配置凭据但开启了认证，使用默认凭据
    if not basic_auth_list:
        basic_auth_list = ["admin:admin"]
    elif isinstance(basic_auth_list, str):
        basic_auth_list = [basic_auth_list]

    candidate = f"{username}:{password}"
    for stored in basic_auth_list:
        if hmac.compare_digest(stored, candidate):
            return True
    return False


def create_access_token(subject: str) -> str:
    now = int(time.time())
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + settings.token_expire_minutes * 60,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def _from_basic_header(header: str) -> Optional[str]:
    try:
        scheme, credentials = header.split()
        if scheme.lower() != "basic":
            return None
        decoded = base64.b64decode(credentials.encode()).decode()
        username, _, password = decoded.partition(":")
        if verify_basic_credentials(username, password):
            return username
    except Exception:
        return None
    return None


async def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    """未开启认证时直接放行，返回 anonymous。"""
    if not settings.auth_enabled:
        return "anonymous"

    if creds is not None and creds.scheme.lower() == "bearer":
        user = decode_token(creds.credentials)
        if user:
            return user

    auth_header = request.headers.get("Authorization", "")
    if auth_header:
        user = _from_basic_header(auth_header)
        if user:
            return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Access denied",
    )


CurrentUser = Depends(get_current_user)
