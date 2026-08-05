"""FlowerUI 真实模式演示用的 Celery 任务定义。

与 docker-compose.yml 中注释掉的示例 worker 保持一致：以 `celery -A tasks worker` 启动。
broker / result backend 读取顺序：FLOWER_BROKER_URL / CELERY_BROKER_URL（默认 redis://127.0.0.1:6379/0），
result 同理默认 redis://127.0.0.1:6379/1。
"""
from __future__ import annotations

import os
import random
import time

from celery import Celery


# ---------------------------------------------------------------------------
# 兼容老版本 Redis（如 Windows 移植版 5.x 及更早，不支持 RESP3 的 HELLO 握手）。
# redis-py 8.x 默认 RESP3，连接时会发送 HELLO 导致握手失败。回退默认协议到 RESP2。
# 与 FlowerUI 后端 backend/app/core/celery_app.py 中的修复保持一致。
# ---------------------------------------------------------------------------
def _patch_redis_default_resp2() -> None:
    try:
        import redis as _redis

        major, minor = (int(x) for x in _redis.__version__.split(".")[:2])
        if (major, minor) >= (8, 0):

            def _make_init(orig_init):
                def _init(self, *a, **kw):
                    if kw.get("protocol") is None:
                        kw["protocol"] = 2
                    return orig_init(self, *a, **kw)

                return _init

            for _cls in (_redis.Redis, _redis.Connection, _redis.ConnectionPool):
                _cls.__init__ = _make_init(_cls.__init__)
    except Exception:
        pass


_patch_redis_default_resp2()


BROKER = (
    os.getenv("FLOWER_BROKER_URL")
    or os.getenv("CELERY_BROKER_URL")
    or "redis://127.0.0.1:6379/0"
)
BACKEND = (
    os.getenv("FLOWER_RESULT_BACKEND")
    or os.getenv("CELERY_RESULT_BACKEND")
    or "redis://127.0.0.1:6379/1"
)

app = Celery("flowerui_demo", broker=BROKER, backend=BACKEND)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_routes={
        "tasks.send_email": {"queue": "emails"},
        "tasks.resize_image": {"queue": "reports"},
    },
)


@app.task(name="tasks.send_email")
def send_email(to, template="welcome"):
    """模拟发送邮件，随机耗时 0.5~2s。"""
    time.sleep(random.uniform(0.5, 2.0))
    return {"to": to, "template": template, "status": "sent"}


@app.task(name="tasks.resize_image")
def resize_image(path, size=128):
    """模拟图片处理，随机耗时 1~3s。"""
    time.sleep(random.uniform(1.0, 3.0))
    return f"resized {path} -> {size}px"


@app.task(name="tasks.custom_job")
def custom_job(a, b):
    """普通计算任务。"""
    time.sleep(random.uniform(0.2, 1.5))
    return a + b


@app.task(name="tasks.flaky")
def flaky():
    """约 60% 概率失败，用于演示 FAILURE 状态。"""
    if random.random() < 0.6:
        raise ValueError("模拟任务失败：下游服务超时")
    return "ok"


@app.task(name="tasks.long_task", bind=True)
def long_task(self, steps=8):
    """长时间任务，过程中上报 PROGRESS 状态。"""
    for i in range(steps):
        time.sleep(1.5)
        self.update_state(state="PROGRESS", meta={"step": i + 1, "total": steps})
    return {"steps": steps, "done": True}


@app.task(name="tasks.retry_demo", bind=True, max_retries=1)
def retry_demo(self):
    """先失败一次再重试，用于演示 RETRIED 状态。"""
    if self.request.retries < 1:
        raise self.retry(countdown=1, exc=ValueError("先失败一次再重试"))
    return "重试后成功"
