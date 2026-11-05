"""Broker 队列探针，覆盖 amqp / redis / rediss / redis+socket / sentinel。"""
from __future__ import annotations

import asyncio
import json
import logging
import numbers
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx

try:
    import redis as redis_lib
except ImportError:  # pragma: no cover
    redis_lib = None

logger = logging.getLogger(__name__)


class BrokerBase:
    def __init__(self, broker_url: str, *_, **__):
        purl = urlparse(broker_url)
        self.scheme = purl.scheme
        self.host = purl.hostname
        try:
            self.port = purl.port
        except ValueError:
            # 多哨兵 URL（sentinel://h1:26379;sentinel://h2:26379/0）整体
            # urlparse 后 netloc 含 ";"，port 无法转整数，交由子类按节点重解析
            self.port = None
        self.vhost = purl.path[1:] if purl.path else ""
        self.username = unquote(purl.username) if purl.username else purl.username
        self.password = unquote(purl.password) if purl.password else purl.password

    async def queues(self, names: List[str]) -> List[Dict[str, Any]]:
        raise NotImplementedError


class RabbitMQ(BrokerBase):
    def __init__(self, broker_url: str, http_api: Optional[str] = None, **__):
        super().__init__(broker_url)
        self.host = self.host or "localhost"
        self.port = 15672
        self.vhost = quote(self.vhost, "") or "/" if self.vhost != "/" else self.vhost
        self.username = self.username or "guest"
        self.password = self.password or "guest"
        if not http_api:
            http_api = (
                f"http://{self.username}:{self.password}@"
                f"{self.host}:{self.port}/api/{self.vhost}"
            )
        try:
            self.validate_http_api(http_api)
        except ValueError:
            logger.error("非法的 broker api 地址: %s", http_api)
        self.http_api = http_api

    @classmethod
    def validate_http_api(cls, http_api: str) -> None:
        url = urlparse(http_api)
        if url.scheme not in ("http", "https"):
            raise ValueError(f"Invalid http api schema: {url.scheme}")

    async def queues(self, names: List[str]) -> List[Dict[str, Any]]:
        url = urljoin(self.http_api, "queues/" + self.vhost)
        api_url = urlparse(self.http_api)
        username = unquote(api_url.username or "") or self.username
        password = unquote(api_url.password or "") or self.password
        try:
            async with httpx.AsyncClient(verify=False, timeout=3.0) as client:
                resp = await client.get(url, auth=(username, password))
        except Exception as exc:
            logger.error("RabbitMQ management API 调用失败: %s", exc)
            return []
        if resp.status_code != 200:
            logger.error("RabbitMQ management API 返回 %s", resp.status_code)
            return []
        try:
            info = json.loads(resp.text)
        except ValueError:
            return []
        return [x for x in info if x.get("name") in names]


class RedisBase(BrokerBase):
    DEFAULT_SEP = "\x06\x16"
    DEFAULT_PRIORITY_STEPS = [0, 3, 6, 9]

    def __init__(self, broker_url: str, *_, **kwargs):
        super().__init__(broker_url)
        if redis_lib is None:
            raise ImportError("需要安装 redis 库")
        self.redis = None
        broker_options = kwargs.get("broker_options") or {}
        self.priority_steps = broker_options.get(
            "priority_steps", self.DEFAULT_PRIORITY_STEPS
        )
        self.sep = broker_options.get("sep", self.DEFAULT_SEP)
        self.broker_prefix = broker_options.get("global_keyprefix", "")

    @staticmethod
    def _prepare_virtual_host(vhost) -> int:
        if not isinstance(vhost, numbers.Integral):
            if not vhost or vhost == "/":
                vhost = 0
            elif isinstance(vhost, str) and vhost.startswith("/"):
                vhost = vhost[1:]
            try:
                vhost = int(vhost)
            except ValueError as exc:
                raise ValueError(f"Database 必须是整数, 而非 {vhost}") from exc
        return vhost

    def _q_for_pri(self, queue: str, pri: int) -> str:
        if pri not in self.priority_steps:
            raise ValueError("Priority not in priority steps")
        return f"{queue}{self.sep}{pri}" if pri else queue

    def _queues_sync(self, names: List[str]) -> List[Dict[str, Any]]:
        stats = []
        for name in names:
            keys = [
                self.broker_prefix + self._q_for_pri(name, pri)
                for pri in self.priority_steps
            ]
            try:
                messages = sum(int(self.redis.llen(k)) for k in keys)
            except Exception as exc:
                logger.error("读取 Redis 队列 %s 失败: %s", name, exc)
                messages = 0
            stats.append({"name": name, "messages": messages})
        return stats

    async def queues(self, names: List[str]) -> List[Dict[str, Any]]:
        return await asyncio.get_running_loop().run_in_executor(
            None, self._queues_sync, names
        )


class Redis(RedisBase):
    def __init__(self, broker_url: str, *args, **kwargs):
        super().__init__(broker_url, *args, **kwargs)
        self.host = self.host or "localhost"
        self.port = self.port or 6379
        self.vhost = self._prepare_virtual_host(self.vhost)
        self.redis = self._get_redis_client()

    def _get_redis_client_args(self) -> Dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "db": self.vhost,
            "username": self.username,
            "password": self.password,
            "socket_connect_timeout": 2.0,
        }

    def _get_redis_client(self):
        return redis_lib.Redis(**self._get_redis_client_args())


class RedisSsl(Redis):
    def __init__(self, broker_url: str, *args, **kwargs):
        if "broker_use_ssl" not in kwargs:
            raise ValueError("rediss 需要提供 broker_use_ssl")
        self.broker_use_ssl = kwargs.get("broker_use_ssl") or {}
        super().__init__(broker_url, *args, **kwargs)

    def _get_redis_client_args(self) -> Dict[str, Any]:
        args = super()._get_redis_client_args()
        args["ssl"] = True
        if isinstance(self.broker_use_ssl, dict):
            args.update(self.broker_use_ssl)
        return args


class RedisSocket(RedisBase):
    def __init__(self, broker_url: str, *args, **kwargs):
        super().__init__(broker_url, *args, **kwargs)
        self.redis = redis_lib.Redis(
            unix_socket_path="/" + self.vhost, password=self.password
        )


class RedisSentinel(RedisBase):
    def __init__(self, broker_url: str, *args, **kwargs):
        super().__init__(broker_url, *args, **kwargs)
        broker_options = kwargs.get("broker_options") or {}
        # 解析全部哨兵节点：sentinel://h1:26379;sentinel://h2:26379;sentinel://h3:26379/0
        # 整体 urlparse 只能拿到第一段，这里按 ";" 拆分逐段解析
        nodes: List[tuple] = []
        db_text = None
        password = self.password
        for part in broker_url.split(";"):
            part = part.strip()
            if not part:
                continue
            p = urlparse(part)
            if not p.hostname:
                continue
            try:
                port = p.port or 26379
            except ValueError:
                port = 26379
            nodes.append((p.hostname, port))
            if p.path and p.path != "/":
                db_text = p.path.lstrip("/")  # db 允许写在任意一段
            if p.password and not password:
                password = unquote(p.password)
        if not nodes:
            nodes = [(self.host or "localhost", self.port or 26379)]
        master_name = broker_options.get("master_name")
        if not master_name:
            raise ValueError("Sentinel 模式必须配置 master_name")
        self.master_name = master_name
        # db 以 URL 中显式段为准，回退到 BrokerBase 解析出的 vhost
        self.vhost = self._prepare_virtual_host(
            db_text if db_text not in (None, "") else self.vhost
        )
        sentinel = redis_lib.sentinel.Sentinel(
            nodes,
            password=password,
            sentinel_kwargs=broker_options.get("sentinel_kwargs"),
        )
        self.redis = sentinel.master_for(
            self.master_name,
            db=self.vhost,
            socket_connect_timeout=broker_options.get(
                "socket_connect_timeout", 2.0
            ),
        )


def create_broker(broker_url: str, **kwargs) -> BrokerBase:
    scheme = urlparse(broker_url).scheme
    mapping = {
        "amqp": RabbitMQ,
        "amqps": RabbitMQ,
        "redis": Redis,
        "rediss": RedisSsl,
        "redis+socket": RedisSocket,
        "sentinel": RedisSentinel,
    }
    cls = mapping.get(scheme)
    if cls is None:
        raise NotImplementedError(f"不支持的 broker 类型: {scheme}")
    return cls(broker_url, **kwargs)
