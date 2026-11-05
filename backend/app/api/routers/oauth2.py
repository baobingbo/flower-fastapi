"""通用 OAuth2 授权码登录（GitHub / GitLab / OIDC 等任意兼容提供方）。

流程（标准 authorization code）：
1. 前端调 GET /api/auth/oauth2/login：client_id 未配置时 400；否则生成随机
   state（内存保存 5 分钟），返回 {redirect_url}（authorize_url 携带
   response_type=code / client_id / redirect_uri / state / scope），前端整页跳转。
2. 用户在提供方页面授权后，提供方 302 回 /api/auth/oauth2/callback?code&state。
3. callback 校验 state → 向 token_url 换 access_token（form 携带
   code/redirect_uri/client_id/client_secret）→ 带 Bearer 请求 userinfo
   （未配置 userinfo_url 时退回令牌响应本身）→ 按 username_claim 取用户名
   （缺失依次尝试 login/preferred_username/email/name）→ 白名单校验
   （auth 邮箱/用户名正则，非空且未命中则拒绝）→ 用与 basic auth 完全相同的
   create_access_token JWT 机制签发会话（get_current_user 的 Bearer 分支直接
   认可，前端与账号密码登录一样存 localStorage 并以 Bearer 发送）。
   成功后 302 回前端根路径 ?token=...&user=...，失败统一 302 回登录页
   ?oauth_error=xxx。

本路由由 auth.py 的 /api/auth 路由 include，故无需改动 main.py。
"""
from __future__ import annotations

import logging
import re
import secrets
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

from ...core.config import settings
from ...core.security import create_access_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

# state 防 CSRF：内存保存 {state: 生成时间戳}，5 分钟过期
_STATE_TTL = 300
_oauth_states: Dict[str, float] = {}

# 用户名字段缺失时的兜底尝试顺序
_CLAIM_FALLBACKS = ("login", "preferred_username", "email", "name")


def _purge_states() -> None:
    now = time.time()
    for s in [k for k, v in _oauth_states.items() if now - v > _STATE_TTL]:
        _oauth_states.pop(s, None)


def _origin(request: Request) -> str:
    """前端根地址（生产为后端同源；开发为 Vite 代理来源），尊重代理头。"""
    host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host") or "127.0.0.1"
    scheme = request.headers.get("X-Forwarded-Proto") or request.url.scheme
    return f"{scheme}://{host}"


def _callback_url(request: Request) -> str:
    """redirect_uri：优先配置值（需与提供方注册一致），留空自动推导。"""
    explicit = (settings.oauth2_redirect_uri or "").strip()
    if explicit:
        return explicit
    return f"{_origin(request)}/api/auth/oauth2/callback"


def _extract_username(userinfo: Any) -> Optional[str]:
    """优先 username_claim；该字段缺失时依次尝试 login/preferred_username/email/name。"""
    if not isinstance(userinfo, dict):
        return None
    claim = (settings.oauth2_username_claim or "").strip() or "login"
    for key in dict.fromkeys([claim, *_CLAIM_FALLBACKS]):
        value = userinfo.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


@router.get("/oauth2/login")
async def oauth2_login(request: Request):
    """发起 OAuth2 授权码登录（免鉴权）：返回 {redirect_url} 供前端整页跳转。"""
    if not (settings.oauth2_client_id or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth2 未配置：请先在系统配置中填写客户端 ID 等参数",
        )
    if not (settings.oauth2_authorize_url or "").strip() or not (settings.oauth2_token_url or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth2 未配置：缺少授权端点或令牌端点地址",
        )

    _purge_states()
    state = secrets.token_hex(16)  # 32 位 hex 随机 state
    _oauth_states[state] = time.time()

    # F-09: 兼容 Flower OAuth2 格式
    is_flower_compatible = settings.oauth2_flower_compatible
    state_param_name = "flow_state" if is_flower_compatible else "state"
    
    # 当启用 flower 兼容模式时，使用 flower 默认的 redirect_uri 格式
    if is_flower_compatible:
        callback_url = f"{_origin(request)}/oauth2/callback"
    else:
        callback_url = _callback_url(request)

    params = {
        "response_type": "code",
        "client_id": settings.oauth2_client_id,
        "redirect_uri": callback_url,
        state_param_name: state,
    }
    if (settings.oauth2_scope or "").strip():
        params["scope"] = settings.oauth2_scope
    sep = "&" if "?" in settings.oauth2_authorize_url else "?"
    return {"redirect_url": settings.oauth2_authorize_url + sep + urlencode(params)}


@router.get("/oauth2/callback")
async def oauth2_callback(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
):
    """提供方授权回调（免鉴权）：校验 state → 换 token → 取 userinfo → 签发会话。"""

    def fail(code_name: str) -> RedirectResponse:
        logger.info("OAuth2 登录失败: %s", code_name)
        query = urlencode({"oauth_error": code_name})
        return RedirectResponse(f"{_origin(request)}/?{query}", status_code=302)

    # 提供方直接拒绝（用户取消授权等）会带 error 参数回跳
    if error:
        return fail("provider_denied")

    # state 校验（防 CSRF）：不存在或已过期
    _purge_states()
    issued_at = _oauth_states.pop(state, None)
    if issued_at is None or time.time() - issued_at > _STATE_TTL:
        return fail("invalid_state")
    if not code:
        return fail("token_failed")

    try:
        # 1) 用授权码换 access_token
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                settings.oauth2_token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": _callback_url(request),
                    "client_id": settings.oauth2_client_id,
                    "client_secret": settings.oauth2_client_secret,
                },
            )
            resp.raise_for_status()
            token_data = resp.json()
        access_token = token_data.get("access_token") if isinstance(token_data, dict) else None
        if not access_token:
            return fail("token_failed")

        # 2) 取 userinfo（带 Bearer）；未配置 userinfo_url 时退回令牌响应本身
        userinfo = token_data
        if (settings.oauth2_userinfo_url or "").strip():
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    settings.oauth2_userinfo_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                resp.raise_for_status()
                userinfo = resp.json()
    except Exception as exc:  # noqa: BLE001 - 任何失败统一按 token_failed 回跳
        logger.warning("OAuth2 令牌交换/用户信息获取失败: %s", exc)
        return fail("token_failed")

    # 3) 取用户名
    username = _extract_username(userinfo)
    if not username:
        return fail("token_failed")

    # 4) 白名单校验：auth 正则非空时，用户名或其 email 等字段任一命中才放行
    whitelist = (settings.auth or "").strip()
    if whitelist:
        candidates = {username}
        if isinstance(userinfo, dict):
            for key in ("email", "preferred_username", "login", "name"):
                value = userinfo.get(key)
                if isinstance(value, str) and value.strip():
                    candidates.add(value.strip())
        try:
            allowed = any(re.search(whitelist, c) for c in candidates)
        except re.error:
            logger.error("邮箱白名单正则不合法，拒绝 OAuth2 登录: %r", whitelist)
            allowed = False
        if not allowed:
            return fail("not_allowed")

    # 5) 与 basic auth 同构的会话：同样的 create_access_token JWT，
    #    get_current_user 的 Bearer 分支直接认可；302 回前端根路径落地
    token = create_access_token(username)
    query = urlencode({"token": token, "user": username})
    return RedirectResponse(f"{_origin(request)}/?{query}", status_code=302)
