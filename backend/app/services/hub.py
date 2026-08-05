"""WebSocket 广播中心：把 Celery 事件实时推给前端。

除了扇出给 WebSocket 订阅者，这里还维护一段**环形事件历史**。
原因：前端支持「HTTP 轮询」模式，此时没有任何 WebSocket 订阅者，
但轮询接口仍然需要拿到两次请求之间新产生的事件。
历史带自增游标（cursor），轮询方按 ``since`` 增量取，不重不漏。
"""
from __future__ import annotations

import asyncio
import collections
import logging
import threading
from typing import Any, Deque, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)


class EventHub:
    """线程安全的事件扇出 + 事件历史缓冲。"""

    def __init__(self, maxsize: int = 2000, history: int = 500):
        self._subscribers: Set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._maxsize = maxsize

        self._history: Deque[Tuple[int, Dict[str, Any]]] = collections.deque(maxlen=history)
        self._seq = 0
        self._hlock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    # ------------------------------------------------------------------
    # 历史缓冲（轮询模式使用）
    # ------------------------------------------------------------------
    @property
    def cursor(self) -> int:
        with self._hlock:
            return self._seq

    def _record(self, message: Dict[str, Any]) -> None:
        if message.get("type") != "event":
            return
        with self._hlock:
            self._seq += 1
            self._history.append((self._seq, message.get("event") or {}))

    def recent(self, since: int = 0, limit: int = 200) -> Dict[str, Any]:
        """取 ``since`` 之后的事件。since=0 表示取最近 limit 条。"""
        with self._hlock:
            cursor = self._seq
            if since <= 0:
                picked: List[Dict[str, Any]] = [e for _, e in self._history]
            else:
                picked = [e for s, e in self._history if s > since]
        if limit and len(picked) > limit:
            picked = picked[-limit:]
        # 前端按"最新在前"渲染事件流
        picked.reverse()
        return {"cursor": cursor, "events": picked}

    # ------------------------------------------------------------------
    def publish_threadsafe(self, message: Dict[str, Any]) -> None:
        """供采集线程调用。历史缓冲无条件记录，扇出仅在有订阅者时进行。"""
        self._record(message)
        if self._loop is None or not self._subscribers:
            return
        try:
            self._loop.call_soon_threadsafe(self._publish, message)
        except RuntimeError:
            pass

    def _publish(self, message: Dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                # 慢消费者丢弃最旧的一条，保证实时性
                try:
                    q.get_nowait()
                    q.put_nowait(message)
                except Exception:
                    pass


hub = EventHub()
