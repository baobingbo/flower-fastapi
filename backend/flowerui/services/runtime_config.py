"""运行时配置：可在 Web 界面查看与修改的配置项。

设计要点
--------
1. **单一事实来源仍是 Settings**：这里不重新造配置系统，只是给 Settings
   套一层"哪些字段能在运行时改、改完写到哪里"的元数据。
2. **分级**：
   - ``editable=True``  改完立刻生效（写回 settings 实例 + 落盘）
   - ``editable=False`` 只读展示，改动需要重启进程（如 host/port）
3. **持久化**：改动写入 TOML 格式的覆盖文件（默认 ``flowerui.runtime.toml``，
   项目启动时自动回放，保证重启后仍然生效。
4. **脱敏**：secret_key、oauth2_secret、basic_auth 的密码部分不外发明文。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import toml

from .. import paths
from ..core.config import settings

logger = logging.getLogger("flowerui.config")

_lock = threading.RLock()

# 运行时配置（界面修改的值）保存到 `flowerui.runtime.toml`，TOML 格式
# = 用户意图存档，每次启动回放。
# 位置由 paths 统一决定：默认「执行代码的当前目录」，写前自动建目录。
# --runtime-config / FLOWER_RUNTIME_CONFIG_FILE 可显式指定其它路径。
RUNTIME_FILE = paths.runtime_file()
_EXPLICIT_RUNTIME_FILE = False


def set_runtime_file(path) -> None:
    """显式指定运行时配置文件（--runtime-config 用），之后不再随 cwd 重定位。"""
    global RUNTIME_FILE, _EXPLICIT_RUNTIME_FILE
    RUNTIME_FILE = Path(path).expanduser().resolve()
    _EXPLICIT_RUNTIME_FILE = True
    os.environ[paths.ENV_RUNTIME_FILE] = str(RUNTIME_FILE)


def relocate() -> Path:
    """按当前运行目录重新解析默认路径。

    CLI 会在导入本模块前 chdir；uvicorn --reload / --workers 子进程继承 cwd，
    这里再算一次可保证各进程读写同一份文件。显式指定过路径时不做改动。
    """
    global RUNTIME_FILE
    if not _EXPLICIT_RUNTIME_FILE:
        RUNTIME_FILE = paths.runtime_file()
    return RUNTIME_FILE


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
    Field("cors_origins", "CORS 白名单", "service", "list", editable=True, desc="允许跨域的来源", restart=True),
    Field("debug", "调试日志", "service", "bool", editable=True, desc="打开后输出 DEBUG 级别日志"),

    # ---------- Celery ----------
    Field("broker_url", "Broker URL", "celery", "string",
          editable=True,
          desc="消息中间件地址。本地务必用 127.0.0.1 而非 localhost，"
               "否则 IPv6 回退会给每次连接额外增加约 2 秒",
          secret=True, restart=True),
    Field("broker_transport_options", "Broker 传输选项", "celery", "dict", editable=True,
          desc='哨兵模式填 {"master_name": "mymaster"}；哨兵节点有密码时用 '
               '{"sentinel_kwargs": {"password": "xxx"}}；仅 redis:// 时留空',
          secret=True, restart=True),
    Field("result_backend", "结果后端", "celery", "string", editable=True,
          desc='非必须。不配（空）时 Celery 只提供投递/控制，不提供结果查询（wait=true '
               '的下发会抛 NotImplementedError）；要查询结果则配，示例 '
               'redis://user:YOUR_PASSWORD@redis.example.com:6379/1（最好与 broker 同机不同 DB 号）',
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
    # 说明：以下认证项部分功能尚不完善，用 todo 标记让前端给出"待完善"提示。
    Field("basic_auth", "登录凭据", "auth", "list", editable=True,
          desc="user:pass `,`间隔，配置后前端将强制走登录页；在界面改完点『重启系统』生效",
          secret=True, restart=True),
    Field("basic_auth_enabled", "登录凭证管理", "auth", "bool", editable=True,
          desc="总开关：开启后界面展示并允许编辑各用户凭据（展开可改自己的账号密码）；关闭则隐藏凭据管理"),
    Field("auth", "邮箱白名单正则", "auth", "string", editable=True, restart=True,
          todo=True, todo_reason="OAuth 登录流程尚未接入，该白名单目前不生效"),
    Field("auth_provider", "OAuth 提供方", "auth", "string", editable=True, restart=True,
          todo=True, todo_reason="OAuth 登录流程尚未接入，暂未对接任何第三方登录"),
    Field("secret_key", "JWT 密钥", "auth", "string", secret=True, restart=True,
          todo=True, todo_reason="暂不支持界面设置；留空时每次启动自动生成随机密钥，重启后旧令牌失效"),
    Field("token_expire_minutes", "令牌有效期", "auth", "int", editable=True,
          unit="min", minimum=5, maximum=525600, desc="登录令牌过期时间"),

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

# 命令行启动参数覆盖（``celery -A celery_app flowerui ...`` 注入）。
# 优先级最高：load() 回放运行时 TOML 时会跳过这些键，避免把用户显式传入的
# 参数盖回去。uvicorn 的 reload / workers 子进程通过同名环境变量自动回放。
CLI_OVERRIDES_ENV = "FLOWERUI_CLI_OVERRIDES"
_CLI_OVERRIDES: Dict[str, Any] = {}

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


_SECRET_KEY_HINTS = ("password", "passwd", "secret", "token")


def _mask_deep(value: Any) -> Any:
    """结构化脱敏 dict/list：保持原类型，仅把敏感键的值打码。

    此前对 dict 直接 ``str(value)`` 会把 ``broker_transport_options`` 之类
    变成 Python repr 字符串，前端 dict 编辑器拿到字符串后 ``Object.entries``
    按字符展开成一行行伪键值对。改为递归处理：嵌套中键名含
    password/passwd/secret/token 的字符串值打码为 ******，其余原样保留。
    """
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                out[k] = _mask_deep(v)
            elif isinstance(v, str) and any(h in str(k).lower() for h in _SECRET_KEY_HINTS):
                out[k] = "******"
            else:
                out[k] = v
        return out
    if isinstance(value, list):
        return [_mask_deep(v) for v in value]
    return value


def _mask(field: Field, value: Any) -> Any:
    """脱敏：URL 只隐藏密码段，dict/list 结构化脱敏，密钥整体打码，凭据只留用户名。"""
    if not field.secret or value in (None, "", []):
        return value

    if field.key == "basic_auth":
        out = []
        for item in value:
            user = str(item).split(":", 1)[0]
            out.append(f"{user}:******")
        return out

    if field.key == "secret_key":
        return "******"

    # dict/list（如 broker_transport_options）：保持结构化类型，不要 str() 成字符串
    if isinstance(value, (dict, list)):
        return _mask_deep(value)

    text = str(value)
    if "://" in text and "@" in text:
        head, _, tail = text.partition("://")
        creds, _, host = tail.rpartition("@")
        if creds:
            user = creds.split(":", 1)[0]
            return f"{head}://{user}:******@{host}"
    return text


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
                    # 展示一律脱敏（含可编辑密文字段）：密码段用 ****** 替代，避免明文泄露；
                    # 界面编辑所需的明文另由 edit_value 提供（仅 editable 且 secret 的字段）。
                    # include_secret_values=True 时（内部/测试用）value 才返回明文。
                    "value": value if include_secret_values else _mask(f, value),
                    "edit_value": value if (f.editable and f.secret) else None,
                    "default": _boot_values.get(f.key),
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
            # 嵌套容器（如 sentinel_kwargs={"password": "x"}）原样保留，
            # 标量仍统一转字符串，与既有行为兼容
            return {
                str(k): (v if isinstance(v, (dict, list)) else str(v))
                for k, v in value.items()
            }
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


def set_cli_overrides(overrides: Dict[str, Any]) -> Dict[str, Any]:
    """登记并立即应用命令行覆盖项，返回实际生效的键值。

    与 ``update()`` 的区别：

    * 不检查 ``editable``（命令行可以覆盖 host/port/broker_url 等需重启字段）；
    * 不落盘（命令行参数只对本次进程有效，重启后仍以 TOML 为准）；
    * 键被记入 ``_CLI_OVERRIDES``，``load()`` 回放磁盘配置时会跳过它们。

    ``celery flowerui`` 命令与 uvicorn 子进程都会调用本函数，故必须幂等。
    """
    global _CLI_OVERRIDES
    applied: Dict[str, Any] = {}
    with _lock:
        for key, raw in overrides.items():
            field = FIELD_MAP.get(key)
            if field is None:
                raise ConfigError(
                    f"未知配置项：{key}（可用 --list-keys 查看所有键名）"
                )
            value = _coerce(field, raw)
            _validate_range(field, value)
            if key in _UI_DEFAULTS:
                _ui_state[key] = value
            else:
                setattr(settings, key, value)
            applied[key] = value
            _fire(key, value)
        _CLI_OVERRIDES.update(applied)
    if applied:
        logger.info("命令行配置覆盖已生效: %s", ", ".join(sorted(applied)))
    return applied


def cli_overrides() -> Dict[str, Any]:
    """返回当前进程的命令行覆盖键（值不保证是最新的）。"""
    return dict(_CLI_OVERRIDES)


def update(changes: Dict[str, Any], *, persist: bool = True, allow_restart: bool = False) -> Dict[str, Any]:
    """批量更新可编辑配置，返回实际生效的键值。

    ``allow_restart=True`` 用于配置文件回放：来自磁盘覆盖文件的值即用户意图，
    允许直接设置 ``editable=False`` 的字段（如 basic_auth、broker_url），否则
    回放会因拒绝非可编辑字段而整体失败。
    """
    if not isinstance(changes, dict) or not changes:
        raise ConfigError("没有需要修改的配置项")

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
# TOML 序列化辅助
# --------------------------------------------------------------------------
def _toml_value(value: Any) -> str:
    """把任意值序列化成合法的 **TOML 内联值** 文本（标量 / 数组 / 内联表）。

    注意：``toml.dumps()`` 只接受 dict 且输出 ``key = value`` 形式，
    不能直接用于标量；这里自行实现，供模板与手工键写出使用。
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return '""'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        # JSON 字符串转义与 TOML 基本字符串兼容（中文保持原样）
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            key = json.dumps(str(k), ensure_ascii=False)
            parts.append(f"{key} = {_toml_value(v)}")
        return "{" + ", ".join(parts) + "}"
    return json.dumps(str(value), ensure_ascii=False)


def _read_toml_file(path: Path) -> Dict[str, Any]:
    """解析 TOML 格式的覆盖文件，返回 ``{key: value}``（只取根级键）。"""
    data: Dict[str, Any] = {}
    try:
        with path.open("r", encoding="utf-8") as f:
            parsed = toml.load(f)
        if not isinstance(parsed, dict):
            return data
        # 只要根级键（如 broker_url, host, result_backend）
        for k, v in parsed.items():
            if isinstance(k, str) and k.strip():
                data[k.strip()] = v
    except OSError:
        return data
    except Exception as exc:
        logger.warning("解析 TOML 运行时文件失败 %s: %s", path, exc)
        return data
    return data


def _save() -> None:
    """写回 currently 被界面修改过的键（``_overrides``）。

    行为（关键）：读 TOML 库 ``toml`` 把 ``_overrides`` 合并写入文件，
    只写系统托管的字段，不碰用户手动写的其它节。
    """
    try:
        RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)

        # 已有文件先读出来，保留非系统托管的节（如手工的 FLOWER_ órica键）
        existing = {}
        if RUNTIME_FILE.exists():
            try:
                with RUNTIME_FILE.open("r", encoding="utf-8") as f:
                    existing = toml.load(f) or {}
            except Exception:
                existing = {}

        out = dict(existing)
        for k, v in _overrides.items():
            # 系统托管的键，按 TOML 可表达的类型原样写
            out[k] = v

        with RUNTIME_FILE.open("w", encoding="utf-8") as f:
            toml.dump(out, f)
        logger.debug("运行时配置已落盘: %s", RUNTIME_FILE)
    except OSError:
        logger.exception("运行时配置写入失败: %s", RUNTIME_FILE)


def load() -> None:
    """进程启动时调用：先记录启动值，再回放磁盘上的覆盖项。"""
    with _lock:
        for f in FIELDS:
            _boot_values[f.key] = _raw_value(f.key)

        # 迁移：旧版 JSON 覆盖文件 → TOML 格式（兼容升级）。
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
                    logger.info("已将旧版 JSON 覆盖文件迁移为 TOML 格式并删除旧文件: %s", RUNTIME_FILE)
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

        data = _read_toml_file(RUNTIME_FILE)
        if not data:
            return

        # 容错：字段表已移除的项（如 broker_api）直接跳过，
        # 避免单个未知键导致整份覆盖文件回放失败，连 basic_auth 也一起失效。
        unknown = [k for k in data if k not in FIELD_MAP]
        for k in unknown:
            logger.warning("运行时配置忽略未知项（已从字段表移除）：%s", k)
        known = {
            k: v for k, v in data.items()
            if k in FIELD_MAP and k not in _CLI_OVERRIDES
        }
        if _CLI_OVERRIDES:
            skipped = sorted(set(data) & set(_CLI_OVERRIDES))
            if skipped:
                logger.info(
                    "运行时配置回放跳过命令行已覆盖的项: %s", ", ".join(skipped)
                )
        if known:
            try:
                update(known, persist=False, allow_restart=True)
                logger.info("已回放运行时配置覆盖项: %s", ", ".join(known))
            except ConfigError as exc:
                logger.warning("运行时配置回放失败，已忽略: %s", exc)


# --------------------------------------------------------------------------
# 完整模板（带中文注释）
# --------------------------------------------------------------------------
def _materialize_full() -> str:
    """生成包含全部配置项与中文注释的 TOML 模板文本。

    非密文字段写出当前默认值（方便查看）；密文字段（basic_auth 等）写出
    默认值，``secret_key`` 因每次启动随机，只给注释示例、不写生效行。
    """
    out = []
    out.append("# ===========================================================")
    out.append("# FlowerUI 运行时配置（TOML 格式）")
    out.append("# -----------------------------------------------------------")
    out.append("# 规则：")
    out.append("#   * 每行 KEY = VALUE；系统保存时只更新对应行，不覆盖你的注释/手工键")
    out.append('#   * 列表/字典以 TOML 语法书写：cors_origins = ["http://127.0.0.1:5556"]')
    out.append('#   * 字典示例：task_routes = { "tasks.send_email" = "emails" }')
    out.append('#   * 字符串含空格请用引号：db = "flower state.db"')
    out.append("#   * 修改后需重启的配置，在界面点「重启系统」即可生效")
    out.append("# ===========================================================")
    out.append("")

    for g in GROUPS:
        out.append(f"# ---- {g['label']}（{g['desc']}） ----")
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
            out.append(f"# {f.label}：{desc}  [{'; '.join(meta)}]")
            if f.todo:
                out.append(f"# ⚠ 待完善：{f.todo_reason}")

            if f.key == "secret_key":
                # 随机密钥不落到模板明文，仅给注释示例
                out.append("# secret_key = （留空则每次启动自动生成随机 JWT 密钥，推荐保持留空）")
                continue
            default_val = _raw_value(f.key)
            if default_val is None:
                # 可选配置（如 result_backend）默认不启用：只给注释示例，
                # 不写生效行。否则空字符串会被 Celery 当成「已配置但为空」，
                # 触发 NotImplementedError: No result backend is configured.
                out.append(f"# {f.key} = \"...\"  # 非必须，留空/不配置即不启用")
            else:
                out.append(f"{f.key} = {_toml_value(default_val)}")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def materialize() -> Dict[str, Any]:
    """把当前所有配置连同注释整体重写为 TOML 文件（「生成完整配置」按钮用）。

    与日常保存不同，这里是用户主动触发的「重新排版 + 加注释」。
    为遵循「不覆盖手工配置」原则：
    - FIELDS 中的键写出**当前生效值**（而非默认值），保留你已改的内容；
    - 文件中出现的、系统未管理的手工键（如 FLOWER_ 前缀或其它键）原样保留。
    """
    with _lock:
        RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)

        preserved: Dict[str, Any] = {}
        if RUNTIME_FILE.exists():
            try:
                with RUNTIME_FILE.open("r", encoding="utf-8") as f:
                    existing = toml.load(f) or {}
                for k, v in existing.items():
                    if isinstance(k, str) and k.strip() and k.strip() not in FIELD_MAP:
                        preserved[k.strip()] = v
            except Exception:
                preserved = {}

        content = _materialize_full()
        if preserved:
            # 手工添加的键追加到文件末尾，非系统托管
            for k, v in preserved.items():
                content += f"{k} = {_toml_value(v)}\n"
            content = content.rstrip() + "\n"

        try:
            with RUNTIME_FILE.open("w", encoding="utf-8") as f:
                f.write(content)
        except OSError:
            logger.exception("运行时配置写入失败: %s", RUNTIME_FILE)
            return {"ok": False, "message": "运行时配置写入失败"}

        logger.info("已生成完整配置模板: %s", RUNTIME_FILE)
        return {"ok": True, "message": "已生成完整配置模板", "runtime_file": str(RUNTIME_FILE)}


# --------------------------------------------------------------------------
# 子进程回放：uvicorn --reload / --workers 会重新导入本模块，此时命令行参数
# 本身不在子进程里，只能靠环境变量把覆盖项带过来。主进程由 flowerui/cli.py
# 显式调用 set_cli_overrides()，这里只负责兜底，两者都是幂等的。
# --------------------------------------------------------------------------
def _apply_cli_overrides_from_env() -> None:
    raw = os.environ.get(CLI_OVERRIDES_ENV)
    if not raw:
        return
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("忽略无法解析的 %s", CLI_OVERRIDES_ENV)
        return
    if isinstance(data, dict) and data:
        try:
            set_cli_overrides(data)
        except ConfigError as exc:
            logger.warning("命令行配置覆盖未生效: %s", exc)


_apply_cli_overrides_from_env()
