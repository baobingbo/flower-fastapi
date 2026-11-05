"""Celery 应用工厂与连接探测。"""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse

import celery

from .config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 兼容老版本 Redis（如 Windows 移植版 5.x 及更早，不支持 RESP3 的 HELLO 握手）：
# redis-py 8.x 默认使用 RESP3 协议，连接时会发送 HELLO 命令协商，而老 Redis
# 会返回 "unknown command 'HELLO'" 导致 broker 连接失败、FlowerUI 误判 broker
# 不可达并自动降级为演示模式。这里版本感知地把默认协议回退到 RESP2
# （所有现代 Redis 也兼容 RESP2），一劳永逸覆盖探测/事件消费者/inspect。
# ---------------------------------------------------------------------------
def _patch_redis_default_resp2() -> None:
    try:
        import redis as _redis

        parts = _redis.__version__.split(".")[:2]
        major, minor = (int(x) for x in parts)
        # redis-py 8.x 默认 RESP3 并会自动启用"维护通知"，而老版本 Redis
        # （如 Windows 移植版 5.x 及更早，HELLO 命令在 6.0 才引入）会拒绝连接。
        # 从源头把默认协议回退到 RESP2（所有现代 Redis 也兼容 RESP2），
        # 同时避免 ConnectionPool 因 protocol=3 而自动启用维护通知。
        if (major, minor) >= (8, 0):

            def _make_init(orig_init):
                def _init(self, *args, **kwargs):
                    if kwargs.get("protocol") is None:
                        kwargs["protocol"] = 2
                    return orig_init(self, *args, **kwargs)

                return _init

            for _cls in (_redis.Redis, _redis.Connection, _redis.ConnectionPool):
                _cls.__init__ = _make_init(_cls.__init__)
    except Exception as exc:  # pragma: no cover - 取决于环境
        logger.debug("redis RESP2 兼容补丁未生效: %s", exc)


_patch_redis_default_resp2()


_capp: Optional[celery.Celery] = None
_capp_signature: Optional[tuple] = None


def _current_signature() -> tuple:
    """影响 Celery app 构建的配置签名。

    ``main.py`` 在导入期就会实例化 ServiceManager（间接调用本工厂），
    而 ``runtime_config.load()`` 的配置回放发生在 lifespan 启动阶段——
    若不在签名变化时重建 app，探测/inspect/事件会一直使用导入期按
    **默认配置**建出的陈旧连接（典型症状：broker 明明配了哨兵或密码，
    却按默认 ``redis://127.0.0.1:6379/0`` 去连，报 Authentication
    required 并误降级为演示模式）。
    """
    return (
        settings.broker_url,
        tuple(sorted((settings.broker_transport_options or {}).items())),
        settings.result_backend,
    )


def get_celery_app() -> celery.Celery:
    global _capp, _capp_signature
    sig = _current_signature()
    if _capp is None or _capp_signature != sig:
        _capp = celery.Celery(broker=settings.broker_url)
        conf = {"broker_connection_retry_on_startup": True}
        if settings.broker_transport_options:
            conf["broker_transport_options"] = settings.broker_transport_options
        if settings.result_backend:
            conf["result_backend"] = settings.result_backend
            # kombu 的 SentinelBackend 与 broker 侧一样要求 master_name。
            # 只配 broker_transport_options 而不给 result backend 传同一份选项时，
            # 结果后端会以 service_name=None 去问哨兵，抛
            # "MasterNotFoundError: No master found for None"，使
            # /api/task/send-task/*、/api/task/result/* 在约 19s 重试后 500。
            # examples/tasks.py 的直连模式早已这样处理，这里保持一致。
            if (
                urlparse(settings.result_backend).scheme == "sentinel"
                and settings.broker_transport_options
            ):
                conf["result_backend_transport_options"] = dict(
                    settings.broker_transport_options
                )
        _capp.conf.update(conf)
        try:
            _capp.loader.import_default_modules()
        except Exception as exc:  # pragma: no cover - 取决于用户工程
            logger.debug("import_default_modules failed: %s", exc)
        _capp_signature = sig
        if sig != _current_signature():  # pragma: no cover - 防御并发改写
            logger.debug("Celery app 重建期间配置发生变化，将在下次获取时再建")
    return _capp


_URL_PASSWORD_RE = re.compile(r"(://[^:@/?#]*:)([^@]+)(@)")


def mask_url_password(url: str) -> str:
    """把 URL 中的密码段替换为 ******（无密码原样返回），仅用于展示。

    兼容 redis://user:pass@host、redis://:pass@host 与
    sentinel://:pass@h1:26379;h2:26379/master 等形态。
    """
    if not url or "://" not in url or "@" not in url:
        return url
    return _URL_PASSWORD_RE.sub(r"\1******\3", url)


def broker_uri(include_password: bool = False) -> str:
    """返回 broker 连接串，失败时回退到配置原值。

    哨兵模式直接返回原始配置值：kombu 的 ``as_uri()`` 对多哨兵 URL 会
    退化（只剩第一个节点且丢失 db），探测与展示都应以原串为准。

    展示安全：``include_password=False``（默认）时无论哪个分支都把密码段
    脱敏为 ******——此前哨兵分支与异常回退分支会原文返回，导致
    /api/system（运行环境页）、总览等处泄露明文密码。
    ``include_password=True`` 仍返回原文，供真实建连（如 broker_queues）使用。
    """
    if urlparse(settings.broker_url).scheme == "sentinel":
        url = settings.broker_url
    else:
        try:
            url = get_celery_app().connection().as_uri(include_password=include_password)
        except Exception:
            url = settings.broker_url
    return url if include_password else mask_url_password(url)


def transport_driver() -> Optional[str]:
    try:
        return getattr(get_celery_app().connection().transport, "driver_type", None)
    except Exception:
        return None


def ping_broker(timeout: float = 2.0) -> bool:
    """检测 broker 是否真实可用，用于自动决定是否进入演示模式。"""
    try:
        conn = get_celery_app().connection(connect_timeout=timeout)
        conn.ensure_connection(max_retries=0, timeout=timeout)
        conn.release()
        return True
    except Exception as exc:
        logger.warning("Broker 不可达 (%s): %s", mask_url_password(settings.broker_url), exc)
        return False
