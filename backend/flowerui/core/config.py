"""全局配置。字段与 flower 原生命令行参数一一对齐。

配置来源（按优先级从低到高）：
1. 静态默认配置：``flowerui-settings.toml``，**分层回退**——项目执行目录下的优先，
   没有则回退到包内随源码 / wheel 分发的模板（pip 安装后通常在 site-packages/flowerui/ 旁，
   往往不存在，于是回退到代码默认值）；
2. 系统环境变量：``FLOWER_<KEY>`` 前缀（如 ``FLOWER_BROKER_URL``），可覆盖 TOML 值；
3. 默认值（无任何来源时生效）。

不再依赖 .env 文件（pydantic-settings 不解析 TOML，也不支持 py3.7），
改为由 pydantic 1.10 自己的 ``BaseSettings`` 托管，文件驱动层自行实现。
"""
from __future__ import annotations

import json
import os
import secrets
from typing import Any, Dict, List, Optional

import toml
from pydantic import BaseSettings, Field, root_validator, validator

from .. import paths

# 仅用于「分节写法」体检：TOML 的 table 与 inline table 解析后都是 dict，
# 因此不做自动展平，只在遇到历史分节名时明确告警，避免静默丢弃配置。
_TOML_SECTION_NAMES = {
    "service", "celery", "routing", "capacity", "persistence",
    "display", "auth", "demo", "broker", "worker", "monitor",
}

DEFAULT_RUNTIME_BUCKETS = [
    0.005, 0.01, 0.025, 0.05, 0.075, 1.0, 2.5, 5.0, 7.5, 10.0, 30.0, 60.0, 300.0, 600.0,
]

# 静态默认配置（flowerui-settings.toml）采用「分层回退」：
#   项目执行目录下的 flowerui-settings.toml 优先；没有则回退到包内随源码 / wheel
#   分发的模板（源码模式在 backend/，pip 安装后在 site-packages/flowerui/ 旁，通常不存在）。
# 运行时覆盖配置 flowerui.runtime.toml 始终按「当前工作目录」落盘（见 paths.runtime_file）。
# 两者语义不同，勿混用。具体解析见 paths.settings_toml()。


def _load_toml(path: str) -> Dict[str, Any]:
    """读 TOML 配置文件，不存在或解析失败时返回 ``{}``（不中断启动）。

    期望扁平布局（顶层 ``KEY = VALUE``），因为返回值会直接被
    ``Settings(**sources)`` 消费；分节（``[service]`` 等）会被
    ``extra="ignore"`` 静默丢弃，故这里显式告警。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = toml.load(f)
    except FileNotFoundError:
        return {}  # 未配置项目文件时，后续回退到环境变量和默认值
    except Exception as exc:
        print(
            "WARNING: 无法解析 %s，已忽略整个文件，配置将回退到 "
            "FLOWER_* 环境变量与代码默认值 (%s)" % (path, exc)
        )
        return {}

    sections = [
        k for k, v in data.items()
        if k in _TOML_SECTION_NAMES and isinstance(v, dict)
    ]
    if sections:
        print(
            "WARNING: %s 使用分节写法 %s；这些配置不会生效，"
            "请改为顶层 KEY = VALUE（参考文件头注释）" % (path, sections)
        )
    return data


def _load_env() -> Dict[str, Any]:
    """读 ``FLOWER_`` 前缀的环境变量，键名转小写，用于覆盖 TOML。"""
    env_cfg = {}
    for key, value in os.environ.items():
        if key.startswith("FLOWER_"):
            env_cfg[key[len("FLOWER_"):].lower()] = value
    return env_cfg


def _sources() -> Dict[str, Any]:
    """合并所有配置源（TOML 文件是低优先级，环境变量是最高优先级）"""
    sources = _load_toml(str(paths.settings_toml()))
    sources.update(_load_env())
    return sources


class Settings(BaseSettings):
    class Config:
        env_prefix = ""       # 不在 BaseSettings 环境变量扩展前缀，这里我们手动合并
        extra = "ignore"      # 忽略漏掉的未知 key，不对未知配置项改名

    # ---------- 服务 ----------
    host: str = "0.0.0.0"
    port: int = 5555
    debug: bool = False
    url_prefix: str = ""
    cors_origins: List[str] = ["*"]

    # ---------- Celery ----------
    # 注意：本地 Redis 用 127.0.0.1 而非 localhost。
    # 实测 Windows 移植版 Redis + redis-py 8.x 下，localhost 会先尝试 IPv6(::1)
    # 超时再回退 IPv4，单次连接额外耗时 ~2s；inspect 8 个方法叠加会卡 17s+。
    # 127.0.0.1 直连仅 ~10ms，是真实模式不卡顿的关键。
    broker_url: str = "redis://127.0.0.1:6379/0"
    # 哨兵模式必需：kombu SentinelTransport 要求 master_name。
    # 例：{"master_name": "mymaster"}；哨兵节点带密码时
    # {"sentinel_kwargs": {"password": "xxx"}}。
    broker_transport_options: Dict[str, Any] = Field(default_factory=dict)
    # 结果后端，非必须。不配（None）时 celery 只负责消息运输与任务控制，
    # 不提供结果查询（比如 ``wait=True`` 下发任务会抛 NotImplementedError）
    # 给任务结果保留一个结果存储，才配。示例（和 broker 同机不同 DB 号）：
    #   result_backend="redis://user:YOUR_PASSWORD@redis.example.com:6379/1"
    result_backend: Optional[str] = None
    broker_api: Optional[str] = None  # RabbitMQ management API
    inspect_timeout: float = 3000.0  # 毫秒
    # 远程控制命令（pool grow/shrink、add_consumer 等）等待 worker 回复的超时。
    # celery 默认仅 1 秒，单线程（--pool=solo）worker 正在跑任务时来不及回复，
    # 会被误判为"执行失败"，实际命令已经生效。这里放宽并允许通过环境变量调整。
    control_timeout: float = 5000.0  # 毫秒
    enable_events: bool = True

    # ---------- 任务路由（仅用于"下发任务"表单的队列预填） ----------
    # 演示项目 examples/tasks.py 中 task_routes 把 send_email→emails、resize_image→reports。
    # 可通过环境变量 FLOWER_TASK_ROUTES（JSON 字符串）注入，例如：
    #   FLOWER_TASK_ROUTES={"tasks.send_email":"emails","tasks.resize_image":"reports"}
    # 这样前端在"选择任务"时就能自动预填其默认队列，实现任务↔队列联动。
    task_default_queue: str = "celery"
    task_routes: Dict[str, str] = Field(default_factory=dict)

    # ---------- 状态容量 ----------
    max_workers: int = 5000
    max_tasks: int = 100000
    purge_offline_workers: Optional[int] = None

    # ---------- 持久化 ----------
    db: str = "flower.state"
    persistent: bool = False
    state_save_interval: int = 0  # 毫秒，0 表示关闭

    # ---------- 展示 ----------
    auto_refresh: bool = True
    natural_time: bool = False
    tasks_columns: str = (
        "name,uuid,state,args,kwargs,result,received,started,runtime,worker"
    )

    # ---------- 认证 ----------
    basic_auth: List[str] = []          # ["user:pass", ...]
    basic_auth_enabled: bool = False    # 登录凭证管理总开关
    auth: str = ""                      # 允许登录的邮箱正则（OAuth）
    auth_provider: Optional[str] = None
    oauth2_key: Optional[str] = None
    oauth2_secret: Optional[str] = None
    oauth2_redirect_uri: Optional[str] = None
    secret_key: str = secrets.token_urlsafe(32)
    token_expire_minutes: int = 60 * 24

    # ---------- 指标 ----------
    task_runtime_metric_buckets: List[float] = DEFAULT_RUNTIME_BUCKETS

    # ---------- 演示模式 ----------
    # 无可用 broker 时启用，内置模拟集群，保证 UI 全功能可演示
    mock: bool = False
    mock_workers: int = 4
    mock_seed_tasks: int = 260

    @validator("basic_auth", "cors_origins", "broker_transport_options",
               "task_routes", pre=True)
    @classmethod
    def _split_csv(cls, v: Any) -> Any:
        """空字符串、CSV 字符串、列表三种形态统一做强转。"""
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("["):
                return v
            return [x.strip() for x in v.split(",") if x.strip()]
        if isinstance(v, dict):
            return v
        return v

    @root_validator(pre=True)
    @classmethod
    def _parse_json_dicts(cls, data: Any) -> Any:
        """部分字段的 JSON 字符串转 dict，放在所有字段验证之前。"""
        if not isinstance(data, dict):
            return data
        for field in ("broker_transport_options", "task_routes"):
            value = data.get(field)
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, dict):
                        data = dict(data)
                        data[field] = parsed
                except (ValueError, TypeError):
                    pass
        return data

    @root_validator(pre=True)
    @classmethod
    def _parse_task_routes(cls, data: Any) -> Any:
        """允许通过环境变量 FLOWER_TASK_ROUTES（JSON）注入任务→队列映射。"""
        if not isinstance(data, dict):
            return data
        if "task_routes" not in data:
            raw = os.getenv("FLOWER_TASK_ROUTES")
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        data = dict(data)
                        data["task_routes"] = {str(k): str(v) for k, v in parsed.items()}
                except (ValueError, TypeError):
                    pass
        return data

    @validator("task_runtime_metric_buckets", pre=True)
    @classmethod
    def _split_floats(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return DEFAULT_RUNTIME_BUCKETS
            if v.startswith("["):
                return v
            return [float(x) for x in v.split(",") if x.strip()]
        return v

    @property
    def auth_enabled(self) -> bool:
        # 当 basic_auth_enabled=false 时，不使用 basic_auth 配置
        if not self.basic_auth_enabled:
            return False
        return bool(self.basic_auth or self.auth)

    @property
    def inspect_timeout_seconds(self) -> float:
        return self.inspect_timeout / 1000.0

    @property
    def control_timeout_seconds(self) -> float:
        return self.control_timeout / 1000.0

    @property
    def task_columns_list(self) -> List[str]:
        return [c.strip() for c in self.tasks_columns.split(",") if c.strip()]


settings = Settings(**_sources())
