"""触发后端自身重启。

设计要点
--------
某些配置（监听地址/端口、CORS、持久化、认证、演示模式、事件采集等）
改动后必须重启进程才能生效。这里通过执行后端专属的 ``manage.sh``
脚本来重启后端服务：

- 脚本先停止已运行的后端（端口 5555，按 uvicorn 命令行特征精确定位，
  不会误杀 celery worker）
- 然后以开发模式（--reload）重新启动后端
- 日志输出到 ``backend/logs/uvicorn_*.log``

``backend/manage.sh`` 支持参数：
- ``--mock``：启用模拟模式
- ``--clean``：重启并清理日志文件

环境变量 ``FLOWER_RESTART_SCRIPT`` 可自定义脚本路径，默认使用 backend
目录下的 ``manage.sh``（自根 manage.sh 拆分的后端专属版本）。
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time

logger = logging.getLogger("flowerui.restart")

# 重启脚本路径（可通过环境变量覆盖）：
# 本文件位于 backend/app/services/，上溯两级即 backend/manage.sh
RESTART_SCRIPT = os.environ.get(
    "FLOWER_RESTART_SCRIPT",
    os.path.join(os.path.dirname(__file__), "..", "..", "manage.sh")
)


def describe_restart_command() -> dict:
    """返回将要用于重启的脚本路径，便于调试与前端展示。"""
    return {"script": RESTART_SCRIPT}


def restart_later(delay: float = 1.2) -> None:
    """在后台延迟后执行重启脚本，使运行时配置变更生效。

    延迟是为了让调用方（前端）先收到 HTTP 200 响应，再真正重启服务，
    否则连接在脚本启动瞬间被掐断，前端拿不到回包。
    """

    def _run() -> None:
        try:
            logger.info("准备重启 FlowerUI 服务（执行脚本: %s）", RESTART_SCRIPT)
            time.sleep(delay)
            # 执行重启脚本（后台运行，不阻塞）
            # 显式传入 `restart` 子命令，等价于 dev：先停后起
            # 后端服务，不依赖 manage.sh 的默认 fallthrough。
            subprocess.Popen(
                ["bash", RESTART_SCRIPT, "restart"],
                cwd=os.path.dirname(RESTART_SCRIPT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            logger.error("重启脚本未找到: %s", RESTART_SCRIPT)
        except Exception:  # noqa: BLE001 - 重启失败必须留下痕迹
            logger.exception("后端重启失败")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
