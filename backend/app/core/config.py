"""全局配置。字段与 flower 原生命令行参数一一对齐。"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_RUNTIME_BUCKETS = [
    0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5,
    0.75, 1.0, 2.5, 5.0, 7.5, 10.0, 30.0, 60.0, 300.0, 600.0,
]



class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FLOWER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 服务 ----------
    host: str = "0.0.0.0"
    port: int = 5555
    debug: bool = False
    url_prefix: str = ""
    cors_origins: List[str] = []

    # ---------- Celery ----------
    # 注意：本地 Redis 用 127.0.0.1 而非 localhost。
    # 实测 Windows 移植版 Redis + redis-py 8.x 下，localhost 会先尝试 IPv6(::1)
    # 超时再回退 IPv4，单次连接额外耗时 ~2s；inspect 8 个方法叠加会卡 17s+。
    # 127.0.0.1 直连仅 ~10ms，是真实模式不卡顿的关键。
    broker_url: str = "redis://127.0.0.1:6379/0"
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
    # basic_auth 字段已废弃，改用 SQLite 用户存储
    basic_auth: List[str] = []          # 保留字段以兼容旧配置
    basic_auth_enabled: bool = False    # 保留字段以兼容旧配置
    auth: str = ""                      # 允许登录的邮箱正则（OAuth）
    auth_provider: Optional[str] = None
    oauth2_key: Optional[str] = None
    oauth2_secret: Optional[str] = None
    oauth2_redirect_uri: Optional[str] = None
    # 通用 OAuth2 授权码流程（GitHub / GitLab / OIDC 等任意兼容提供方），URL 全部可配
    oauth2_provider: str = "OAuth"        # 登录页第三方登录按钮上的提供方显示名
    oauth2_authorize_url: str = ""        # 授权端点 URL（authorization endpoint）
    oauth2_token_url: str = ""            # 令牌端点 URL（token endpoint）
    oauth2_userinfo_url: str = ""         # 用户信息端点 URL（userinfo，空则从令牌响应取用户名）
    oauth2_client_id: str = ""            # client_id，非空即启用 OAuth2 登录
    oauth2_client_secret: str = ""        # client_secret
    oauth2_scope: str = ""                # 授权 scope，空为提供方默认
    oauth2_username_claim: str = "login"   # userinfo 中用户名字段名
    oauth2_flower_compatible: bool = False  # 兼容 Flower OAuth2 格式
    secret_key: str = secrets.token_urlsafe(32)
    token_expire_minutes: int = 60 * 24
    token_version: int = 0
    legacy_basic_auth_enabled: bool = False
    password_min_length: int = 8
    password_require_upper: bool = False
    password_require_digit: bool = False
    password_require_special: bool = False
    
    # ---------- SQLite 数据库路径 ----------
    db_path: str = "flowerui.db"

    # ---------- 指标 ----------
    task_runtime_metric_buckets: List[float] = DEFAULT_RUNTIME_BUCKETS

    # ---------- 历史归档 ----------
    history_enabled: bool = False
    history_db_path: str = "flowerui_history.db"
    history_retention_days: int = 7

    # ---------- 告警 ----------
    alert_enabled: bool = False
    alert_webhook_url: str = ""
    alert_rules: str = ""

    # ---------- 演示模式 ----------
    # 无可用 broker 时启用，内置模拟集群，保证 UI 全功能可演示
    mock: bool = False
    mock_workers: int = 4
    mock_seed_tasks: int = 260

    # ---------- 鉴权 ----------
    # 新鉴权模型：SQLite 用户库是唯一凭据来源（初始 admin 用户始终存在），
    # 因此默认开启鉴权；纯演示场景可用 FLOWER_AUTH_ENABLED=false 放开匿名访问。
    auth_enabled: bool = True

    @field_validator("basic_auth", "cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("["):
                return v
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    @model_validator(mode="before")
    @classmethod
    def _parse_task_routes(cls, data: Any) -> Any:
        """允许通过 FLOWER_TASK_ROUTES（JSON）注入任务→队列映射。"""
        if isinstance(data, dict) and "task_routes" not in data:
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

    @field_validator("task_runtime_metric_buckets", mode="before")
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
    def inspect_timeout_seconds(self) -> float:
        return self.inspect_timeout / 1000.0

    @property
    def control_timeout_seconds(self) -> float:
        return self.control_timeout / 1000.0

    @property
    def task_columns_list(self) -> List[str]:
        return [c.strip() for c in self.tasks_columns.split(",") if c.strip()]


# backend 目录（app/core/config.py → 上溯三级到 backend/）
BACKEND_DIR = Path(__file__).resolve().parents[2]


def resolve_db_path(path: str) -> Path:
    """相对路径锚定到 backend 目录，避免受启动 CWD 影响。"""
    p = Path(path)
    return p if p.is_absolute() else (BACKEND_DIR / p)


# 全局settings实例
settings = Settings()
