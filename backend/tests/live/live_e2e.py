"""真实服务端到端自测：对运行中的 FlowerUI 发起真实 HTTP / WebSocket 请求。

用法（另开终端先启动服务，或 .\\dev-restart.ps1 -Mock）:
    cd backend
    python tests/live/live_e2e.py [base_url] [--user admin --password admin123]

覆盖：静态资源与文档、查询类接口、Prometheus 指标、Worker 控制（solo 池自动
降级为 SKIP）、任务下发与控制、任务查询（过滤/排序/搜索/分页）、错误处理、
WebSocket 实时推送、配置/主题/审计等管理面。

退出码：0 = 全部通过（允许 SKIP），1 = 有失败。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Tuple

BASE = "http://127.0.0.1:5555"
USER = "admin"
PASSWORD = "admin123"


def _parse_args() -> None:
    global BASE, USER, PASSWORD
    args = sys.argv[1:]
    positional = []
    i = 0
    while i < len(args):
        if args[i] == "--user":
            USER = args[i + 1]
            i += 2
        elif args[i] == "--password":
            PASSWORD = args[i + 1]
            i += 2
        else:
            positional.append(args[i])
            i += 1
    if positional:
        BASE = positional[0]


TOKEN: str = ""
_ok = 0
_fail = 0
_skip = 0
_failed: list = []


def req(method: str, path: str, body: Any = None, *, timeout: float = 30, auth: bool = True) -> Tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    if auth and TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "ignore")
            try:
                return resp.status, json.loads(raw)
            except ValueError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw
    except Exception as e:  # noqa: BLE001
        return -1, repr(e)


def check(label: str, cond: bool, extra: str = "") -> None:
    global _ok, _fail
    if cond:
        _ok += 1
        print("  PASS  " + label + (" " + extra if extra else ""))
    else:
        _fail += 1
        _failed.append(label)
        print("  FAIL  " + label + (" " + extra if extra else ""))


def skip(label: str, why: str = "") -> None:
    global _skip
    _skip += 1
    print("  SKIP  " + label + (" (" + why + ")" if why else ""))


def section(title: str) -> None:
    print("\n--- " + title + " ---")


def body_of(x: Any) -> Any:
    return x if isinstance(x, (dict, list)) else {"_raw": x}


def main() -> int:
    global TOKEN
    print("FlowerUI 真实服务 E2E | base=" + BASE)
    section("启动与认证")
    s, d = req("GET", "/health", auth=False)
    check("GET /health", s == 200)
    s, d = req("GET", "/api/auth/config", auth=False)
    auth_enabled = isinstance(d, dict) and d.get("auth_enabled")
    check("GET /api/auth/config", s == 200, "auth_enabled=%s" % auth_enabled)
    if auth_enabled:
        s, d = req("POST", "/api/auth/login", {"username": USER, "password": PASSWORD}, auth=False)
        if s == 200 and isinstance(d, dict) and d.get("access_token"):
            TOKEN = d["access_token"]
            check("登录 %s" % USER, True, "role=%s" % d.get("role"))
        else:
            check("登录 %s" % USER, False, "s=%s %s" % (s, str(d)[:80]))
            print("登录失败，后续受保护接口无法验证，提前结束。")
            return 1
    else:
        check("免鉴权模式", True)

    section("静态资源与文档")
    for path in ("/", "/docs", "/redoc", "/openapi.json"):
        s, _ = req("GET", path, auth=False)
        check(path, s == 200, "-> %s" % s)

    section("查询类接口")
    query_paths = [
        "/api/system",
        "/api/workers",
        "/api/workers/table",
        "/api/tasks?limit=3",
        "/api/tasks/table?limit=3",
        "/api/task/types",
        "/api/task/registered",
        "/api/queues/length",
        "/api/broker",
        "/api/dashboard/summary",
        "/api/dashboard/timeline?limit=5",
        "/api/dashboard/filters",
        "/api/dashboard/task-distribution?top=5",
        "/api/beats",
        "/api/alerts/status",
        "/healthcheck",
    ]
    for path in query_paths:
        s, _ = req("GET", path)
        check(path, s == 200, "-> %s" % s)

    section("Prometheus 指标")
    s, text = req("GET", "/metrics", auth=False)
    names = {
        line.split("{")[0].split(" ")[0]
        for line in str(text).splitlines()
        if line.startswith("flower_")
    }
    check("/metrics 可访问", s == 200)
    for m in ("flower_events_total", "flower_worker_online"):
        check("指标 " + m, any(n.startswith(m) for n in names))

    section("Worker 控制")
    s, table = req("GET", "/api/workers/table")
    online = [r["name"] for r in body_of(table).get("data", []) if r["status"]]
    check("存在在线 worker", bool(online), "共 %d 个" % len(online))
    if not online:
        skip("worker 控制类", "无在线 worker")
        print_summary()
        return 1
    worker = online[0]
    wq = urllib.parse.quote(worker)
    s, detail = req("GET", "/api/worker/" + wq)
    detail = body_of(detail)
    check("worker 详情", s == 200, "并发=%s" % body_of(detail.get("pool")).get("max-concurrency"))
    for key in ("pool", "broker", "rusage", "active_queues", "registered", "conf", "total"):
        check("详情字段 " + key, key in detail)
    pool_impl = str(body_of(detail.get("pool")).get("implementation") or "").lower()
    elastic = "solo" not in pool_impl
    if not elastic:
        for label in ("pool grow", "pool shrink", "autoscale", "pool restart"):
            skip(label, "pool=%s 不支持动态伸缩" % (pool_impl or "solo"))
    else:
        before = body_of(detail["pool"]).get("max-concurrency")
        check("pool grow", req("POST", f"/api/worker/pool/grow/{wq}?n=3")[0] == 200)
        _, d2 = req("GET", "/api/worker/" + wq)
        after = body_of(body_of(d2)["pool"]).get("max-concurrency")
        check("grow 实际生效", after == before + 3, "%s -> %s" % (before, after))
        check("pool shrink", req("POST", f"/api/worker/pool/shrink/{wq}?n=3")[0] == 200)
        _, d3 = req("GET", "/api/worker/" + wq)
        check("shrink 实际生效", body_of(body_of(d3)["pool"]).get("max-concurrency") == before)
        check("autoscale", req("POST", f"/api/worker/pool/autoscale/{wq}?min=2&max=12")[0] == 200)
        check("pool restart", req("POST", f"/api/worker/pool/restart/{wq}")[0] == 200)
    # 队列消费（threads/solo 池都支持）
    check("add-consumer", req("POST", f"/api/worker/queue/add-consumer/{wq}?queue=zz_e2e")[0] == 200)
    time.sleep(1.0)
    _, dw = req("GET", "/api/worker/" + wq)
    queues = [q["name"] for q in body_of(dw).get("active_queues", [])]
    check("队列已加入订阅", "zz_e2e" in queues, str(queues))
    check("cancel-consumer", req("POST", f"/api/worker/queue/cancel-consumer/{wq}?queue=zz_e2e")[0] == 200)
    time.sleep(1.0)
    _, dw = req("GET", "/api/worker/" + wq)
    queues = [q["name"] for q in body_of(dw).get("active_queues", [])]
    check("队列已移除", "zz_e2e" not in queues, str(queues))

    section("任务下发与控制")
    s, reg = req("GET", "/api/task/registered")
    reg = body_of(reg)
    tasks = reg.get("tasks", [])
    check("注册任务列表", s == 200 and bool(tasks), str(tasks[:3]))
    if not tasks:
        skip("任务下发类", "worker 未注册任务")
    else:
        t_send = next((t for t in tasks if t.endswith("send_email")), tasks[0])
        t_resize = next((t for t in tasks if t.endswith("resize_image")), tasks[-1])
        s, res = req("POST", f"/api/task/async-apply/{t_send}", {"args": ["x@y.com"], "kwargs": {"template": "welcome"}})
        res = body_of(res)
        check("async-apply", s == 200 and res.get("task-id"), "id=%s" % str(res.get("task-id"))[:8])
        task_id = res.get("task-id")
        if task_id:
            s, info = 0, {}
            deadline = time.time() + 30
            while time.time() < deadline:
                s, info = req("GET", f"/api/task/info/{task_id}")
                if s == 200:
                    break
                time.sleep(1.0)
            info = body_of(info)
            check("task info", s == 200, "state=%s" % info.get("state"))
            check("info 含 children_tasks", "children_tasks" in info)
            check("revoke + terminate", req("POST", f"/api/task/revoke/{task_id}?terminate=true")[0] == 200)
            check("task abort", req("POST", f"/api/task/abort/{task_id}")[0] in (200, 403, 503))
        s, res = req("POST", f"/api/task/send-task/{t_resize}", {"args": ["s3://a.jpg"]})
        check("send-task（按名投递）", s == 200 and body_of(res).get("task-id"))
        has_backend = bool(body_of(req("GET", "/api/system")[1]).get("result_backend_configured"))
        if not has_backend:
            skip("apply（同步等待）", "未配置 result backend（FLOWER_RESULT_BACKEND）")
        else:
            s, res = req("POST", f"/api/task/apply/{t_resize}?timeout=60", {"args": ["s3://a.jpg"]}, timeout=70)
            res = body_of(res)
            check("apply（同步等待）", s == 200, "state=%s" % res.get("state"))
            if s == 200 and res.get("task-id"):
                check("task result", req("GET", f"/api/task/result/{res['task-id']}")[0] == 200)
        check("rate-limit", req("POST", f"/api/task/rate-limit/{t_send}?workername={wq}&ratelimit=20/m")[0] == 200)
        check("time-limit", req("POST", f"/api/task/timeout/{t_send}?workername={wq}&soft=15&hard=30")[0] == 200)

    section("任务查询：过滤 / 排序 / 搜索 / 分页")
    s, data = req("GET", "/api/tasks/table?limit=5&state=SUCCESS")
    data = body_of(data)
    check("按状态过滤", s == 200 and all(r["state"] == "SUCCESS" for r in data.get("data", [])),
          "total=%s" % data.get("total"))
    s, data = req("GET", f"/api/tasks/table?limit=5&workername={wq}")
    check("按 worker 过滤", s == 200, "total=%s" % body_of(data).get("total"))
    s, data = req("GET", "/api/tasks/table?limit=10&sort_by=-runtime")
    runtimes = [r["runtime"] for r in body_of(data).get("data", []) if r["runtime"] is not None]
    check("按耗时倒序", s == 200 and runtimes == sorted(runtimes, reverse=True))
    for term in ("state:SUCCESS", "state:FAILURE", "args:", "kwargs:"):
        s, data = req("GET", "/api/tasks/table?limit=2&search=" + urllib.parse.quote(term))
        check("搜索 " + term, s == 200, "total=%s" % body_of(data).get("total"))
    p1 = [r["uuid"] for r in body_of(req("GET", "/api/tasks/table?limit=3&offset=0")[1]).get("data", [])]
    p2 = [r["uuid"] for r in body_of(req("GET", "/api/tasks/table?limit=3&offset=3")[1]).get("data", [])]
    check("分页不重叠", not set(p1) & set(p2))

    section("管理面：配置 / 主题 / 审计")
    s, d = req("GET", "/api/config/ui", auth=False)
    check("GET /api/config/ui（免鉴权）", s == 200 and isinstance(d, dict))
    s, d = req("GET", "/api/config")
    d = body_of(d)
    check("GET /api/config", s == 200 and isinstance(d, dict), "items=%s" % len(d.get("items", [])))
    if s == 200:
        keys = [x["key"] for x in d.get("items", [])]
        check("配置含 basic_auth", "basic_auth" in keys)
        secret_vals = {x["key"]: x.get("value") for x in d.get("items", []) if x.get("secret")}
        for k, v in secret_vals.items():
            text = "" if v is None else str(v)
            # 掩码策略（与 runtime_config._mask 一致）：含凭据段的 URL 必须打码
            # 密码段；无凭据的 URL 本身不敏感可原样；纯密钥整体打码或留空。
            if "://" in text:
                ok = True if "@" not in text else "******" in text
            else:
                ok = v in (None, "") or "******" in text
            check("secret 字段已脱敏 " + k, ok, "-> " + text[:40])
    s, d = req("POST", "/api/config/materialize")
    check("POST /api/config/materialize", s == 200 and body_of(d).get("ok") is True)
    s, d = req("GET", "/api/themes")
    check("GET /api/themes", s == 200 and {"themes", "dir"} <= set(body_of(d)))
    s, d = req("GET", "/api/audit?limit=5")
    d = body_of(d)
    check("GET /api/audit", s == 200 and d.get("total", 0) > 0, "total=%s" % d.get("total"))
    s, d = req("GET", "/api/auth/login-logs?limit=5")
    check("GET /api/auth/login-logs", s == 200 and isinstance(body_of(d).get("items"), list))

    section("错误处理")
    check("未知 worker -> 404", req("POST", "/api/worker/pool/grow/nonexistent-worker?n=1")[0] == 404)
    check("未知任务 -> 404", req("GET", "/api/task/info/deadbeef-not-exist")[0] == 404)
    check("未知 API -> 404 JSON", req("GET", "/api/definitely-not-here")[0] == 404)
    if auth_enabled:
        check("无 token 受保护接口 -> 401", req("GET", "/api/config", auth=False)[0] == 401)

    section("WebSocket 实时推送")
    try:
        import asyncio
        import websockets

        async def ws_check():
            results = {}
            qs = ("?token=" + urllib.parse.quote(TOKEN)) if TOKEN else ""
            ws_url = BASE.replace("http", "ws", 1) + "/ws/events" + qs
            async with websockets.connect(ws_url) as ws:
                got_snapshot = False
                for _ in range(50):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                    if msg.get("type") == "snapshot":
                        got_snapshot = True
                        results["snapshot"] = bool(
                            msg.get("summary") and msg.get("workers") is not None and msg.get("timeline") is not None
                        )
                        break
                results["got_snapshot"] = got_snapshot
                for payload in ({"action": "ping"}, {"type": "ping"}):
                    await ws.send(json.dumps(payload))
                    got = False
                    for _ in range(20):
                        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                        if msg.get("type") == "pong":
                            got = True
                            break
                    results["pong_" + str(payload)] = got
            return results

        ws_res = asyncio.run(ws_check())
        check("WS 连接 + snapshot 首屏推送", ws_res.get("got_snapshot", False))
        check("WS snapshot 结构完整", ws_res.get("snapshot", False))
        check("WS 心跳 {action:ping} -> pong", ws_res.get("pong_{'action': 'ping'}", False))
        check("WS 心跳 {type:ping} -> pong（兼容）", ws_res.get("pong_{'type': 'ping'}", False))
    except Exception as exc:  # noqa: BLE001
        check("WebSocket 测试", False, "异常: %r" % exc)

    print_summary()
    return 1 if _fail else 0


def print_summary() -> None:
    print("\n" + "=" * 56)
    print("结果：%d 通过 / %d 失败 / %d 跳过" % (_ok, _fail, _skip))
    if _failed:
        print("失败项：")
        for label in _failed:
            print("  - " + label)
    print("=" * 56)


if __name__ == "__main__":
    _parse_args()
    sys.exit(main())
