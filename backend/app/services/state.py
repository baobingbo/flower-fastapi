"""事件状态机：继承 celery.events.state.State，保持任务字段与 flower 完全一致。"""
from __future__ import annotations

import collections
import logging
import threading
from collections import Counter
from typing import Any, Dict, List, Optional

from celery.events.state import State

from .hub import hub
from .metrics import get_prometheus_metrics

logger = logging.getLogger(__name__)

# 用于前端趋势图的滚动时间序列
TIMELINE_MAX_POINTS = 720


class EventsState(State):
    """在 celery State 之上追加：每 worker 事件计数、Prometheus 指标、实时广播。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.counter = collections.defaultdict(Counter)
        self.metrics = get_prometheus_metrics()
        self.lock = threading.RLock()
        # 时间线：[{ts, succeeded, failed, received, started, retried, active}]
        self.timeline: collections.deque = collections.deque(
            maxlen=TIMELINE_MAX_POINTS
        )
        self._tick = Counter()

    # ------------------------------------------------------------------
    def event(self, event: Dict[str, Any]) -> None:  # noqa: C901
        with self.lock:
            super().event(event)

            worker_name = event.get("hostname", "")
            event_type = event.get("type", "")
            self.counter[worker_name][event_type] += 1
            self._tick[event_type] += 1

            if event_type.startswith("task-"):
                self._on_task_event(event, worker_name, event_type)

            if event_type == "worker-online":
                self.metrics.worker_online.labels(worker_name).set(1)

            if event_type == "worker-heartbeat":
                self.metrics.worker_online.labels(worker_name).set(1)
                active = event.get("active")
                if active is not None:
                    self.metrics.worker_number_of_currently_executing_tasks.labels(
                        worker_name
                    ).set(active)

            if event_type == "worker-offline":
                self.metrics.worker_online.labels(worker_name).set(0)
                # B-12: 清理 counter，避免内存泄漏
                if worker_name and worker_name not in self.workers:
                    if worker_name in self.counter:
                        del self.counter[worker_name]
                        logger.debug("清理离线 worker 计数器: %s", worker_name)

        # 广播放在锁外，避免阻塞采集线程
        hub.publish_threadsafe(
            {
                "type": "event",
                "event": {
                    "type": event_type,
                    "hostname": worker_name,
                    "uuid": event.get("uuid"),
                    "name": event.get("name"),
                    "timestamp": event.get("timestamp"),
                },
            }
        )

    # ------------------------------------------------------------------
    def _on_task_event(self, event, worker_name: str, event_type: str) -> None:
        task_id = event.get("uuid")
        task = self.tasks.get(task_id)
        task_name = event.get("name", "") or ""
        if not task_name and task is not None:
            task_name = task.name or ""

        self.metrics.events.labels(worker_name, event_type, task_name).inc()

        runtime = event.get("runtime", 0)
        if runtime:
            self.metrics.runtime.labels(worker_name, task_name).observe(runtime)

        if task is None:
            return

        task_started = getattr(task, "started", None)
        task_received = getattr(task, "received", None)
        task_eta = getattr(task, "eta", None)

        if event_type == "task-received" and not task_eta and task_received:
            self.metrics.number_of_prefetched_tasks.labels(
                worker_name, task_name
            ).inc()

        if (
            event_type == "task-started"
            and not task_eta
            and task_started
            and task_received
        ):
            self.metrics.prefetch_time.labels(worker_name, task_name).set(
                task_started - task_received
            )
            self.metrics.number_of_prefetched_tasks.labels(
                worker_name, task_name
            ).dec()

        if (
            event_type in ("task-succeeded", "task-failed")
            and not task_eta
            and task_started
            and task_received
        ):
            self.metrics.prefetch_time.labels(worker_name, task_name).set(0)

    # ------------------------------------------------------------------
    def snapshot_timeline(self, ts: float) -> None:
        """由定时器调用，把这一采样周期内的事件量固化成一个时间点。"""
        with self.lock:
            active = sum(
                1 for t in self.tasks.values() if t.state == "STARTED"
            )
            point = {
                "ts": ts,
                "received": self._tick.get("task-received", 0),
                "started": self._tick.get("task-started", 0),
                "succeeded": self._tick.get("task-succeeded", 0),
                "failed": self._tick.get("task-failed", 0),
                "retried": self._tick.get("task-retried", 0),
                "revoked": self._tick.get("task-revoked", 0),
                "active": active,
            }
            self._tick.clear()
            self.timeline.append(point)
        return point

    def get_timeline(self, limit: int = 120) -> List[Dict[str, Any]]:
        with self.lock:
            return list(self.timeline)[-limit:]

    # ------------------------------------------------------------------
    def task_types(self) -> List[str]:
        with self.lock:
            return sorted({t.name for t in self.tasks.values() if t.name})

    def worker_names(self) -> List[str]:
        with self.lock:
            return sorted(self.workers.keys())

    def totals(self) -> Dict[str, int]:
        """全局任务状态汇总，供 Dashboard 卡片使用。"""
        with self.lock:
            c: Counter = Counter()
            for t in self.tasks.values():
                c[t.state or "UNKNOWN"] += 1
            return dict(c)


def build_state(max_workers: int, max_tasks: int) -> EventsState:
    return EventsState(
        max_workers_in_memory=max_workers,
        max_tasks_in_memory=max_tasks,
    )
