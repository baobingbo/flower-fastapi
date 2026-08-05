"""向真实 broker 灌入一批任务，让 FlowerUI 真实模式立即有真实数据可看。

任务通过 examples/tasks.py 的同一个 Celery app 发送到 broker，
由 start_worker 启动的 worker 消费；worker 产生的事件被 FlowerUI 采集。

建议顺序：先启动 FlowerUI(真实模式) → 再启动 worker → 最后运行本脚本。

用法:
  ../.venv/Scripts/python.exe seed_tasks.py [数量，默认 120]
"""
from __future__ import annotations

import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tasks import (  # noqa: E402
    send_email,
    resize_image,
    custom_job,
    flaky,
    long_task,
    retry_demo,
)

TEMPLATES = ["welcome", "reset_password", "invoice", "newsletter", "alert"]
USERS = [f"user{random.randint(1, 999)}@example.com" for _ in range(30)]


def main(n: int = 120) -> None:
    broker = send_email.app.conf.broker_url
    print(f">> 计划发送 {n} 个任务到 broker ({broker})")
    for i in range(n):
        kind = random.choice(["email", "image", "job", "flaky", "long", "retry"])
        if kind == "email":
            send_email.delay(random.choice(USERS), random.choice(TEMPLATES))
        elif kind == "image":
            resize_image.delay(f"s3://bucket/img/{i}.jpg", random.choice([64, 128, 256, 512]))
        elif kind == "job":
            custom_job.delay(random.randint(1, 100), random.randint(1, 100))
        elif kind == "flaky":
            flaky.delay()
        elif kind == "long":
            long_task.delay(steps=random.randint(4, 10))
        elif kind == "retry":
            retry_demo.delay()
        # 稍微错开发送，制造持续的活动曲线，便于观察实时事件流
        if i % 10 == 9:
            time.sleep(0.3)

    # 再发几个未来才执行的（PENDING / ETA）任务
    for j in range(5):
        send_email.apply_async(
            args=[f"future{j}@example.com", "welcome"],
            countdown=random.randint(20, 90),
        )

    print(f">> 已发送 {n + 5} 个任务。稍后在 FlowerUI 的 Tasks / Dashboard 查看实时数据。")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 120)
