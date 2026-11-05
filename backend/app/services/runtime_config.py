"""运行时配置：可在 Web 界面查看与修改的配置项。

设计要点
--------
1. **单一事实来源仍是 Settings**：这里不重新造配置系统，只是给 Settings
   套一层"哪些字段能在运行时改、改完写到哪里"的元数据。
2. **分级**：
   - ``editable=True``  改完立刻生效（写回 settings 实例 + 落盘）
   - ``editable=False`` 只读展示，改动需要重启进程（如 host/port/broker_url）
3. **持久化**：改动写入 ``.env`` 格式的覆盖文件（默认 ``flowerui.runtime.env``，
   每行 ``KEY=VALUE``，复合类型以 JSON 书写），进程启动时自动回放，
   保证重启后仍然生效。兼容旧版 ``flowerui.runtime.json``（首次启动自动迁移）。
4. **脱敏**：secret_key、oauth2_secret、basic_auth 的密码部分不外发明文。
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..core.config import settings

logger = logging.getLogger("flowerui.config")

_lock = threading.RLock()

RUNTIME_FILE = Path(
    os.environ.get("FLOWER_RUNTIME_CONFIG_FILE", "flowerui.runtime.env")
).resolve()


class Field:
    """一条可展示 / 可编辑的配置项元数据。"""

    __slots__ = (
        "key", "label", "group", "type", "editable", "desc",
        "unit", "minimum", "maximum", "options", "secret", "restart",
        "todo", "todo_reason",
    )

    def __init__(
        self,
        key: str,
        label: str,
        group: str,
        type_: str = "string",
        *,
        editable: bool = False,
        desc: str = "",
        unit: str = "",
        minimum: Optional[float] = None,
        maximum: Optional[float] = None,
        options: Optional[List[Any]] = None,
        secret: bool = False,
        restart: bool = False,
        todo: bool = False,
        todo_reason: str = "",
    ) -> None:
        self.key = key
        self.label = label
        self.group = group
        self.type = type_
        self.editable = editable
        self.desc = desc
        self.unit = unit
        self.minimum = minimum
        self.maximum = maximum
        self.options = options
        self.secret = secret
        self.restart = restart
        self.todo = todo
        self.todo_reason = todo_reason


# --------------------------------------------------------------------------
# 配置项清单
# --------------------------------------------------------------------------
GROUPS = [
    {"id": "service", "label": "服务", "icon": "Setting", "desc": "HTTP 服务监听与跨域"},
    {"id": "celery", "label": "Celery 连接", "icon": "Connection", "desc": "消息中间件连接与控制超时"},
    {"id": "routing", "label": "任务路由", "icon": "Guide", "desc": "下发任务时的默认队列与任务→队列映射"},
    {"id": "capacity", "label": "状态容量", "icon": "Coin", "desc": "内存中保留的 worker / 任务数量上限"},
    {"id": "persistence", "label": "持久化", "icon": "FolderOpened", "desc": "状态落盘"},
    {"id": "display", "label": "展示", "icon": "View", "desc": "列表列与时间显示"},
    {"id": "ui", "label": "界面与实时通道", "icon": "Monitor", "desc": "主题默认值、数据通道与轮询间隔"},
    {"id": "auth", "label": "认证", "icon": "Lock", "desc": "登录凭据与令牌有效期"},
    {"id": "mock", "label": "演示模式", "icon": "MagicStick", "desc": "无 broker 时的内置模拟集群"},
]

FIELDS: List[Field] = [
    # ---------- 服务 ----------
    Field("host", "监听地址", "service", "string", editable=True, desc="HTTP 服务绑定的网卡地址", restart=True),
    Field("port", "监听端口", "service", "int", editable=True, desc="HTTP 服务端口", restart=True),
    Field("url_prefix", "URL 前缀", "service", "string", editable=True, desc="反向代理下的子路径", restart=True),
    Field("cors_origins", "CORS 白名单", "service", "list", editable=True, desc="允许跨域的来源；填通配 * 时浏览器将不携带凭据（credentials 关闭）", restart=True),
    Field("debug", "调试日志", "service", "bool", editable=True, desc="打开后输出 DEBUG 级别日志"),

    # ---------- Celery ----------
    Field("broker_url", "Broker URL", "celery", "string",
          desc="消息中间件地址。本地务必用 127.0.0.1 而非 localhost，"
               "否则 IPv6 回退会给每次连接额外增加约 2 秒",
          secret=True, restart=True),
    Field("inspect_timeout", "inspect 超时", "celery", "float", editable=True,
          unit="ms", minimum=200, maximum=60000,
          desc="向 worker 广播 inspect 命令的等待时长，调大更稳、调小更跟手"),
    Field("control_timeout", "控制命令超时", "celery", "float", editable=True,
          unit="ms", minimum=200, maximum=60000,
          desc="pool grow/shrink、add_consumer 等远程控制命令的回执等待时长"),
    Field("enable_events", "启用事件采集", "celery", "bool", editable=True,
          desc="关闭后不再消费 Celery 事件流", restart=True),

    # ---------- 任务路由 ----------
    Field("task_default_queue", "默认队列", "routing", "string", editable=True,
          desc="任务未命中路由表时使用的队列"),
    Field("task_routes", "任务→队列映射", "routing", "dict", editable=True,
          desc="下发任务页据此自动预填队列，例如 tasks.send_email → emails"),

    # ---------- 容量 ----------
    Field("max_workers", "Worker 上限", "capacity", "int", editable=True,
          minimum=1, maximum=100000, desc="内存中保留的 worker 数量上限"),
    Field("max_tasks", "任务上限", "capacity", "int", editable=True,
          minimum=100, maximum=5000000, desc="内存中保留的任务数量上限"),
    Field("purge_offline_workers", "离线清理", "capacity", "int", editable=True,
          unit="s", minimum=0, maximum=86400,
          desc="worker 离线超过该秒数后从列表移除，留空表示不清理"),

    # ---------- 持久化 ----------
    Field("persistent", "启用持久化", "persistence", "bool", editable=True, desc="重启后恢复状态", restart=True),
    Field("db", "状态文件", "persistence", "string", editable=True, desc="状态落盘路径", restart=True),
    Field("state_save_interval", "保存间隔", "persistence", "int", editable=True,
          unit="ms", minimum=0, maximum=3600000, desc="0 表示关闭定时保存"),

    # ---------- 展示 ----------
    Field("auto_refresh", "自动刷新", "display", "bool", editable=True, desc="列表页自动刷新"),
    Field("natural_time", "自然时间", "display", "bool", editable=True,
          desc="时间显示为『3 分钟前』而不是绝对时间"),
    Field("tasks_columns", "任务列表列", "display", "string", editable=True,
          desc="逗号分隔，控制任务表格默认展示哪些列"),

    # ---------- 界面 ----------
    Field("ui_default_theme", "默认主题", "ui", "enum", editable=True,
          options=["auto", "light", "dark", "tech-liquid", "aurora"],
          desc="新访客首次打开时的主题，auto 表示跟随操作系统"),
    Field("ui_transport", "数据通道", "ui", "enum", editable=True,
          options=["ws", "polling"],
          desc="ws=WebSocket 实时推送；polling=HTTP 轮询，适合不支持 WS 的代理"),
    Field("ui_poll_interval", "轮询间隔", "ui", "int", editable=True,
          unit="ms", minimum=1000, maximum=120000,
          desc="仅在轮询模式下生效，间隔越小越实时、请求也越多"),
    Field("ui_sidebar_collapsed", "侧边栏默认收起", "ui", "bool", editable=True,
          desc="新访客首次打开时导航是否处于收起状态"),

    # ---------- 认证 ----------
    # 说明：secret_key 尚不支持界面设置，用 todo 标记让前端给出"待完善"提示。
    Field("basic_auth", "登录凭据", "auth", "list", editable=True,
          desc="user:pass `,`间隔，配置后前端将强制走登录页；在界面改完点『重启系统』生效",
          secret=True, restart=True),
    Field("basic_auth_enabled", "登录凭证管理", "auth", "bool", editable=True,
          desc="总开关：开启后界面展示并允许编辑各用户凭据（展开可改自己的账号密码）；关闭则隐藏凭据管理"),
    Field("auth", "邮箱白名单正则", "auth", "string", editable=True, restart=True,
          desc="OAuth2 登录白名单：正则匹配通过才允许 OAuth2 登录（依次比对用户名/email 等字段）；留空不限制"),
    Field("auth_provider", "OAuth 提供方", "auth", "string", editable=True, restart=True,
          desc="OAuth2 提供方名称（登录页第三方登录按钮文案），如 GitHub / GitLab"),
    Field("secret_key", "JWT 密钥", "auth", "string", secret=True, restart=True,
          todo=True, todo_reason="暂不支持界面设置；留空时每次启动自动生成随机密钥，重启后旧令牌失效"),
    Field("token_expire_minutes", "令牌有效期", "auth", "int", editable=True,
          unit="min", minimum=5, maximum=525600, desc="登录令牌过期时间"),
    # 通用 OAuth2 授权码流程（GitHub / GitLab / OIDC 等任意兼容提供方），URL 全部可配
    Field("oauth2_provider", "OAuth2 显示名", "auth", "string", editable=True,
          desc="OAuth2 提供方显示名（登录页按钮文案），留空回退到『OAuth 提供方』"),
    Field("oauth2_authorize_url", "授权端点", "auth", "string", editable=True,
          desc="提供方授权页地址（authorization endpoint），OAuth2 登录的跳转起点"),
    Field("oauth2_token_url", "令牌端点", "auth", "string", editable=True,
          desc="提供方换令牌地址（token endpoint），用授权码 code 换 access_token"),
    Field("oauth2_userinfo_url", "用户信息端点", "auth", "string", editable=True,
          desc="提供方用户信息地址（userinfo），带 Bearer 令牌请求；留空则从令牌响应中取用户字段"),
    Field("oauth2_client_id", "客户端 ID", "auth", "string", editable=True,
          desc="OAuth2 client_id；非空即启用登录页的第三方登录入口"),
    Field("oauth2_client_secret", "客户端密钥", "auth", "string", editable=True,
          secret=True, desc="OAuth2 client_secret，换取 access_token 时使用"),
    Field("oauth2_scope", "授权 Scope", "auth", "string", editable=True,
          desc="请求的权限范围 scope，如 read:user；留空使用提供方默认"),
    Field("oauth2_username_claim", "用户名字段", "auth", "string", editable=True,
          desc="userinfo 中作为系统用户名的字段名；该字段缺失时依次尝试 login/preferred_username/email/name"),
    Field("oauth2_redirect_uri", "回调地址", "auth", "string",
          desc="OAuth2 回调重定向地址（redirect_uri），需与提供方注册一致；留空自动使用本服务 /api/auth/oauth2/callback"),

    # ---------- 告警 ----------
    Field("alert_enabled", "启用告警", "celery", "bool", editable=True,
          desc="启用告警系统，开启后规则会定期评估并推送告警"),
    Field("alert_webhook_url", "Webhook URL", "celery", "string", editable=True,
          desc="告警推送的 Webhook 地址，留空则仅输出到控制台"),
    Field("alert_rules", "告警规则(JSON)", "celery", "string", editable=False,
          desc="启动时加载的告警规则 JSON 字符串，格式为数组"),

    # ---------- 演示模式 ----------
    Field("mock", "强制演示模式", "mock", "bool", editable=True, desc="忽略真实 broker，使用内置模拟集群", restart=True),
    Field("mock_workers", "模拟 worker 数", "mock", "int", editable=True, restart=True),
    Field("mock_seed_tasks", "模拟任务数", "mock", "int", editable=True, restart=True),
]

FIELD_MAP: Dict[str, Field] = {f.key: f for f in FIELDS}

# UI 相关字段不在 Settings 上，单独存放
_UI_DEFAULTS: Dict[str, Any] = {
    "ui_default_theme": "auto",
    "ui_transport": "ws",
    "ui_poll_interval": 3000,
    "ui_sidebar_collapsed": False,
}
_ui_state: Dict[str, Any] = dict(_UI_DEFAULTS)

# 记录进程启动时的原始值，用于"恢复默认"
_boot_values: Dict[str, Any] = {}

# 某些字段改动后需要通知其它模块，这里挂钩子
_hooks: Dict[str, List[Callable[[Any], None]]] = {}


def on_change(key: str, fn: Callable[[Any], None]) -> None:
    _hooks.setdefault(key, []).append(fn)


def _fire(key: str, value: Any) -> None:
    for fn in _hooks.get(key, []):
        try:
            fn(value)
        except Exception:  # noqa: BLE001 - 钩子不应影响主流程
            logger.exception("配置变更钩子执行失败: %s", key)


# --------------------------------------------------------------------------
# 读取
# --------------------------------------------------------------------------
def _raw_value(key: str) -> Any:
    if key in _UI_DEFAULTS:
        return _ui_state.get(key, _UI_DEFAULTS[key])
    return getattr(settings, key, None)


def _mask(field: Field, value: Any) -> Any:
    """脱敏：URL 只隐藏密码段，密钥整体打码，凭据只留用户名。"""
    if not field.secret or value in (None, "", []):
        return value

    # t8 扩展：{old,new} 等嵌套结构一律整体打码（按 str() 做 URL 掩码对
    # dict 不可靠，且不同形态的凭据位置不固定，整体掩码最安全）
    if isinstance(value, dict):
        return "******"

    if field.key == "basic_auth":
        out = []
        for item in value:
            user = str(item).split(":", 1)[0]
            out.append(f"{user}:******")
        return out

    if field.key == "secret_key":
        return "******"

    text = str(value)
    if "://" in text and "@" in text:
        head, _, tail = text.partition("://")
        creds, _, host = tail.rpartition("@")
        if creds:
            user = creds.split(":", 1)[0]
            return f"{head}://{user}:******@{host}"
    # t8：普通字符串形态的密文（如 oauth2_client_secret）整体打码；
    # 仅当值是「不含凭据段的 URL」（本身无敏感部分）时才原样返回。
    if "://" in text:
        return text
    return "******"


def describe(include_secret_values: bool = False) -> Dict[str, Any]:
    """返回给前端的完整配置视图。"""
    with _lock:
        items = []
        for f in FIELDS:
            value = _raw_value(f.key)
            items.append(
                {
                    "key": f.key,
                    "label": f.label,
                    "group": f.group,
                    "type": f.type,
                    "editable": f.editable,
                    "restart_required": f.restart,
                    "secret": f.secret,
                    "todo": f.todo,
                    "todo_reason": f.todo_reason,
                    "desc": f.desc,
                    "unit": f.unit,
                    "min": f.minimum,
                    "max": f.maximum,
                    "options": f.options,
                    # B-04：secret 字段默认一律脱敏（含 basic_auth 等可编辑项），
                    # 防止 GET/PUT /api/config 外发明文凭据；界面改用「掩码值 + 合并」编辑。
                    "value": value if (not f.secret or include_secret_values) else _mask(f, value),
                    # B-04：default（启动值）同样脱敏，避免外发明文
                    "default": (
                        _boot_values.get(f.key)
                        if not f.secret
                        else _mask(f, _boot_values.get(f.key))
                    ),
                    "modified": f.key in _overrides,
                }
            )
        return {
            "groups": GROUPS,
            "items": items,
            "runtime_file": str(RUNTIME_FILE),
            "overrides": sorted(_overrides.keys()),
            "editable_keys": [f.key for f in FIELDS if f.editable],
        }


def ui_defaults() -> Dict[str, Any]:
    """给前端启动时用的界面默认值。"""
    with _lock:
        return {
            "theme": _ui_state.get("ui_default_theme", "auto"),
            "transport": _ui_state.get("ui_transport", "ws"),
            "poll_interval": _ui_state.get("ui_poll_interval", 3000),
            "sidebar_collapsed": _ui_state.get("ui_sidebar_collapsed", False),
        }


# --------------------------------------------------------------------------
# 写入
# --------------------------------------------------------------------------
_overrides: Dict[str, Any] = {}


class ConfigError(ValueError):
    """配置校验失败。"""


def _coerce(field: Field, value: Any) -> Any:
    t = field.type
    try:
        if t == "bool":
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)
        if t == "int":
            if value in (None, ""):
                return None
            return int(value)
        if t == "float":
            if value in (None, ""):
                return None
            return float(value)
        if t == "list":
            if isinstance(value, str):
                return [x.strip() for x in value.split(",") if x.strip()]
            return list(value or [])
        if t == "dict":
            if isinstance(value, str):
                value = json.loads(value or "{}")
            if not isinstance(value, dict):
                raise ConfigError(f"{field.label} 需要是对象")
            return {str(k): str(v) for k, v in value.items()}
        if t == "enum":
            text = str(value)
            if field.options and text not in field.options:
                raise ConfigError(
                    f"{field.label} 只能取 {'、'.join(map(str, field.options))}"
                )
            return text
        return "" if value is None else str(value)
    except ConfigError:
        raise
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field.label} 取值不合法：{exc}") from exc


def _validate_range(field: Field, value: Any) -> None:
    if value is None or field.type not in ("int", "float"):
        return
    if field.minimum is not None and value < field.minimum:
        raise ConfigError(f"{field.label} 不能小于 {field.minimum}{field.unit}")
    if field.maximum is not None and value > field.maximum:
        raise ConfigError(f"{field.label} 不能大于 {field.maximum}{field.unit}")


def _is_masked_password(pass_value: Any) -> bool:
    """B-04：判断密码是否为掩码形态（空或全为星号）。"""
    if pass_value is None:
        return True
    p = str(pass_value).strip()
    return p == "" or set(p) == {"*"}


def _is_masked_value(field: Field, value: Any) -> bool:
    """t8/B-04：判断提交的值是否为掩码形态（用户并未真正修改密文字段）。

    覆盖两种形态：全星号（******）与掩码 URL（scheme://user:******@host）。
    """
    if not isinstance(value, str):
        return False
    p = value.strip()
    if not p:
        return False
    if set(p) == {"*"}:
        return True
    return "******" in p


def _merge_basic_auth(submitted: Optional[List[str]]) -> List[str]:
    """B-04 basic_auth 合并策略。

    submitted 为前端提交的列表（user:pass，密码可能为掩码形态 user:******）；
    settings.basic_auth 为当前生效列表。掩码条目保留同一用户的原密码（用户须已
    存在），明文条目替换或追加。由此界面无需读取旧密码即可改凭据，且 /api/config
    不再外发明文。
    """
    existing_by_user: Dict[str, str] = {}
    for entry in (settings.basic_auth or []):
        user = str(entry).split(":", 1)[0].strip()
        if user:
            existing_by_user[user] = str(entry)

    merged: List[str] = []
    seen: set = set()
    for entry in (submitted or []):
        text = str(entry).strip()
        if not text:
            continue
        user, _sep, pass_value = text.partition(":")
        user = user.strip()
        if not user or user in seen:
            continue
        if _is_masked_password(pass_value):
            # 掩码形态：保留同一用户原密码；用户不存在则跳过（掩码无法新建）
            if user in existing_by_user:
                merged.append(existing_by_user[user])
                seen.add(user)
            continue
        # 新明文：替换或追加
        merged.append(f"{user}:{pass_value}")
        seen.add(user)
    return merged


def update(changes: Dict[str, Any], *, persist: bool = True, allow_restart: bool = False) -> Dict[str, Any]:
    """批量更新可编辑配置，返回实际生效的键值。

    ``allow_restart=True`` 用于配置文件回放：来自磁盘覆盖文件的值即用户意图，
    允许直接设置 ``editable=False`` 的字段（如 basic_auth、broker_url），否则
    回放会因拒绝非可编辑字段而整体失败。
    """
    if not isinstance(changes, dict) or not changes:
        raise ConfigError("没有需要修改的配置项")

    # B-03 前置校验：开启登录凭证总开关时凭据列表不得为空（防后门/锁死）。
    # 在写入前校验，避免内存状态已被改动后校验才失败。
    if "basic_auth_enabled" in changes:
        _enabled_field = FIELD_MAP["basic_auth_enabled"]
        if _coerce(_enabled_field, changes["basic_auth_enabled"]):
            _eff_basic: Any = settings.basic_auth
            if "basic_auth" in changes:
                _eff_basic = _merge_basic_auth(
                    _coerce(FIELD_MAP["basic_auth"], changes["basic_auth"])
                )
            if not _eff_basic:
                raise ConfigError(
                    "无法开启登录凭证管理：凭据列表 (basic_auth) 为空，"
                    "请先配置至少一个 user:pass"
                )

    applied: Dict[str, Any] = {}
    with _lock:
        for key, raw in changes.items():
            field = FIELD_MAP.get(key)
            if field is None:
                raise ConfigError(f"未知配置项：{key}")
            if not field.editable and not allow_restart:
                raise ConfigError(f"{field.label} 需要重启进程才能修改")

            value = _coerce(field, raw)
            _validate_range(field, value)

            # B-04：basic_auth 合并策略——掩码条目保留原密码，明文条目替换/追加，
            # 使界面改凭据无需读取旧密码，且 /api/config 不再外发明文。
            if key == "basic_auth":
                value = _merge_basic_auth(value)
            elif field.secret and _is_masked_value(field, value):
                # t8：界面把掩码值原样提交 = 用户未改动该密文字段（如
                # oauth2_client_secret 显示 ****** 后随其它字段一起保存），
                # 保留原值，防止真实密钥被 ****** 覆盖。
                continue

            if key in _UI_DEFAULTS:
                _ui_state[key] = value
            else:
                setattr(settings, key, value)

            _overrides[key] = value
            applied[key] = value
            _fire(key, value)

        if persist:
            _save()

    logger.info("运行时配置已更新: %s", ", ".join(applied))
    return applied


def reset(keys: Optional[List[str]] = None, *, persist: bool = True) -> List[str]:
    """恢复到进程启动时的取值。keys 为空表示全部恢复。"""
    with _lock:
        targets = list(_overrides.keys()) if not keys else [k for k in keys if k in _overrides]
        for key in targets:
            boot = _boot_values.get(key)
            if key in _UI_DEFAULTS:
                _ui_state[key] = boot
            else:
                setattr(settings, key, boot)
            _overrides.pop(key, None)
            _fire(key, boot)
        if persist:
            _save()
    logger.info("运行时配置已重置: %s", ", ".join(targets) or "(无)")
    return targets


# --------------------------------------------------------------------------
# 落盘 / 回放
# --------------------------------------------------------------------------
def _read_env_file(path: Path) -> Dict[str, Any]:
    """解析 ``.env`` 格式的覆盖文件，返回 ``{key: value}``。

    每行 ``KEY=VALUE``：
    - 复合类型（列表/字典/布尔/数字）以 JSON 书写，``json.loads`` 还原；
    - 裸字符串（未加引号）``json.loads`` 失败则按原样保留。
    支持 ``#`` 注释与空行。
    """
    data: Dict[str, Any] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return data
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        try:
            data[key] = json.loads(value)
        except (ValueError, TypeError):
            # 如果是 basic_auth，用逗号分隔解析为列表
            if key == "basic_auth" and "," in value:
                data[key] = [x.strip() for x in value.split(",") if x.strip()]
            else:
                data[key] = value  # 裸字符串兜底
    return data


def _save() -> None:
    """行级更新：只改 ``_overrides`` 中存在的键，保留文件里其它行。

    行为（关键：绝不整文件覆盖，以免丢失用户手工配置与注释）：
    - 读现有文件全部行；
    - 对 ``_overrides`` 中每个键：文件中已有该行则**就地替换**，否则**追加到末尾**；
    - 文件里未被管理的行（用户注释、``basic_auth`` 等手工键）原样保留。
    - ``basic_auth`` 特殊处理：保存为逗号分隔字符串（如 ``admin:admin,user1:pass1``）
      而非 JSON 数组格式，便于手工编辑。
    """
    try:
        RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)

        existing: List[str] = []
        key_line_idx: Dict[str, int] = {}
        if RUNTIME_FILE.exists():
            for i, raw in enumerate(RUNTIME_FILE.read_text(encoding="utf-8").splitlines()):
                existing.append(raw)
                stripped = raw.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key = stripped.partition("=")[0].strip()
                if key:
                    key_line_idx[key] = i  # 同名取最后一行

        out = list(existing)
        appended: List[str] = []
        for k, v in _overrides.items():
            # basic_auth 特殊处理：列表转为逗号分隔字符串
            if k == "basic_auth" and isinstance(v, list):
                new_line = f"{k}={','.join(str(x) for x in v)}"
            else:
                new_line = f"{k}={json.dumps(v, ensure_ascii=False)}"
            if k in key_line_idx:
                out[key_line_idx[k]] = new_line
            else:
                appended.append(new_line)

        if appended:
            if out and out[-1].strip():
                out.append("")  # 末行非空则补一空行，避免追加内容粘连
            out.extend(appended)

        new_content = ("\n".join(out).rstrip() + "\n") if out else "\n"
        # #5：仅当文件内容真的变化时才备份（重复保存同一值不刷备份）
        current_content = (
            RUNTIME_FILE.read_text(encoding="utf-8") if RUNTIME_FILE.exists() else None
        )
        if current_content != new_content:
            _backup_current()
        RUNTIME_FILE.write_text(new_content, encoding="utf-8")
    except OSError:
        logger.exception("运行时配置写入失败: %s", RUNTIME_FILE)


def load() -> None:
    """进程启动时调用：先记录启动值，再回放磁盘上的覆盖项。
    
    优先从 SQLite 加载配置，如 SQLite 无数据则回退到 .env 文件。
    """
    with _lock:
        for f in FIELDS:
            _boot_values[f.key] = _raw_value(f.key)
        
        # 尝试从 SQLite 加载配置（优先级高于 .env）
        db_configs = _load_from_db()
        if db_configs:
            logger.info("从 SQLite 加载配置，跳过 .env 文件")
            known = {k: v for k, v in db_configs.items() if k in FIELD_MAP}
            if known:
                try:
                    update(known, persist=False, allow_restart=True)
                    logger.info("已回放 SQLite 配置覆盖项: %s", ", ".join(known))
                except ConfigError as exc:
                    logger.warning("SQLite 配置回放失败，已忽略: %s", exc)
            return

        # 迁移：旧版 JSON 覆盖文件 → .env 格式（兼容升级）。
        # 迁移成功后删除旧 JSON，避免它日后再次被读回造成"反向污染"。
        legacy = RUNTIME_FILE.with_suffix(".json")
        if not RUNTIME_FILE.exists() and legacy.exists():
            try:
                legacy_data = json.loads(legacy.read_text(encoding="utf-8"))
                if isinstance(legacy_data, dict) and legacy_data:
                    _overrides.clear()
                    _overrides.update(legacy_data)
                    _save()
                    legacy.unlink()
                    logger.info("已将旧版 JSON 覆盖文件迁移为 .env 格式并删除旧文件: %s", RUNTIME_FILE)
            except (OSError, ValueError):
                logger.warning("旧版 JSON 覆盖文件无法迁移，已忽略: %s", legacy)

        # 首次：覆盖文件不存在时，生成一份完整带注释的默认配置模板，
        # 方便用户在此基础上一目了然地手工修改（之后保存只做行级更新）。
        if not RUNTIME_FILE.exists():
            try:
                RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)
                RUNTIME_FILE.write_text(_materialize_full(), encoding="utf-8")
                logger.info("已生成带注释的运行时配置模板: %s", RUNTIME_FILE)
            except OSError:
                logger.exception("生成配置模板失败: %s", RUNTIME_FILE)
            return  # 模板即默认值，无需回放

        data = _read_env_file(RUNTIME_FILE)
        if not data:
            return

        # 容错：字段表已移除的项（如 result_backend/broker_api）直接跳过，
        # 避免单个未知键导致整份覆盖文件回放失败，连 basic_auth 也一起失效。
        unknown = [k for k in data if k not in FIELD_MAP]
        for k in unknown:
            logger.warning("运行时配置忽略未知项（已从字段表移除）：%s", k)
        known = {k: v for k, v in data.items() if k in FIELD_MAP}
        if known:
            try:
                update(known, persist=False, allow_restart=True)
                logger.info("已回放运行时配置覆盖项: %s", ", ".join(known))
            except ConfigError as exc:
                logger.warning("运行时配置回放失败，已忽略: %s", exc)


# --------------------------------------------------------------------------
# SQLite 集成方法
# --------------------------------------------------------------------------
def _load_from_db() -> Dict[str, Any]:
    """从 SQLite 加载运行时配置。
    
    Returns:
        {key: value} 字典，为空表示数据库中没有配置
    """
    try:
        from .config_db import get_all_configs
        configs = get_all_configs()
        result = {}
        for config in configs:
            key = config.get('key')
            value = config.get('value', '')
            if key:
                # 尝试解析 JSON 值
                try:
                    result[key] = json.loads(value)
                except (ValueError, TypeError):
                    result[key] = value
        logger.info(f"已从 SQLite 加载 {len(result)} 项配置")
        return result
    except Exception as e:
        logger.warning(f"从 SQLite 加载配置失败: {e}")
        return {}


def _save_to_db() -> None:
    """将内存中的配置覆盖保存到 SQLite。
    
    保持与 _save() 相同的行级更新策略，同时写入数据库。
    """
    try:
        from .config_db import set_config
        for key, value in _overrides.items():
            field = FIELD_MAP.get(key)
            if field is None:
                continue
            
            # 转换值格式（列表/字典转为 JSON 字符串）
            if isinstance(value, (list, dict)):
                value_str = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, bool):
                value_str = 'true' if value else 'false'
            else:
                value_str = str(value)
            
            # 确定参数
            secret = field.secret
            group = field.group
            restart_required = field.restart
            
            set_config(
                key=key,
                value=value_str,
                secret=secret,
                group=group,
                editable=field.editable,
                restart_required=restart_required,
                changed_by="system",
            )
        
        logger.info(f"已将配置保存到 SQLite")
    except Exception as e:
        logger.error(f"保存配置到 SQLite 失败: {e}")


def migrate_from_env() -> int:
    """从旧的 .env 文件迁移配置到 SQLite。
    
    Returns:
        迁移的配置项数量
    """
    try:
        from .config_db import migrate_from_env as _migrate
        count = _migrate(RUNTIME_FILE)
        if count > 0:
            logger.info(f"配置迁移完成: {count} 项已从 .env 迁移到 SQLite")
        return count
    except Exception as e:
        logger.error(f"配置迁移失败: {e}")
        return 0


# --------------------------------------------------------------------------
# 完整模板（带中文注释）
# --------------------------------------------------------------------------
def _materialize_full() -> str:
    """生成包含全部配置项与中文注释的 .env 模板文本。

    非密文字段写出当前默认值（方便查看）；密文字段（basic_auth 等）写出
    默认值，``secret_key`` 因每次启动随机，只给注释示例、不写生效行。
    """
    lines: List[str] = []
    lines.append("# ===========================================================")
    lines.append("# FlowerUI 运行时配置（.env 格式）")
    lines.append("# -----------------------------------------------------------")
    lines.append("# 规则：")
    lines.append("#   * 每行 KEY=VALUE；系统保存时只更新对应行，不覆盖你的注释/手工键")
    lines.append('#   * 列表/字典以 JSON 书写：cors_origins=["http://127.0.0.1:5556"]')
    lines.append('#   * 字典示例：task_routes={"tasks.send_email": "emails"}')
    lines.append('#   * 字符串含空格请用引号：db="flower state.db"')
    lines.append("#   * 修改后需重启的配置，在界面点「重启系统」即可生效")
    lines.append("# ===========================================================")
    lines.append("")

    for g in GROUPS:
        lines.append(f"# ---- {g['label']}（{g['desc']}） ----")
        for f in FIELDS:
            if f.group != g["id"]:
                continue
            meta = [f"类型={f.type}"]
            if f.options:
                meta.append("可选=" + "/".join(str(o) for o in f.options))
            if f.minimum is not None or f.maximum is not None:
                lo = "" if f.minimum is None else str(f.minimum)
                hi = "" if f.maximum is None else str(f.maximum)
                meta.append(f"范围={lo}~{hi}")
            if f.unit:
                meta.append(f"单位={f.unit}")
            if f.restart:
                meta.append("需重启=是")
            if f.secret:
                meta.append("密文=是")
            if not f.editable:
                meta.append("界面只读=是")
            desc = (f.desc or "").replace("\n", " ")
            lines.append(f"# {f.label}：{desc}  [{'; '.join(meta)}]")
            if f.todo:
                lines.append(f"# ⚠ 待完善：{f.todo_reason}")

            if f.key == "secret_key":
                # 随机密钥不落到模板明文，仅给注释示例
                lines.append("# secret_key=（留空则每次启动自动生成随机 JWT 密钥，推荐保持留空）")
                continue
            default_val = _raw_value(f.key)
            # basic_auth 与 _save() 保持一致：逗号分隔字符串（便于手工编辑），
            # 避免 materialize 后文件格式从 CSV 跳变成 JSON 数组
            if f.key == "basic_auth" and isinstance(default_val, list):
                lines.append(f"{f.key}={','.join(str(x) for x in default_val)}")
            else:
                lines.append(f"{f.key}={json.dumps(default_val, ensure_ascii=False)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def materialize() -> Dict[str, Any]:
    """把当前所有配置连同注释整体重写文件（「生成完整配置」按钮用）。

    与日常保存不同，这里是用户主动触发的「重新排版 + 加注释」。
    为遵循「不覆盖手工配置」原则：
    - FIELDS 中的键写出**当前生效值**（而非默认值），保留你已改的内容；
    - 文件中出现的、系统未管理的手工键（如 FLOWER_ 前缀或其它键）原样保留。
    """
    with _lock:
        RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)

        preserved: List[str] = []
        if RUNTIME_FILE.exists():
            for raw in RUNTIME_FILE.read_text(encoding="utf-8").splitlines():
                stripped = raw.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key = stripped.partition("=")[0].strip()
                if key and key not in FIELD_MAP:
                    preserved.append(raw)

        content = _materialize_full()
        if preserved:
            content = (
                content.rstrip()
                + "\n\n# ---- 以下为系统未管理、你手工添加的配置（已保留） ----\n"
                + "\n".join(preserved)
                + "\n"
            )
        # #5：仅当内容真的变化时才备份
        current_content = (
            RUNTIME_FILE.read_text(encoding="utf-8") if RUNTIME_FILE.exists() else None
        )
        backup_name = None
        if current_content != content:
            backup_name = _backup_current()
        RUNTIME_FILE.write_text(content, encoding="utf-8")
        logger.info("已生成完整配置模板: %s", RUNTIME_FILE)
        # t4 收尾①：返回消息带备份路径，让用户知道原文件可找回
        message = "已生成完整配置模板"
        if backup_name:
            message = f"已生成完整配置模板（原文件备份到 {backup_name}）"
        return {
            "ok": True,
            "message": message,
            "runtime_file": str(RUNTIME_FILE),
            "backup": backup_name,
        }


# --------------------------------------------------------------------------
# #5 配置备份：每次改写文件前自动建时间戳备份，支持列表 / 回滚 / 删除
# --------------------------------------------------------------------------
BACKUP_KEEP = 20  # 最多保留的备份数
_BAK_RE = re.compile(r"^[A-Za-z0-9._-]+\.bak$")


def _backup_glob():
    return RUNTIME_FILE.parent.glob(f"{RUNTIME_FILE.name}.*.bak")


def _latest_backup() -> Optional[Path]:
    pats = [p for p in _backup_glob() if p.is_file()]
    if not pats:
        return None
    return max(pats, key=lambda p: p.stat().st_mtime)


def _prune_backups() -> None:
    """只保留最近 BACKUP_KEEP 份备份，删除更旧的。"""
    try:
        pats = sorted(
            (p for p in _backup_glob() if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in pats[BACKUP_KEEP:]:
            old.unlink()
            logger.info("已清理旧配置备份: %s", old.name)
    except OSError:
        logger.exception("清理配置备份失败")


def _backup_current() -> Optional[str]:
    """修改运行时文件前备份当前文件。

    - 文件不存在 → 无需备份；
    - 内容与最近一次备份相同 → 跳过（避免重复保存刷出一堆相同备份）；
    返回备份文件名；失败返回 None（不阻断保存主流程）。
    """
    try:
        if not RUNTIME_FILE.exists():
            return None
        current = RUNTIME_FILE.read_bytes()
        latest = _latest_backup()
        if latest is not None and latest.read_bytes() == current:
            return latest.name
        ts = time.strftime("%Y%m%d-%H%M%S")
        name = f"{RUNTIME_FILE.name}.{ts}.bak"
        i = 1
        while (RUNTIME_FILE.parent / name).exists():
            name = f"{RUNTIME_FILE.name}.{ts}-{i}.bak"
            i += 1
        (RUNTIME_FILE.parent / name).write_bytes(current)
        _prune_backups()
        return name
    except OSError:
        logger.exception("创建配置备份失败: %s", RUNTIME_FILE)
        return None


def _validate_backup_name(name: str) -> Path:
    """校验备份文件名（防路径穿越），返回完整路径。"""
    if not name or not _BAK_RE.match(name) or not name.startswith(RUNTIME_FILE.name + "."):
        raise ConfigError(f"非法的备份文件名：{name}")
    path = (RUNTIME_FILE.parent / name).resolve()
    if path.parent != RUNTIME_FILE.parent.resolve() or not path.is_file():
        raise ConfigError(f"备份不存在：{name}")
    return path


def list_backups() -> List[Dict[str, Any]]:
    """列出全部备份（新→旧），并计算与当前文件的差异配置键。"""
    out: List[Dict[str, Any]] = []
    for p in sorted(
        (p for p in _backup_glob() if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ):
        stat = p.stat()
        diff_keys: List[str] = []
        try:
            backup_data = _read_env_file(p)
            current_data = _read_env_file(RUNTIME_FILE) if RUNTIME_FILE.exists() else {}
            diff_keys = sorted(
                k for k in set(backup_data) | set(current_data)
                if backup_data.get(k) != current_data.get(k)
            )
        except OSError:
            pass
        out.append(
            {"name": p.name, "size": stat.st_size, "mtime": stat.st_mtime, "diff_keys": diff_keys}
        )
    return out


def restore_backup(name: str) -> Dict[str, Any]:
    """回滚运行时文件到指定备份，并同步内存配置。

    步骤：① 先给当前文件建新备份（回滚本身也可再回滚）
          ② 用备份内容原样覆盖运行时文件
          ③ 把当前所有被改动键重置回启动值
          ④ 回放备份中的已知键（persist=False，含需重启项）
    """
    path = _validate_backup_name(name)
    with _lock:
        _backup_current()
        content = path.read_text(encoding="utf-8")
        RUNTIME_FILE.write_text(content, encoding="utf-8")
        data = _read_env_file(path)

        # 内存状态先全部重置回启动值
        for key in list(_overrides.keys()):
            boot = _boot_values.get(key)
            if key in _UI_DEFAULTS:
                _ui_state[key] = boot if boot is not None else _UI_DEFAULTS[key]
            else:
                setattr(settings, key, boot)
            _overrides.pop(key, None)

        # 回放备份中的已知键
        known = {k: v for k, v in data.items() if k in FIELD_MAP}
        if known:
            try:
                update(known, persist=False, allow_restart=True)
            except ConfigError as exc:
                raise ConfigError(f"备份回放失败：{exc}") from exc
        logger.info("已回滚运行时配置到备份: %s", name)
        return {"restored": name, "applied": sorted(known.keys())}


def delete_backup(name: str) -> None:
    """删除指定备份。"""
    path = _validate_backup_name(name)
    with _lock:
        path.unlink()
    logger.info("已删除配置备份: %s", name)