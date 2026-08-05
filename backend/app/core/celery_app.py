"""Celery 应用工厂与连接探测。"""
from __future__ import annotations

import logging
from typing import Optional

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


def get_celery_app() -> celery.Celery:
    global _capp
    if _capp is None:
        _capp = celery.Celery(broker=settings.broker_url)
        conf = {"broker_connection_retry_on_startup": True}
        if settings.result_backend:
            conf["result_backend"] = settings.result_backend
        _capp.conf.update(conf)
        try:
            _capp.loader.import_default_modules()
        except Exception as exc:  # pragma: no cover - 取决于用户工程
            logger.debug("import_default_modules failed: %s", exc)
    return _capp


def broker_uri(include_password: bool = False) -> str:
    """返回 broker 连接串，失败时回退到配置原值。"""
    try:
        return get_celery_app().connection().as_uri(include_password=include_password)
    except Exception:
        return settings.broker_url


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
        logger.warning("Broker 不可达 (%s): %s", settings.broker_url, exc)
        return False
