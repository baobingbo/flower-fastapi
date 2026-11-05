"""Worker 探测器：异步执行 celery inspect，缓存结果。"""
from __future__ import annotations

import asyncio
import collections
import logging
import time
from functools import partial
from typing import Any, Dict, List, Optional, Set

from ..core.celery_app import mask_url_password
from ..core.config import settings

logger = logging.getLogger(__name__)


class Inspector:
    methods = (
        "stats",
        "active_queues",
        "registered",
        "scheduled",
        "active",
        "reserved",
        "revoked",
        "conf",
    )

    def __init__(self, capp, timeout: float):
        self.capp = capp
        self.timeout = timeout
        self.workers: Dict[str, Dict[str, Any]] = collections.defaultdict(dict)
        # 归属当前 broker_url 的 worker 名（累积集合，不随离线/探测抖动删除）。
        # control inspect 的回执走按 db 隔离的队列，只有与监控端同一 broker/db
        # 的 worker 才会回包；而事件广播（Redis Pub/Sub）是服务端全局的，其它
        # broker/db 的 worker 心跳也会混进 state。用「曾被 inspect 到」作为归属
        # 判据，供上层隔离非配置 broker 的 worker。
        self.known_workers: Set[str] = set()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    async def inspect(self, workername: Optional[str] = None) -> None:
        """并发执行全部 inspect 方法。"""
        loop = asyncio.get_running_loop()
        tasks = [
            loop.run_in_executor(None, partial(self._inspect, m, workername))
            for m in self.methods
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for method, res in zip(self.methods, results):
            if isinstance(res, Exception):
                logger.debug("inspect %s 失败: %s", method, res)
                continue
            if not res:
                continue
            for worker, response in res.items():
                if response is not None:
                    self._on_update(worker, method, response)

    def _inspect(self, method: str, workername: Optional[str]):
        destination = [workername] if workername else None
        inspect = self.capp.control.inspect(
            timeout=self.timeout, destination=destination
        )
        start = time.time()
        result = (
            inspect.active(safe=True) if method == "active" else getattr(inspect, method)()
        )
        logger.debug("inspect %s 耗时 %.2fs", method, time.time() - start)
        if result is None or "error" in result:
            return None
        return result

    def _on_update(self, workername: str, method: str, response: Any) -> None:
        # 收到回包即证明该 worker 与监控端处于同一 broker（回执通道按 db 隔离）。
        self.known_workers.add(workername)
        if method == "conf" and isinstance(response, dict) and "error" in response:
            # worker 端 celery 的 Conf.table() 会用 kombu maybe_sanitize_url
            # 消毒 broker_url，而多节点哨兵 URL（sentinel://h:26379;sentinel:...）
            # 的 netloc 含 ";sentinel:"，url_to_parts 解析端口时抛 ValueError，
            # 错误体经 control 通道回传。这里丢弃错误体，改存监控端视角的
            # broker 概要，避免前端 worker 详情页渲染出一行 error。
            response = {
                # 该 dict 会经 /api/worker/{name} 返回前端，密码段必须脱敏
                "broker_url": mask_url_password(settings.broker_url),
                "note": "worker 端 conf 采集失败（多哨兵 URL 无法被 celery/kombu "
                        "的配置消毒逻辑解析），此处展示监控端视角",
            }
        info = self.workers[workername]
        info[method] = response
        info["timestamp"] = time.time()

    # ------------------------------------------------------------------
    def get(self, workername: str) -> Optional[Dict[str, Any]]:
        return self.workers.get(workername)

    def active_queue_names(self, capp) -> List[str]:
        """收集所有 worker 正在消费的队列名；无数据时回退到 Celery 配置。"""
        queues = set()
        for _, info in self.workers.items():
            for queue in info.get("active_queues") or []:
                if queue.get("name"):
                    queues.add(queue["name"])
        if not queues:
            try:
                queues = {capp.conf.task_default_queue or "celery"}
                for q in capp.conf.task_queues or []:
                    if getattr(q, "name", None):
                        queues.add(q.name)
            except Exception:
                queues = {"celery"}
        return sorted(queues)
