"""单独验证 Redis 连接，复现 manager.startup 里的 run_in_executor 写法。

用法：
    cd backend
    python tests/test_redis_connection.py
    # 自定义 broker：
    FLOWER_BROKER_URL=redis://127.0.0.1:6379/0 python tests/test_redis_connection.py

目的：
    1. 确认老版本 Redis（不支持 RESP3 的 HELLO）在 RESP2 补丁后能否连上；
    2. 对比「主线程同步调用 ping_broker」与「asyncio run_in_executor 调用 ping_broker」
       —— 即完全复现 backend/flowerui/services/manager.py 的 startup() 那段逻辑，
       看是否存在线程池场景下连接异常 / 死锁 / 被吞异常。
"""
import os
import sys
import time
import asyncio
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# 默认指向本地 6379（用户已手动启动的 Redis）
os.environ.setdefault("FLOWER_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("FLOWER_RESULT_BACKEND", "redis://localhost:6379/1")

BROKER = os.environ["FLOWER_BROKER_URL"]
RESULT = os.environ["FLOWER_RESULT_BACKEND"]
print("="*64)
print("Redis 连接独立诊断")
print(f"  FLOWER_BROKER_URL    = {BROKER}")
print(f"  FLOWER_RESULT_BACKEND= {RESULT}")
print("="*64)


def section(title: str) -> None:
    print("\n" + "-" * 64)
    print(title)
    print("-" * 64)


# import 即触发 _patch_redis_default_resp2()（RESP2 兜底补丁）
from flowerui.core.celery_app import get_celery_app, ping_broker, broker_uri  # noqa: E402


# ----------------------------------------------------------------------
# 1) redis-py 直连（最直接，绕开 celery/kombu 链路）
# ----------------------------------------------------------------------
section("1) redis-py 直连 PING（RESP2 补丁已生效）")
try:
    import redis
    print(f"  redis-py 版本: {redis.__version__}")
    t0 = time.time()
    r = redis.Redis.from_url(BROKER, socket_connect_timeout=3)
    alive = r.ping()
    ver = r.info("server").get("redis_version")
    print(f"  -> ping={alive}  redis_version={ver}  ({time.time()-t0:.3f}s)")
except Exception as exc:
    print(f"  -> FAIL: {exc!r}")
    traceback.print_exc()


# ----------------------------------------------------------------------
# 2) 通过 Celery(kombu) 连接（FlowerUI 实际使用的链路）
# ----------------------------------------------------------------------
section("2) kombu capp.connection().ensure_connection()")
try:
    capp = get_celery_app()
    t0 = time.time()
    conn = capp.connection(connect_timeout=3)
    conn.ensure_connection(max_retries=0, timeout=3)
    print(f"  -> OK  ({time.time()-t0:.3f}s)")
    conn.release()
except Exception as exc:
    print(f"  -> FAIL: {exc!r}")
    traceback.print_exc()


# ----------------------------------------------------------------------
# 3) 主线程同步调用 ping_broker（作为基线）
# ----------------------------------------------------------------------
section("3) ping_broker() 主线程同步调用")
t0 = time.time()
try:
    ok = ping_broker(2.0)
    print(f"  -> {ok}  ({time.time()-t0:.3f}s)")
except Exception as exc:
    print(f"  -> EXC: {exc!r}")
    traceback.print_exc()


# ----------------------------------------------------------------------
# 4) 完全复现 manager.startup 的写法：
#      broker_alive = await loop.run_in_executor(None, ping_broker, 2.0)
# ----------------------------------------------------------------------
section("4) asyncio run_in_executor(ping_broker, 2.0) —— 复现 manager.startup")


async def _repro_startup_line() -> None:
    loop = asyncio.get_running_loop()
    t0 = time.time()
    try:
        broker_alive = await loop.run_in_executor(None, ping_broker, 2.0)
        print(f"  -> broker_alive={broker_alive}  ({time.time()-t0:.3f}s)")
    except Exception as exc:
        print(f"  -> EXC: {exc!r}")
        traceback.print_exc()


asyncio.run(_repro_startup_line())

print("\n" + "=" * 64)
print(f"broker_uri() -> {broker_uri()}")
print("=" * 64)
