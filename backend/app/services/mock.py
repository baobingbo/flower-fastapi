"""演示模式：内置模拟 Celery 集群。

生成与真实 Celery 完全同构的事件流写入 EventsState，并填充 Inspector 缓存，
因此上层 API / 前端无需任何分支判断即可获得全功能体验。
"""
from __future__ import annotations

import itertools
import logging
import random
import threading
import time
import uuid as uuidlib
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TASK_CATALOG = [
    ("app.tasks.send_email", 0.4, 2.0, 0.04),
    ("app.tasks.generate_report", 1.5, 9.0, 0.09),
    ("app.tasks.resize_image", 0.2, 1.4, 0.03),
    ("app.tasks.sync_inventory", 0.8, 4.5, 0.12),
    ("app.tasks.charge_order", 0.3, 1.8, 0.06),
    ("app.tasks.rebuild_index", 3.0, 16.0, 0.07),
    ("app.tasks.export_csv", 1.0, 6.0, 0.05),
    ("app.tasks.notify_webhook", 0.1, 0.9, 0.15),
]

QUEUES = ["celery", "emails", "reports", "media", "priority"]

ERRORS = [
    ("ConnectionError", "Connection refused by upstream service"),
    ("TimeoutError", "Operation exceeded soft time limit"),
    ("ValueError", "Invalid payload: missing required field 'id'"),
    ("KeyError", "'customer_id'"),
]


def _traceback(exc_type: str, message: str, task_name: str) -> str:
    return (
        "Traceback (most recent call last):\n"
        '  File "/app/celery/app/trace.py", line 451, in trace_task\n'
        "    R = retval = fun(*args, **kwargs)\n"
        f'  File "/app/tasks.py", line 88, in {task_name.rsplit(".", 1)[-1]}\n'
        "    return backend.execute(payload)\n"
        f"{exc_type}: {message}\n"
    )


class MockWorker:
    def __init__(self, name: str, queues: List[str], concurrency: int):
        self.name = name
        self.queues = list(queues)
        self.concurrency = concurrency
        self.pid = random.randint(1000, 60000)
        self.child_pids = [
            self.pid + i + 1 for i in range(concurrency)
        ]
        self.online = True
        self.processed: Dict[str, int] = {}
        self.active: List[Dict[str, Any]] = []
        self.reserved: List[Dict[str, Any]] = []
        self.scheduled: List[Dict[str, Any]] = []
        self.revoked: List[str] = []
        self.autoscale: Optional[Dict[str, int]] = None
        self.rate_limits: Dict[str, str] = {}
        self.time_limits: Dict[str, List[Optional[float]]] = {}
        self.started_at = time.time()

    # ------------------------------------------------------------------
    def stats(self) -> Dict[str, Any]:
        total_tasks = sum(self.processed.values()) or 1
        return {
            "broker": {
                "hostname": "127.0.0.1",
                "port": 6379,
                "transport": "redis",
                "virtual_host": "0",
                "userid": None,
                "insist": False,
                "ssl": False,
                "login_method": None,
                "connect_timeout": 4,
                "heartbeat": 120.0,
                "transport_options": {},
                "uri_prefix": None,
                "alternates": [],
            },
            "clock": str(random.randint(2000, 90000)),
            "uptime": int(time.time() - self.started_at),
            "pid": self.pid,
            "pool": {
                "max-concurrency": self.concurrency,
                "min-concurrency": self.autoscale["min"] if self.autoscale else self.concurrency,
                "max-tasks-per-child": "N/A",
                "processes": self.child_pids,
                "put-guarded-by-semaphore": False,
                "timeouts": [0, 0],
                "writes": {
                    "all": "100.00%",
                    "avg": f"{100 / max(len(self.child_pids), 1):.2f}%",
                    "inqueues": {"active": len(self.active), "total": self.concurrency},
                    "raw": str(total_tasks),
                    "total": total_tasks,
                },
            },
            "prefetch_count": self.concurrency * 4,
            "rusage": {
                "utime": round(random.uniform(1, 400), 6),
                "stime": round(random.uniform(0.5, 120), 6),
                "maxrss": random.randint(40000, 260000),
                "idrss": 0,
                "isrss": 0,
                "ixrss": 0,
                "majflt": random.randint(0, 40),
                "minflt": random.randint(2000, 90000),
                "nswap": 0,
                "inblock": random.randint(0, 4000),
                "oublock": random.randint(0, 4000),
                "msgsnd": random.randint(100, 9000),
                "msgrcv": random.randint(100, 9000),
                "nsignals": 0,
                "nvcsw": random.randint(500, 40000),
                "nivcsw": random.randint(100, 9000),
            },
            "total": dict(self.processed),
            **({"autoscaler": {
                "max": self.autoscale["max"],
                "min": self.autoscale["min"],
                "current": self.concurrency,
                "qty": len(self.active),
            }} if self.autoscale else {}),
        }

    def active_queues(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": q,
                "exchange": {
                    "name": q,
                    "type": "direct",
                    "arguments": None,
                    "durable": True,
                    "passive": False,
                    "auto_delete": False,
                    "delivery_mode": 2,
                },
                "routing_key": q,
                "queue_arguments": None,
                "binding_arguments": None,
                "consumer_arguments": None,
                "durable": True,
                "exclusive": False,
                "auto_delete": False,
                "no_ack": False,
                "alias": None,
                "bindings": [],
            }
            for q in self.queues
        ]

    def conf(self) -> Dict[str, Any]:
        return {
            "broker_url": "redis://localhost:6379/0",
            "result_backend": "redis://localhost:6379/1",
            "task_serializer": "json",
            "result_serializer": "json",
            "accept_content": ["json"],
            "timezone": "Asia/Shanghai",
            "enable_utc": True,
            "worker_concurrency": self.concurrency,
            "worker_prefetch_multiplier": 4,
            "task_acks_late": True,
            "task_default_queue": "celery",
            "task_send_sent_event": True,
            "worker_send_task_events": True,
            "broker_transport_options": {"visibility_timeout": 3600},
            "task_time_limit": 1800,
            "task_soft_time_limit": 1500,
            "include": ["app.tasks"],
        }


class MockCluster:
    """驱动模拟事件流的后台线程。"""

    def __init__(self, state, inspector, worker_count: int = 4, seed_tasks: int = 260):
        self.state = state
        self.inspector = inspector
        self.seed_tasks = seed_tasks
        self._clock = itertools.count(1)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

        self.workers: Dict[str, MockWorker] = {}
        for i in range(worker_count):
            name = f"celery@node-{i + 1}"
            queues = random.sample(QUEUES, k=random.randint(1, 3))
            if "celery" not in queues:
                queues.insert(0, "celery")
            self.workers[name] = MockWorker(
                name, queues, concurrency=random.choice([2, 4, 4, 8])
            )
        # 保留一个离线节点，便于验证状态展示与清理逻辑
        offline = MockWorker("celery@node-standby", ["celery"], 2)
        offline.online = False
        self.workers[offline.name] = offline

        self._inflight: List[Dict[str, Any]] = []
        self.queue_depth: Dict[str, int] = {q: random.randint(0, 40) for q in QUEUES}

    # ------------------------------------------------------------------
    # 事件构造
    # ------------------------------------------------------------------
    def _emit(self, event_type: str, hostname: str, **fields) -> None:
        now = time.time()
        event = {
            "type": event_type,
            "hostname": hostname,
            "timestamp": fields.pop("timestamp", now),
            "local_received": now,
            "utcoffset": 0,
            "pid": self.workers[hostname].pid if hostname in self.workers else 0,
            "clock": next(self._clock),
            **fields,
        }
        self.state.event(event)

    # ------------------------------------------------------------------
    def start(self) -> None:
        self._bootstrap()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="mock-cluster"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    def _bootstrap(self) -> None:
        """预热：上线 worker + 灌入历史任务，让 UI 一打开就有数据。"""
        now = time.time()
        for w in self.workers.values():
            self._emit("worker-online", w.name, freq=2.0,
                       sw_ident="py-celery", sw_ver="5.4.0", sw_sys="Linux",
                       timestamp=now - 3600 if not w.online else now)
            if not w.online:
                # 离线节点：先上线再下线，保证它出现在列表中且状态为 offline
                self._emit("worker-offline", w.name, timestamp=now - 1800)

        for i in range(self.seed_tasks):
            w = random.choice([x for x in self.workers.values() if x.online])
            name, lo, hi, fail_rate = random.choice(TASK_CATALOG)
            ts = now - (self.seed_tasks - i) * random.uniform(0.6, 3.2)
            self._simulate_full_task(w, name, lo, hi, fail_rate, base_ts=ts)

        self.refresh_inspector()

    def _simulate_full_task(self, w: MockWorker, name, lo, hi, fail_rate, base_ts):
        """一次性生成一个已完成任务的完整事件序列（用于历史数据）。"""
        tid = str(uuidlib.uuid4())
        args, kwargs = self._gen_args(name)
        runtime = round(random.uniform(lo, hi), 4)
        queue = random.choice(w.queues)

        self._emit("task-sent", w.name, uuid=tid, name=name, args=args,
                   kwargs=kwargs, retries=0, eta=None, expires=None,
                   queue=queue, exchange=queue, routing_key=queue,
                   timestamp=base_ts - 0.05)
        self._emit("task-received", w.name, uuid=tid, name=name, args=args,
                   kwargs=kwargs, retries=0, eta=None, expires=None,
                   timestamp=base_ts)
        roll = random.random()
        if roll < 0.02:
            self._emit("task-revoked", w.name, uuid=tid, terminated=False,
                       signum=None, expired=False, timestamp=base_ts + 0.2)
            return
        self._emit("task-started", w.name, uuid=tid, timestamp=base_ts + 0.1)
        w.processed[name] = w.processed.get(name, 0) + 1

        if roll < 0.02 + fail_rate:
            exc_type, msg = random.choice(ERRORS)
            self._emit("task-failed", w.name, uuid=tid,
                       exception=f"{exc_type}('{msg}')",
                       traceback=_traceback(exc_type, msg, name),
                       timestamp=base_ts + 0.1 + runtime)
        elif roll < 0.02 + fail_rate + 0.03:
            self._emit("task-retried", w.name, uuid=tid,
                       exception="ConnectionError('temporary failure')",
                       traceback=_traceback("ConnectionError", "temporary failure", name),
                       timestamp=base_ts + 0.1 + runtime)
        else:
            self._emit("task-succeeded", w.name, uuid=tid,
                       result=repr(self._gen_result(name)), runtime=runtime,
                       timestamp=base_ts + 0.1 + runtime)

    @staticmethod
    def _gen_args(name: str) -> tuple[str, str]:
        if "email" in name:
            return f"['user{random.randint(1, 9999)}@example.com']", "{'template': 'welcome'}"
        if "report" in name:
            return f"[{random.randint(1, 500)}]", "{'format': 'pdf', 'range': '30d'}"
        if "image" in name:
            return f"['s3://bucket/img/{random.randint(1, 9999)}.jpg']", "{'width': 1280}"
        if "order" in name:
            return f"[{random.randint(10000, 99999)}]", "{'currency': 'CNY'}"
        return f"[{random.randint(1, 100)}, {random.randint(1, 100)}]", "{}"

    @staticmethod
    def _gen_result(name: str):
        if "email" in name:
            return {"sent": True, "message_id": str(uuidlib.uuid4())[:8]}
        if "report" in name:
            return {"url": "s3://reports/%s.pdf" % random.randint(1000, 9999)}
        if "image" in name:
            return {"width": 1280, "height": 720}
        return random.randint(1, 10000)

    # ------------------------------------------------------------------
    def _run(self) -> None:
        last_heartbeat = 0.0
        while not self._stop.wait(0.35):
            try:
                with self._lock:
                    self._tick()
                    now = time.time()
                    if now - last_heartbeat > 2.0:
                        self._heartbeat()
                        self.refresh_inspector()
                        last_heartbeat = now
            except Exception as exc:
                logger.debug("模拟集群异常: %s", exc)

    def _tick(self) -> None:
        online = [w for w in self.workers.values() if w.online]
        if not online:
            return

        # 推进在途任务
        now = time.time()
        for item in list(self._inflight):
            if now < item["finish_at"]:
                continue
            self._inflight.remove(item)
            w = item["worker"]
            w.active = [a for a in w.active if a["id"] != item["uuid"]]
            roll = random.random()
            if roll < item["fail_rate"]:
                exc_type, msg = random.choice(ERRORS)
                self._emit("task-failed", w.name, uuid=item["uuid"],
                           exception=f"{exc_type}('{msg}')",
                           traceback=_traceback(exc_type, msg, item["name"]))
            elif roll < item["fail_rate"] + 0.03:
                self._emit("task-retried", w.name, uuid=item["uuid"],
                           exception="ConnectionError('temporary failure')",
                           traceback=_traceback("ConnectionError", "temporary failure", item["name"]))
            else:
                self._emit("task-succeeded", w.name, uuid=item["uuid"],
                           result=repr(self._gen_result(item["name"])),
                           runtime=round(item["runtime"], 4))

        # 投放新任务
        for _ in range(random.randint(0, 3)):
            w = random.choice(online)
            if len(w.active) >= w.concurrency:
                continue
            name, lo, hi, fail_rate = random.choice(TASK_CATALOG)
            tid = str(uuidlib.uuid4())
            args, kwargs = self._gen_args(name)
            queue = random.choice(w.queues)
            runtime = random.uniform(lo, hi)

            self._emit("task-sent", w.name, uuid=tid, name=name, args=args,
                       kwargs=kwargs, retries=0, eta=None, expires=None,
                       queue=queue, exchange=queue, routing_key=queue)
            self._emit("task-received", w.name, uuid=tid, name=name, args=args,
                       kwargs=kwargs, retries=0, eta=None, expires=None)
            self._emit("task-started", w.name, uuid=tid)
            w.processed[name] = w.processed.get(name, 0) + 1
            w.active.append({
                "id": tid, "name": name, "args": args, "kwargs": kwargs,
                "type": name, "hostname": w.name, "time_start": time.time(),
                "acknowledged": True, "delivery_info": {
                    "exchange": queue, "routing_key": queue, "priority": 0,
                    "redelivered": False,
                },
                "worker_pid": random.choice(w.child_pids),
            })
            self._inflight.append({
                "uuid": tid, "worker": w, "name": name,
                "finish_at": time.time() + runtime,
                "runtime": runtime, "fail_rate": fail_rate,
            })

        # 队列水位波动
        for q in self.queue_depth:
            delta = random.randint(-4, 5)
            self.queue_depth[q] = max(0, self.queue_depth[q] + delta)

    def _heartbeat(self) -> None:
        for w in self.workers.values():
            if not w.online:
                continue
            self._emit(
                "worker-heartbeat", w.name, freq=2.0,
                active=len(w.active),
                processed=sum(w.processed.values()),
                loadavg=[round(random.uniform(0.1, 3.5), 2) for _ in range(3)],
                sw_ident="py-celery", sw_ver="5.4.0", sw_sys="Linux",
            )

    # ------------------------------------------------------------------
    def refresh_inspector(self) -> None:
        """把模拟状态写入 Inspector 缓存，让 worker 相关接口透明工作。"""
        for w in self.workers.values():
            if not w.online:
                self.inspector.workers.pop(w.name, None)
                continue
            registered = sorted({n for n, *_ in TASK_CATALOG})
            self.inspector.workers[w.name] = {
                "stats": w.stats(),
                "active_queues": w.active_queues(),
                "registered": registered,
                "conf": w.conf(),
                "active": list(w.active),
                "reserved": list(w.reserved),
                "scheduled": list(w.scheduled),
                "revoked": list(w.revoked),
                "timestamp": time.time(),
            }

    def queues(self, names: List[str]) -> List[Dict[str, Any]]:
        out = []
        for name in names:
            depth = self.queue_depth.get(name, 0)
            consumers = sum(
                1 for w in self.workers.values() if w.online and name in w.queues
            )
            out.append({
                "name": name,
                "messages": depth,
                "messages_ready": max(0, depth - consumers),
                "messages_unacknowledged": min(depth, consumers),
                "consumers": consumers,
                "idle_since": None if depth else time.strftime("%Y-%m-%d %H:%M:%S"),
            })
        return out

    def queue_names(self) -> List[str]:
        names = set()
        for w in self.workers.values():
            if w.online:
                names.update(w.queues)
        return sorted(names or QUEUES)

    # ------------------------------------------------------------------
    # 远程控制指令（对应 celery control 广播）
    # ------------------------------------------------------------------
    def has_worker(self, name: str) -> bool:
        w = self.workers.get(name)
        return bool(w and w.online)

    def shutdown(self, name: str) -> None:
        with self._lock:
            w = self.workers[name]
            w.online = False
            w.active.clear()
            self._inflight = [i for i in self._inflight if i["worker"] is not w]
            self._emit("worker-offline", name)
            self.refresh_inspector()

    def pool_restart(self, name: str) -> None:
        with self._lock:
            w = self.workers[name]
            w.child_pids = [w.pid + i + 1 for i in range(w.concurrency)]
            w.active.clear()
            self._inflight = [i for i in self._inflight if i["worker"] is not w]
            self.refresh_inspector()

    def pool_grow(self, name: str, n: int) -> int:
        with self._lock:
            w = self.workers[name]
            w.concurrency += n
            w.child_pids = [w.pid + i + 1 for i in range(w.concurrency)]
            self.refresh_inspector()
            return w.concurrency

    def pool_shrink(self, name: str, n: int) -> int:
        with self._lock:
            w = self.workers[name]
            w.concurrency = max(1, w.concurrency - n)
            w.child_pids = [w.pid + i + 1 for i in range(w.concurrency)]
            self.refresh_inspector()
            return w.concurrency

    def pool_autoscale(self, name: str, minimum: int, maximum: int) -> None:
        with self._lock:
            w = self.workers[name]
            w.autoscale = {"min": minimum, "max": maximum}
            w.concurrency = max(minimum, min(w.concurrency, maximum))
            w.child_pids = [w.pid + i + 1 for i in range(w.concurrency)]
            self.refresh_inspector()

    def add_consumer(self, name: str, queue: str) -> None:
        with self._lock:
            w = self.workers[name]
            if queue not in w.queues:
                w.queues.append(queue)
            self.queue_depth.setdefault(queue, 0)
            self.refresh_inspector()

    def cancel_consumer(self, name: str, queue: str) -> None:
        with self._lock:
            w = self.workers[name]
            if queue in w.queues:
                w.queues.remove(queue)
            self.refresh_inspector()

    def revoke(self, task_id: str, terminate: bool = False) -> None:
        with self._lock:
            for w in self.workers.values():
                w.active = [a for a in w.active if a["id"] != task_id]
                if task_id not in w.revoked:
                    w.revoked.append(task_id)
            self._inflight = [i for i in self._inflight if i["uuid"] != task_id]
            host = next(
                (w.name for w in self.workers.values() if w.online), "celery@node-1"
            )
            self._emit("task-revoked", host, uuid=task_id,
                       terminated=terminate, signum="SIGTERM" if terminate else None,
                       expired=False)
            self.refresh_inspector()

    def set_rate_limit(self, name: str, taskname: str, ratelimit: str) -> None:
        with self._lock:
            self.workers[name].rate_limits[taskname] = ratelimit

    def set_time_limit(self, name: str, taskname: str, soft, hard) -> None:
        with self._lock:
            self.workers[name].time_limits[taskname] = [soft, hard]

    def send_task(self, taskname: str, args, kwargs, countdown=None) -> str:
        """模拟下发任务，立即产生真实事件序列。"""
        with self._lock:
            online = [w for w in self.workers.values() if w.online]
            if not online:
                raise RuntimeError("没有在线 worker")
            w = random.choice(online)
            tid = str(uuidlib.uuid4())
            queue = random.choice(w.queues)
            meta = next((t for t in TASK_CATALOG if t[0] == taskname), None)
            lo, hi, fail_rate = (meta[1], meta[2], meta[3]) if meta else (0.2, 1.5, 0.05)
            runtime = random.uniform(lo, hi)
            a = str(list(args or []))
            k = str(dict(kwargs or {}))

            self._emit("task-sent", w.name, uuid=tid, name=taskname, args=a,
                       kwargs=k, retries=0, eta=None, expires=None,
                       queue=queue, exchange=queue, routing_key=queue)
            self._emit("task-received", w.name, uuid=tid, name=taskname, args=a,
                       kwargs=k, retries=0, eta=None, expires=None)
            self._emit("task-started", w.name, uuid=tid)
            w.processed[taskname] = w.processed.get(taskname, 0) + 1
            w.active.append({
                "id": tid, "name": taskname, "args": a, "kwargs": k,
                "type": taskname, "hostname": w.name, "time_start": time.time(),
                "acknowledged": True, "worker_pid": random.choice(w.child_pids),
                "delivery_info": {"exchange": queue, "routing_key": queue,
                                  "priority": 0, "redelivered": False},
            })
            self._inflight.append({
                "uuid": tid, "worker": w, "name": taskname,
                "finish_at": time.time() + runtime,
                "runtime": runtime, "fail_rate": fail_rate,
            })
            self.refresh_inspector()
            return tid

    def registered_tasks(self) -> List[str]:
        return sorted({n for n, *_ in TASK_CATALOG})
