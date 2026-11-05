"""验证 Celery 事件流：复现 events.py 的 EventReceiver.capture() 核心逻辑。

目的：确认 FlowerUI 的 Events 消费者能否从 worker 收到 task 事件。
 - 若 capture() 抛异常 → 老 Redis 在事件交换声明/订阅上不兼容（根因在采集线程）
 - 若收不到事件但无异常 → worker 侧事件未发出 / 路由不匹配
 - 若收到事件 → 说明环境 OK，问题在 FlowerUI 的 Events 线程是否真正启动
"""
import os
import sys
import time
import threading
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

os.environ.setdefault("FLOWER_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("FLOWER_RESULT_BACKEND", "redis://localhost:6379/1")

from flowerui.core.celery_app import get_celery_app  # 触发 RESP2 补丁
from celery.events import EventReceiver

capp = get_celery_app()
print("="*64)
print("Celery 事件流诊断")
print(f"  flowerui.main      = {capp.main}")
print(f"  broker        = {capp.conf.broker_url}")
print("="*64)

collected = []
lock = threading.Lock()
capture_err = {}


def on_event(event):
    typ = event.get("type")
    with lock:
        collected.append(typ)
    print(f"  [EVENT] type={typ} worker={event.get('hostname')} "
          f"uuid={str(event.get('uuid'))[:8]}")


def capture():
    try:
        # 完全复现 events.py: run()
        with capp.connection() as conn:
            recv = EventReceiver(conn, handlers={"*": on_event}, app=capp)
            print("  EventReceiver.capture() 启动监听...")
            recv.capture(limit=None, timeout=None, wakeup=True)
    except Exception as exc:  # noqa: BLE001
        import traceback
        capture_err["err"] = repr(exc)
        print("  [capture 异常]")
        traceback.print_exc()


t = threading.Thread(target=capture, daemon=True)
t.start()
time.sleep(1.0)

# 开启 worker 事件上报 + 投递一个真实任务触发事件
try:
    capp.control.enable_events()
    print("  -> 已发送 enable_events 给 worker")
except Exception as exc:
    print("  enable_events 失败:", repr(exc))

try:
    res = capp.send_task("tasks.custom_job", args=["flow", 7], kwargs={"n": 3})
    print(f"  -> 已投递 tasks.custom_job, task_id={res.task_id}")
except Exception as exc:
    print("  send_task 失败:", repr(exc))

time.sleep(5.0)

with lock:
    print("\n" + "-" * 64)
    print("收到的事件类型统计:", dict(Counter(collected)))
    print("capture 异常:", capture_err.get("err", "无"))
    print("-" * 64)
