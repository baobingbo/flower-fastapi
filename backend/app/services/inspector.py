"""Worker 探测器：异步执行 celery inspect，缓存结果。"""
from __future__ import annotations

import asyncio
import collections
import logging
import time
from functools import partial
from typing import Any, Dict, List, Optional

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

    def __init__(self, capp, timeout: float, offline_timeout: float = 300.0):
        self.capp = capp
        self.timeout = timeout
        self.offline_timeout = offline_timeout  # 无心跳超过此秒数视为离线
        self.workers: Dict[str, Dict[str, Any]] = collections.defaultdict(dict)
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

    # ------------------------------------------------------------------
    def cleanup_offline(self) -> int:
        """清理超过 N 分钟无心跳的幽灵 worker，返回清理数量。"""
        now = time.time()
        to_remove = []
        for workername, info in self.workers.items():
            last_seen = info.get("timestamp", 0)
            if now - last_seen > self.offline_timeout:
                to_remove.append(workername)
        
        for workername in to_remove:
            last_seen = self.workers[workername].get("timestamp", 0)
            del self.workers[workername]
            logger.info("清理幽灵 worker: %s (最后活跃 %.0fs 前)", 
                       workername, now - last_seen)
        
        return len(to_remove)
