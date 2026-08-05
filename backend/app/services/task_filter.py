"""任务列表过滤 / 排序，行为对齐 flower 的 iter_tasks。"""
from __future__ import annotations

import datetime
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .search import parse_search_terms, satisfies_search_terms

SORT_KEYS = {
    "name": str,
    "state": str,
    "received": float,
    "started": float,
    "runtime": float,
    "succeeded": float,
    "failed": float,
    "timestamp": float,
    "worker": str,
    "uuid": str,
}


def _to_ts(value: str) -> float:
    return time.mktime(
        datetime.datetime.strptime(value, "%Y-%m-%d %H:%M").timetuple()
    )


class _Comparable:
    """None 视为最小值，避免混合类型排序抛错。"""

    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return self.value == other.value

    def __lt__(self, other):
        a, b = self.value, other.value
        if a is None:
            return b is not None
        if b is None:
            return False
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


def sort_tasks(tasks: List[Tuple[str, Any]], sort_by: str):
    reverse = sort_by.startswith("-")
    key_name = sort_by.lstrip("-")
    if key_name not in SORT_KEYS:
        return tasks

    def key(item):
        value = getattr(item[1], key_name, None)
        if key_name == "worker" and value is not None:
            value = getattr(value, "hostname", None)
        return _Comparable(value)

    return sorted(tasks, key=key, reverse=reverse)


# pylint: disable=too-many-branches
def iter_tasks(
    state,
    limit: Optional[int] = None,
    offset: int = 0,
    type: Optional[str] = None,
    worker: Optional[str] = None,
    task_state: Optional[str] = None,
    sort_by: Optional[str] = None,
    received_start: Optional[str] = None,
    received_end: Optional[str] = None,
    started_start: Optional[str] = None,
    started_end: Optional[str] = None,
    search: Optional[str] = None,
    root_id: Optional[str] = None,
    parent_id: Optional[str] = None,
) -> Iterator[Tuple[str, Any]]:
    # 注意：celery 5.6 的 tasks_by_timestamp() 底层依赖独立的 _taskheap 堆，
    # 在某些事件路径下不会填充，导致列表为空（而 len(state.tasks) 却有数据）。
    # 这里直接遍历 state.tasks 字典再自行排序，行为更可靠。
    tasks = [(uuid, task) for uuid, task in state.tasks.items()]
    if sort_by:
        tasks = sort_tasks(tasks, sort_by)

    search_terms = parse_search_terms(search or "")

    i = 0
    for uuid, task in tasks:
        if type and task.name != type:
            continue
        if worker and (not task.worker or task.worker.hostname != worker):
            continue
        if task_state and task.state != task_state:
            continue
        if root_id and getattr(task, "root_id", None) != root_id:
            continue
        if parent_id and getattr(task, "parent_id", None) != parent_id:
            continue
        if received_start and task.received and task.received < _to_ts(received_start):
            continue
        if received_end and task.received and task.received > _to_ts(received_end):
            continue
        if started_start and task.started and task.started < _to_ts(started_start):
            continue
        if started_end and task.started and task.started > _to_ts(started_end):
            continue
        if not satisfies_search_terms(task, search_terms):
            continue
        if i >= offset:
            yield uuid, task
        i += 1
        if limit is not None and i == limit + offset:
            break


def count_tasks(state, **kwargs) -> int:
    kwargs.pop("limit", None)
    kwargs.pop("offset", None)
    return sum(1 for _ in iter_tasks(state, **kwargs))


def task_to_dict(task) -> Dict[str, Any]:
    """把 celery Task 对象转成 JSON 友好的 dict。"""
    data = task.as_dict()
    worker = data.pop("worker", None)
    if worker is not None:
        data["worker"] = getattr(worker, "hostname", worker)
    children = data.get("children")
    if children:
        data["children"] = [getattr(c, "id", None) or str(c) for c in children]
    # parent / root 是 Task 对象，序列化成 id
    for key in ("parent", "root"):
        if data.get(key) is not None:
            data[key] = getattr(data[key], "uuid", None) or str(data[key])
    # 结果与异常必须可 JSON 序列化
    for key in ("result", "exception", "traceback"):
        if key in data and data[key] is not None and not isinstance(data[key], (str, int, float, bool)):
            data[key] = repr(data[key])
    return data


def get_task_by_id(state, task_id: str):
    return state.tasks.get(task_id)
