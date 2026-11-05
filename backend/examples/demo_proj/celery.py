"""模拟的「第三方 Celery 项目」，用于验证 FlowerUI 的 P3 能力：

直接复用用户已有 Celery app 的 conf，无需在 FlowerUI 侧重复配置 broker。

关键：broker / result backend / transport options / 路由全部指向**非默认**地址，
这样 `celery -A examples.demo_proj.celery:app flowerui --dry-run` 应当显示出
被继承的注入值，而不是默认的 redis://127.0.0.1:6379/0。

真实地跑起来还需要一个可达的 Redis；这里只验证「配置自动继承」是否生效，
dry-run 不真正连接 broker，所以不需要 Redis 实例。
"""
from celery import Celery

app = Celery("third_party_demo")

app.conf.update(
    broker_url="redis://127.0.0.1:6399/3",
    result_backend="redis://127.0.0.1:6399/4",
    broker_transport_options={"master_name": "mymaster"},
    task_default_queue="demo_priority_queue",
    task_routes={
        "tasks.send_email": "emails",
        "tasks.resize_image": "reports",
    },
)

# 暴露 celery 别名，兼容 `celery -A examples.demo_proj.celery:celery`
celery = app

__all__ = ["app", "celery"]
