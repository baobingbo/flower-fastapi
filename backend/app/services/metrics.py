"""Prometheus 指标，完整对齐 flower 原有指标集合。"""
from __future__ import annotations

from typing import Optional

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from ..core.config import settings

_METRICS: Optional["PrometheusMetrics"] = None


class PrometheusMetrics:
    def __init__(self, registry: Optional[CollectorRegistry] = None):
        kw = {"registry": registry} if registry is not None else {}

        self.events = Counter(
            "flower_events_total",
            "Number of events",
            ["worker", "type", "task"],
            **kw,
        )
        self.runtime = Histogram(
            "flower_task_runtime_seconds",
            "Task runtime",
            ["worker", "task"],
            buckets=tuple(settings.task_runtime_metric_buckets),
            **kw,
        )
        self.prefetch_time = Gauge(
            "flower_task_prefetch_time_seconds",
            "The time the task spent waiting at the celery worker to be executed.",
            ["worker", "task"],
            **kw,
        )
        self.number_of_prefetched_tasks = Gauge(
            "flower_worker_prefetched_tasks",
            "Number of tasks of given type prefetched at a worker",
            ["worker", "task"],
            **kw,
        )
        self.worker_online = Gauge(
            "flower_worker_online",
            "Worker online status",
            ["worker"],
            **kw,
        )
        self.worker_number_of_currently_executing_tasks = Gauge(
            "flower_worker_number_of_currently_executing_tasks",
            "Number of tasks currently executing at a worker",
            ["worker"],
            **kw,
        )


def get_prometheus_metrics() -> PrometheusMetrics:
    global _METRICS
    if _METRICS is None:
        _METRICS = PrometheusMetrics()
    return _METRICS
