"""运行时服务聚合：把 Celery 连接、事件采集、Inspector、Broker、模拟集群串起来。

上层 API 只依赖本模块，无需关心当前是真实集群还是演示模式。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

from ..core.celery_app import (
    broker_uri,
    get_celery_app,
    mask_url_password,
    ping_broker,
    transport_driver,
)
from ..core.config import settings
from .broker import create_broker
from .events import Events
from .hub import hub
from .inspector import Inspector
from .mock import MockCluster
from .state import build_state

logger = logging.getLogger(__name__)


class ControlError(Exception):
    """远程控制指令失败。"""

    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ServiceManager:
    def __init__(self) -> None:
        self.capp = get_celery_app()
        self.inspector = Inspector(self.capp, settings.inspect_timeout_seconds)
        self.events: Optional[Events] = None
        self.mock: Optional[MockCluster] = None
        self.state = None
        self.mock_mode = False
        self.started_at = time.time()
        self._timeline_task: Optional[asyncio.Task] = None
        self._refresh_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    async def startup(self) -> None:
        hub.bind_loop(asyncio.get_running_loop())

        # lifespan 已先跑完 runtime_config.load()：此时 broker 配置才是最终值。
        # manager 单例在 main.py 导入期就建好（__init__ 里按默认配置建过一版
        # Celery app），这里按最新配置重建 app 与 inspector，避免陈旧连接
        # 导致"配了哨兵/密码却按默认地址去连"而误降级演示模式。
        self.capp = get_celery_app()
        self.inspector = Inspector(self.capp, settings.inspect_timeout_seconds)

        if urlparse(settings.broker_url).scheme == "sentinel" and not (
            settings.broker_transport_options or {}
        ).get("master_name"):
            logger.error(
                "broker_url 为 sentinel:// 但未配置 master_name"
                "（请设置 FLOWER_BROKER_TRANSPORT_OPTIONS"
                "='{\"master_name\": \"mymaster\"}'），无法连接哨兵集群"
            )

        broker_alive = False
        if not settings.mock:
            broker_alive = await asyncio.get_running_loop().run_in_executor(
                None, ping_broker, 2.0
            )

        self.mock_mode = settings.mock or not broker_alive

        if self.mock_mode:
            logger.warning(
                "启用演示模式（broker=%s 不可用或显式开启 FLOWER_MOCK）",
                mask_url_password(settings.broker_url),
            )
            self.state = build_state(settings.max_workers, settings.max_tasks)
            self.mock = MockCluster(
                self.state,
                self.inspector,
                worker_count=settings.mock_workers,
                seed_tasks=settings.mock_seed_tasks,
            )
            self.mock.start()
        else:
            logger.info("连接真实 Celery 集群: %s", broker_uri())
            self.events = Events(
                self.capp,
                db=settings.db,
                persistent=settings.persistent,
                enable_events=settings.enable_events,
                state_save_interval=settings.state_save_interval,
                max_workers=settings.max_workers,
                max_tasks=settings.max_tasks,
            )
            self.state = self.events.state
            self.events.start()
            asyncio.create_task(self._safe_inspect())

        self._timeline_task = asyncio.create_task(self._timeline_loop())
        if not self.mock_mode and settings.auto_refresh:
            self._refresh_task = asyncio.create_task(self._auto_refresh_loop())

    async def shutdown(self) -> None:
        for t in (self._timeline_task, self._refresh_task):
            if t:
                t.cancel()
        if self.mock:
            self.mock.stop()
        if self.events:
            self.events.stop()

    # ------------------------------------------------------------------
    async def _timeline_loop(self) -> None:
        """每 2 秒固化一个时间点，供趋势图与实时推送使用。"""
        while True:
            try:
                await asyncio.sleep(2.0)
                point = self.state.snapshot_timeline(time.time())
                hub.publish_threadsafe({"type": "timeline", "point": point})
                hub.publish_threadsafe(
                    {"type": "summary", "summary": self.dashboard_summary()}
                )
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.debug("时间线采样失败: %s", exc)

    async def _auto_refresh_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(10.0)
                await self._safe_inspect()
            except asyncio.CancelledError:
                return

    async def _safe_inspect(self, workername: Optional[str] = None) -> None:
        try:
            await self.inspector.inspect(workername)
        except Exception as exc:
            logger.debug("inspect 失败: %s", exc)

    async def refresh_workers(self, workername: Optional[str] = None) -> None:
        if self.mock_mode:
            self.mock.refresh_inspector()
            return
        await self._safe_inspect(workername)

    # ------------------------------------------------------------------
    @property
    def workers(self) -> Dict[str, Dict[str, Any]]:
        return self.inspector.workers

    def is_known_worker(self, name: str) -> bool:
        if self.mock_mode:
            return self.mock.has_worker(name)
        return bool(name) and name in self.inspector.workers

    def registered_tasks(self) -> List[str]:
        """worker 已注册的任务名（用于下发任务的候选列表）。

        三个来源合并，越多越好用：
        1) inspect registered —— 最权威，但 worker 繁忙时可能超时拿不到；
        2) 本进程 capp.tasks —— 监控端通常不加载业务代码，多半为空；
        3) 事件流里出现过的任务类型 —— 只要跑过一次就有，是前两者的有效兜底。
        """
        if self.mock_mode:
            return self.mock.registered_tasks()
        names = set()
        for info in self.inspector.workers.values():
            for n in info.get("registered") or []:
                names.add(n.split(" ")[0] if isinstance(n, str) else n)
        try:
            names.update(
                n for n in self.capp.tasks.keys() if not n.startswith("celery.")
            )
        except Exception:
            pass
        try:
            if self.state is not None:
                names.update(
                    n for n in self.state.task_types() if not n.startswith("celery.")
                )
        except Exception:
            pass
        return sorted(names)

    @staticmethod
    def _route_queue(entry: Any) -> Optional[str]:
        """从 task_routes 的一项中取出队列名。

        worker conf 上报的 task_routes 两种形态都兼容：
        {"tasks.send_email": {"queue": "emails"}} 与 {"tasks.send_email": "emails"}。
        """
        if isinstance(entry, dict):
            queue = entry.get("queue")
            return queue if isinstance(queue, str) else None
        if isinstance(entry, str):
            return entry
        return None

    def registered_tasks_detail(self) -> List[Dict[str, str]]:
        """逐任务附带默认队列，用于前端"选任务即预填队列"的联动。

        路由来源优先级：worker conf 上报的 task_routes > 监控端
        settings.task_routes > settings.task_default_queue。监控端通常不加载
        业务代码，本地 settings.task_routes 多为空，而 worker 的 inspect conf
        会带上各自工程真实的 task_routes，故以 worker 上报为准。
        """
        routes: Dict[str, str] = dict(settings.task_routes or {})
        for info in self.inspector.workers.values():
            conf = info.get("conf")
            if not isinstance(conf, dict):
                continue
            worker_routes = conf.get("task_routes")
            if not isinstance(worker_routes, dict):
                continue
            for name, entry in worker_routes.items():
                queue = self._route_queue(entry)
                if queue:
                    routes[name] = queue
        default_q = settings.task_default_queue
        return [
            {"name": n, "queue": routes.get(n, default_q)}
            for n in self.registered_tasks()
        ]

    def available_queues(self) -> List[str]:
        """可投递队列候选：默认队列 + 路由目标 + worker 实际消费的队列。"""
        queues = {settings.task_default_queue}
        queues.update(settings.task_routes.values())
        try:
            queues.update(self.active_queue_names())
        except Exception:
            pass
        return sorted(queues)

    # ------------------------------------------------------------------
    def configured_worker_names(self) -> Set[str]:
        """当前 broker_url 中的 worker 名集合；空集合表示尚未完成首次探测。

        Celery 事件广播（Redis Pub/Sub）是服务端全局的，连到同实例其它 db、
        或其它 broker 的 worker 心跳也会被本进程收到。control inspect 的回执
        走按 db 隔离的队列，只有与监控端同一 broker/db 的 worker 能回包——
        因此用「曾被 inspect 到」作为归属判据，把非配置 broker 的 worker
        从所有查询里隔离掉（项目只支持单 broker，不做多 db 聚合）。
        演示模式没有真实 broker，全部放行，避免破坏离线节点展示。
        """
        if self.mock_mode:
            return set(self.state.workers)
        return set(self.inspector.known_workers)

    def visible_worker_names(self) -> Set[str]:
        """事件状态中允许对外展示的 worker 名集合。"""
        names = set(self.state.workers)
        allowed = self.configured_worker_names()
        # 白名单为空 = 首次 inspect 尚未完成，此时不过滤，避免首屏空白。
        if allowed:
            names &= allowed
        return names

    def worker_status_map(self) -> Dict[str, bool]:
        """在线状态映射，仅含配置 broker 的 worker。"""
        visible = self.visible_worker_names()
        return {
            name: bool(w.alive)
            for name, w in self.state.workers.items()
            if name in visible
        }

    def configured_worker_count(self) -> int:
        return len(self.visible_worker_names())

    def foreign_worker_count(self) -> int:
        """被隔离掉的非配置 broker worker 数，便于排障。"""
        return len(set(self.state.workers) - self.visible_worker_names())

    # ------------------------------------------------------------------
    def worker_rows(self) -> List[Dict[str, Any]]:
        """Dashboard 表格数据，字段与 flower workers 页面一致。"""
        state = self.state
        visible = self.visible_worker_names()
        allowed = self.configured_worker_names()
        rows: Dict[str, Dict[str, Any]] = {}
        for name, counts in state.counter.items():
            # 只展示配置 broker 的 worker：其它 broker/db 的心跳虽进事件流，
            # 但它们的 inspect 回执不可达，详情必然 404，不应出现在列表里。
            if name not in state.workers or name not in visible:
                continue
            w = state.workers[name]
            info: Dict[str, Any] = dict(counts)
            info.update(self._worker_as_dict(w))
            info["status"] = bool(w.alive)
            info["name"] = name
            rows[name] = info

        # 补上只有 inspect 信息、尚无事件的 worker（仍限定在配置 broker 白名单内）
        for name in self.inspector.workers:
            if allowed and name not in allowed:
                continue
            if name not in rows:
                rows[name] = {"name": name, "status": True}

        if settings.purge_offline_workers is not None:
            now = int(time.time())
            for name in list(rows):
                info = rows[name]
                if info.get("status"):
                    continue
                heartbeats = info.get("heartbeats") or []
                last = int(max(heartbeats)) if heartbeats else None
                if not last or now - last > settings.purge_offline_workers:
                    rows.pop(name)

        out = []
        for name, info in rows.items():
            out.append(
                {
                    "name": name,
                    "status": bool(info.get("status")),
                    "active": info.get("active", 0) or 0,
                    "processed": info.get("task-received", 0) or 0,
                    "failed": info.get("task-failed", 0) or 0,
                    "succeeded": info.get("task-succeeded", 0) or 0,
                    "retried": info.get("task-retried", 0) or 0,
                    "revoked": info.get("task-revoked", 0) or 0,
                    "loadavg": info.get("loadavg"),
                    "pid": info.get("pid"),
                    "sw_ident": info.get("sw_ident"),
                    "sw_ver": info.get("sw_ver"),
                    "sw_sys": info.get("sw_sys"),
                    "freq": info.get("freq"),
                    "heartbeats": (info.get("heartbeats") or [])[-1:],
                    "queues": [
                        q.get("name")
                        for q in (self.inspector.workers.get(name, {}).get(
                            "active_queues"
                        ) or [])
                    ],
                    "concurrency": (
                        (self.inspector.workers.get(name, {}).get("stats") or {})
                        .get("pool", {})
                        .get("max-concurrency")
                    ),
                }
            )
        return sorted(out, key=lambda x: x["name"])

    @staticmethod
    def _worker_as_dict(worker) -> Dict[str, Any]:
        fields = (
            "hostname", "pid", "freq", "heartbeats", "clock", "active",
            "processed", "loadavg", "sw_ident", "sw_ver", "sw_sys",
        )
        out = {}
        for key in fields:
            value = getattr(worker, key, None)
            if value is not None:
                out[key] = value
        return out

    def dashboard_summary(self) -> Dict[str, Any]:
        rows = self.worker_rows()
        totals = self.state.totals()
        return {
            "workers_total": len(rows),
            "workers_online": sum(1 for r in rows if r["status"]),
            "tasks_total": len(self.state.tasks),
            "processed": sum(r["processed"] for r in rows),
            "succeeded": sum(r["succeeded"] for r in rows),
            "failed": sum(r["failed"] for r in rows),
            "retried": sum(r["retried"] for r in rows),
            "revoked": sum(r["revoked"] for r in rows),
            "active": sum(r["active"] for r in rows),
            "states": totals,
            "mock_mode": self.mock_mode,
            "broker_url": broker_uri(),
            "transport": transport_driver(),
            "uptime": int(time.time() - self.started_at),
        }

    # ------------------------------------------------------------------
    def active_queue_names(self) -> List[str]:
        if self.mock_mode:
            return self.mock.queue_names()
        return self.inspector.active_queue_names(self.capp)

    async def broker_queues(self) -> List[Dict[str, Any]]:
        names = self.active_queue_names()
        if self.mock_mode:
            return self.mock.queues(names)
        http_api = None
        if transport_driver() == "amqp" and settings.broker_api:
            http_api = settings.broker_api
        try:
            broker = create_broker(
                broker_uri(include_password=True),
                http_api=http_api,
                broker_options=self.capp.conf.broker_transport_options,
                broker_use_ssl=self.capp.conf.broker_use_ssl,
            )
        except NotImplementedError as exc:
            raise ControlError(str(exc), 404) from exc
        try:
            return await broker.queues(names)
        except Exception as exc:
            logger.error("读取队列失败: %s", exc)
            return []

    # ------------------------------------------------------------------
    # 远程控制
    # ------------------------------------------------------------------
    def _require_worker(self, name: str) -> None:
        if not self.is_known_worker(name):
            raise ControlError(f"Unknown worker '{name}'", 404)

    @staticmethod
    def _error_reason(key: str, response) -> str:
        """从 broadcast 回复中提取失败原因。

        response 为空表示 worker 在超时内没有回复（常见于单线程 solo 池正在
        执行长任务），此时命令通常已经送达并生效，只是拿不到回执 —— 单独区分
        这种情况，避免把"未回执"报成"执行失败"。
        """
        if not response:
            return (
                "worker 未在 %.1fs 内回复（命令可能已生效，可稍后刷新确认；"
                "如需延长请调整 FLOWER_CONTROL_TIMEOUT）"
                % settings.control_timeout_seconds
            )
        for res in response:
            try:
                return res[key].get("error", "Unknown reason")
            except (KeyError, AttributeError):
                continue
        return "Unknown reason"

    def _broadcast(self, command: str, workername: str, arguments=None) -> str:
        response = self.capp.control.broadcast(
            command,
            arguments=arguments or {},
            destination=[workername],
            reply=True,
            timeout=settings.control_timeout_seconds,
        )
        if response and "ok" in (response[0].get(workername) or {}):
            return response[0][workername]["ok"]
        raise ControlError(self._error_reason(workername, response))

    async def _run(self, fn, *args, **kwargs):
        return await asyncio.get_running_loop().run_in_executor(
            None, lambda: fn(*args, **kwargs)
        )

    async def worker_shutdown(self, name: str) -> str:
        self._require_worker(name)
        if self.mock_mode:
            self.mock.shutdown(name)
            return "Shutting down!"
        await self._run(
            self.capp.control.broadcast, "shutdown", destination=[name]
        )
        return "Shutting down!"

    async def worker_pool_restart(self, name: str) -> str:
        self._require_worker(name)
        if self.mock_mode:
            self.mock.pool_restart(name)
            return f"Restarting '{name}' worker's pool"
        await self._run(self._broadcast, "pool_restart", name, {"reload": False})
        await self._safe_inspect(name)
        return f"Restarting '{name}' worker's pool"

    async def worker_pool_grow(self, name: str, n: int) -> str:
        self._require_worker(name)
        if self.mock_mode:
            size = self.mock.pool_grow(name, n)
            return f"Growing '{name}' worker's pool by {n} (now {size})"
        response = await self._run(
            self.capp.control.pool_grow,
            n=n,
            reply=True,
            destination=[name],
            timeout=settings.control_timeout_seconds,
        )
        if response and "ok" in (response[0].get(name) or {}):
            await self._safe_inspect(name)
            return f"Growing '{name}' worker's pool by {n}"
        raise ControlError(self._error_reason(name, response))

    async def worker_pool_shrink(self, name: str, n: int) -> str:
        self._require_worker(name)
        if self.mock_mode:
            size = self.mock.pool_shrink(name, n)
            return f"Shrinking '{name}' worker's pool by {n} (now {size})"
        response = await self._run(
            self.capp.control.pool_shrink,
            n=n,
            reply=True,
            destination=[name],
            timeout=settings.control_timeout_seconds,
        )
        if response and "ok" in (response[0].get(name) or {}):
            await self._safe_inspect(name)
            return f"Shrinking '{name}' worker's pool by {n}"
        raise ControlError(self._error_reason(name, response))

    async def worker_pool_autoscale(self, name: str, minimum: int, maximum: int) -> str:
        self._require_worker(name)
        if minimum > maximum:
            raise ControlError("min 不能大于 max", 400)
        if self.mock_mode:
            self.mock.pool_autoscale(name, minimum, maximum)
            return f"Autoscaling '{name}' worker (min={minimum}, max={maximum})"
        await self._run(
            self._broadcast, "autoscale", name, {"min": minimum, "max": maximum}
        )
        return f"Autoscaling '{name}' worker (min={minimum}, max={maximum})"

    async def _worker_consumes(self, name: str) -> set:
        """重新 inspect 该 worker，返回它当前订阅的队列名集合。"""
        await self._safe_inspect(name)
        info = self.inspector.get(name) or {}
        return {
            q.get("name")
            for q in (info.get("active_queues") or [])
            if q.get("name")
        }

    async def _confirm_consumer(
        self, name: str, queue: str, *, should_consume: bool, exc: ControlError
    ) -> str:
        """无回执时用 inspect 复核命令是否已生效。

        单线程（--pool=solo）worker 正在执行任务期间无法回复控制命令，
        但命令本身已经进入它的控制队列并会被执行。直接报错会误导用户，
        这里改为回查真实订阅状态：确实生效就当成功。
        """
        try:
            queues = await self._worker_consumes(name)
        except Exception:
            raise exc from None
        if (queue in queues) is should_consume:
            action = "开始消费" if should_consume else "停止消费"
            return f"'{name}' 已{action}队列 '{queue}'（命令已生效，未收到即时回执）"
        raise exc

    async def worker_add_consumer(self, name: str, queue: str) -> str:
        self._require_worker(name)
        if self.mock_mode:
            self.mock.add_consumer(name, queue)
            return f"add consumer {queue}"
        try:
            message = await self._run(
                self._broadcast, "add_consumer", name, {"queue": queue}
            )
        except ControlError as exc:
            return await self._confirm_consumer(
                name, queue, should_consume=True, exc=exc
            )
        # inspect 结果是缓存的，命令生效后必须刷新，否则界面仍显示旧队列列表
        await self._safe_inspect(name)
        return message

    async def worker_cancel_consumer(self, name: str, queue: str) -> str:
        self._require_worker(name)
        if self.mock_mode:
            self.mock.cancel_consumer(name, queue)
            return f"no longer consuming from {queue}"
        try:
            message = await self._run(
                self._broadcast, "cancel_consumer", name, {"queue": queue}
            )
        except ControlError as exc:
            return await self._confirm_consumer(
                name, queue, should_consume=False, exc=exc
            )
        await self._safe_inspect(name)
        return message

    async def task_revoke(
        self, task_id: str, terminate: bool = False, signal: str = "SIGTERM"
    ) -> str:
        if self.mock_mode:
            self.mock.revoke(task_id, terminate)
            return f"Revoked '{task_id}'"
        await self._run(
            self.capp.control.revoke, task_id, terminate=terminate, signal=signal
        )
        return f"Revoked '{task_id}'"

    async def task_rate_limit(self, taskname: str, workername: str, ratelimit: str) -> str:
        self._require_worker(workername)
        if self.mock_mode:
            self.mock.set_rate_limit(workername, taskname, ratelimit)
            return "new rate limit set successfully"
        response = await self._run(
            self.capp.control.rate_limit,
            taskname, ratelimit, reply=True, destination=[workername],
            timeout=settings.control_timeout_seconds,
        )
        if response and "ok" in (response[0].get(workername) or {}):
            return response[0][workername]["ok"]
        raise ControlError(self._error_reason(workername, response))

    async def task_time_limit(
        self, taskname: str, workername: str, soft, hard
    ) -> str:
        self._require_worker(workername)
        if self.mock_mode:
            self.mock.set_time_limit(workername, taskname, soft, hard)
            return "time limits set successfully"
        response = await self._run(
            self.capp.control.time_limit,
            taskname, reply=True, hard=hard, soft=soft, destination=[workername],
            timeout=settings.control_timeout_seconds,
        )
        if response and "ok" in (response[0].get(workername) or {}):
            return response[0][workername]["ok"]
        raise ControlError(self._error_reason(workername, response))

    # ------------------------------------------------------------------
    # 任务下发 / 结果
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_options(options: Dict[str, Any]) -> Dict[str, Any]:
        """对齐 flower BaseTaskHandler.normalize_options。"""
        import datetime as _dt

        fmt = "%Y-%m-%d %H:%M:%S.%f"
        options = dict(options or {})
        try:
            if options.get("eta"):
                options["eta"] = _dt.datetime.strptime(str(options["eta"]), fmt)
            if options.get("countdown") is not None:
                options["countdown"] = float(options["countdown"])
            if options.get("expires") is not None:
                expires = options["expires"]
                try:
                    expires = float(expires)
                except (TypeError, ValueError):
                    expires = _dt.datetime.strptime(str(expires), fmt)
                options["expires"] = expires
        except ValueError as exc:
            raise ControlError(f"Invalid option: {exc}", 400) from exc
        return {k: v for k, v in options.items() if v is not None}

    @staticmethod
    def _safe_result(value: Any) -> Any:
        import json

        try:
            json.dumps(value)
        except (TypeError, ValueError):
            return repr(value)
        return value

    def backend_configured(self) -> bool:
        from celery.backends.base import DisabledBackend

        try:
            return not isinstance(self.capp.backend, DisabledBackend)
        except Exception:
            return False

    async def apply_task(
        self,
        taskname: str,
        args: List[Any],
        kwargs: Dict[str, Any],
        options: Dict[str, Any],
        *,
        wait: bool = False,
        timeout: Optional[float] = None,
        require_registered: bool = True,
    ) -> Dict[str, Any]:
        """apply-async / apply / send-task 的统一实现。"""
        options = self._normalize_options(options)

        if self.mock_mode:
            countdown = options.get("countdown")
            try:
                task_id = self.mock.send_task(taskname, args, kwargs, countdown)
            except RuntimeError as exc:
                raise ControlError(str(exc), 503) from exc
            response: Dict[str, Any] = {"task-id": task_id, "state": "PENDING"}
            if wait:
                deadline = time.time() + (timeout or 30.0)
                while time.time() < deadline:
                    task = self.state.tasks.get(task_id)
                    if task is not None and task.state in (
                        "SUCCESS", "FAILURE", "REVOKED"
                    ):
                        response["state"] = task.state
                        response["result"] = self._safe_result(task.result)
                        response["traceback"] = getattr(task, "traceback", None)
                        return response
                    await asyncio.sleep(0.2)
                task = self.state.tasks.get(task_id)
                response["state"] = getattr(task, "state", "PENDING")
            return response

        if require_registered:
            if taskname in self.capp.tasks:
                task = self.capp.tasks[taskname]
                result = await self._run(
                    task.apply_async, args=args, kwargs=kwargs, **options
                )
            elif taskname in set(self.registered_tasks()):
                # 监控进程通常不加载业务任务代码，本地 capp.tasks 里自然没有；
                # 但只要 worker 侧 inspect 到该任务已注册，就按名字直接投递。
                logger.info("任务 '%s' 本地未注册，改用 send_task 投递", taskname)
                result = await self._run(
                    self.capp.send_task, taskname, args=args, kwargs=kwargs, **options
                )
            else:
                raise ControlError(f"Unknown task '{taskname}'", 404)
        else:
            result = await self._run(
                self.capp.send_task, taskname, args=args, kwargs=kwargs, **options
            )

        response = {"task-id": result.task_id}
        if wait:
            await self._run(result.get, propagate=False, timeout=timeout)
            response["result"] = self._safe_result(result.result)
            if result.state == "FAILURE":
                response["traceback"] = result.traceback
        if self.backend_configured():
            response["state"] = result.state
        return response

    async def task_result(
        self, task_id: str, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        if self.mock_mode:
            task = self.state.tasks.get(task_id)
            if task is None:
                raise ControlError(f"Unknown task '{task_id}'", 404)
            return {
                "task-id": task_id,
                "state": task.state,
                "result": self._safe_result(task.result),
                "traceback": getattr(task, "traceback", None),
            }

        from celery.result import AsyncResult

        if not self.backend_configured():
            raise ControlError("Result backend is not configured", 503)
        result = AsyncResult(task_id, app=self.capp)
        response = {"task-id": task_id, "state": result.state}
        if timeout:
            await self._run(result.get, timeout=timeout, propagate=False)
        if timeout or result.ready():
            response["result"] = self._safe_result(result.result)
            if result.state == "FAILURE":
                response["traceback"] = result.traceback
        return response

    async def task_abort(self, task_id: str) -> str:
        if self.mock_mode:
            self.mock.revoke(task_id, terminate=True)
            return f"Aborted '{task_id}'"

        from celery.contrib.abortable import AbortableAsyncResult

        if not self.backend_configured():
            raise ControlError("Result backend is not configured", 503)
        result = AbortableAsyncResult(task_id, app=self.capp)
        await self._run(result.abort)
        return f"Aborted '{task_id}'"


manager = ServiceManager()
