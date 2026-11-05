"""端到端验证：对运行中的 FlowerUI 服务发起真实 HTTP / WebSocket 请求。

用法：
    python -m uvicorn flowerui.main:app --port 5555   # 另开终端启动服务
    python tests/e2e_check.py [base_url]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5555"

_ok = 0
_fail = 0
_failed_labels: list[str] = []


def req(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    request = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")[:160]


_skipped = 0


def check(label: str, cond: bool, extra: str = "") -> None:
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  PASS  {label} {extra}")
    else:
        _fail += 1
        _failed_labels.append(label)
        print(f"  FAIL  {label} {extra}")


def skip(label: str, why: str) -> None:
    global _skipped
    _skipped += 1
    print(f"  SKIP  {label} （{why}）")


def section(title: str) -> None:
    print(f"\n--- {title} ---")


# ----------------------------------------------------------------------
# 运行环境探测：演示模式与真实集群的任务名、pool 能力都不同，脚本需自适应。
# ----------------------------------------------------------------------
_, _system = req("GET", "/api/system")
MOCK_MODE = bool(_system.get("mock_mode")) if isinstance(_system, dict) else True
_, _reg = req("GET", "/api/task/registered")
REGISTERED = _reg.get("tasks", []) if isinstance(_reg, dict) else []


def task_named(suffix: str, fallback: str) -> str:
    """按后缀在 worker 已注册任务里找真实任务名（演示/真实模式前缀不同）。"""
    for name in REGISTERED:
        if name.split(".")[-1] == suffix:
            return name
    return fallback


T_SEND_EMAIL = task_named("send_email", "app.tasks.send_email")
T_CUSTOM_JOB = task_named("custom_job", "app.tasks.custom_job")
T_RESIZE = task_named("resize_image", "app.tasks.resize_image")

print(f"运行模式: {'演示' if MOCK_MODE else '真实集群'} | 目标: {BASE}")
print(f"任务样本: {T_SEND_EMAIL} / {T_CUSTOM_JOB} / {T_RESIZE}")

section("静态资源与文档")
for path in ["/", "/docs", "/redoc", "/openapi.json"]:
    status, _ = req("GET", path)
    check(path, status == 200, f"-> {status}")

section("查询类接口")
QUERY_PATHS = [
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
    "/api/system",
    "/api/auth/config",
    "/healthcheck",
]
for path in QUERY_PATHS:
    status, _ = req("GET", path)
    check(path, status == 200, f"-> {status}")

section("Prometheus 指标")
status, text = req("GET", "/metrics")
metric_names = {
    line.split("{")[0].split(" ")[0]
    for line in str(text).splitlines()
    if line.startswith("flower_")
}
check("/metrics 可访问", status == 200)
for name in [
    "flower_events_total",
    "flower_task_runtime_seconds_bucket",
    "flower_worker_online",
    "flower_worker_number_of_currently_executing_tasks",
    "flower_worker_prefetched_tasks",
]:
    check(f"指标 {name}", any(n.startswith(name) for n in metric_names))

section("Worker 控制")
status, table = req("GET", "/api/workers/table")
online = [r["name"] for r in table["data"] if r["status"]]
check("存在在线 worker", bool(online), f"共 {len(online)} 个")
worker = online[0]
wq = urllib.parse.quote(worker)

status, detail = req("GET", f"/api/worker/{wq}")
check("worker 详情", status == 200, f"并发={detail.get('pool', {}).get('max-concurrency')}")
for key in ["pool", "broker", "rusage", "active_queues", "registered", "conf", "total"]:
    check(f"详情字段 {key}", key in detail)

POOL_IMPL = str(detail.get("pool", {}).get("implementation") or "").lower()
# solo 池是单线程、无子进程的实现，celery 本身就不提供 grow/shrink/autoscale/restart。
ELASTIC_POOL = "solo" not in POOL_IMPL

if not ELASTIC_POOL:
    why = f"pool={POOL_IMPL or 'solo'} 不支持动态伸缩"
    for label in ("pool grow", "grow 实际生效", "pool shrink", "shrink 实际生效",
                  "autoscale", "pool restart"):
        skip(label, why)
else:
    before = detail["pool"]["max-concurrency"]
    status, _ = req("POST", f"/api/worker/pool/grow/{wq}?n=3")
    check("pool grow", status == 200)
    status, detail = req("GET", f"/api/worker/{wq}")
    after = detail["pool"]["max-concurrency"]
    check("grow 实际生效", after == before + 3, f"{before} -> {after}")

    status, _ = req("POST", f"/api/worker/pool/shrink/{wq}?n=3")
    check("pool shrink", status == 200)
    status, detail = req("GET", f"/api/worker/{wq}")
    check("shrink 实际生效", detail["pool"]["max-concurrency"] == before,
          f"{after} -> {detail['pool']['max-concurrency']}")

    status, _ = req("POST", f"/api/worker/pool/autoscale/{wq}?min=2&max=12")
    check("autoscale", status == 200)

    status, _ = req("POST", f"/api/worker/pool/restart/{wq}")
    check("pool restart", status == 200)

status, _ = req("POST", f"/api/worker/queue/add-consumer/{wq}?queue=zz_e2e")
check("add-consumer", status == 200)
status, detail = req("GET", f"/api/worker/{wq}")
check("队列已加入订阅", "zz_e2e" in [q["name"] for q in detail["active_queues"]])

status, _ = req("POST", f"/api/worker/queue/cancel-consumer/{wq}?queue=zz_e2e")
check("cancel-consumer", status == 200)
status, detail = req("GET", f"/api/worker/{wq}")
check("队列已移除", "zz_e2e" not in [q["name"] for q in detail["active_queues"]])

section("任务下发与控制")


def body_of(res):
    """接口失败时 req() 返回错误文本，这里统一成 dict 便于取字段。"""
    return res if isinstance(res, dict) else {}


status, res = req("POST", f"/api/task/async-apply/{T_SEND_EMAIL}",
                  {"args": ["x@y.com"], "kwargs": {"template": "welcome"}})
res = body_of(res)
check("async-apply", status == 200, f"id={str(res.get('task-id'))[:8]}")
task_id = res.get("task-id")

if task_id:
    # 真实集群里任务要先排队，事件到达有延迟；轮询等待而不是死等固定秒数。
    status, info = 0, {}
    deadline = time.time() + 30
    while time.time() < deadline:
        status, info = req("GET", f"/api/task/info/{task_id}")
        if status == 200:
            break
        time.sleep(1.0)
    info = body_of(info)
    check("task info", status == 200, f"state={info.get('state')}")
    check("info 含 children_tasks", "children_tasks" in info)

    status, res = req("POST", f"/api/task/revoke/{task_id}?terminate=true")
    check("revoke + terminate", status == 200)
else:
    for label in ("task info", "info 含 children_tasks", "revoke + terminate"):
        skip(label, "async-apply 未返回 task-id")

status, res = req("POST", f"/api/task/send-task/{T_CUSTOM_JOB}", {"args": [1, 2]})
check("send-task（未注册任务名）", status == 200)

_, _sys2 = req("GET", "/api/system")
HAS_BACKEND = bool(body_of(_sys2).get("result_backend_configured"))
if not HAS_BACKEND:
    skip("apply（同步等待）", "未配置 result backend（FLOWER_RESULT_BACKEND）")
    skip("task result", "未配置 result backend（FLOWER_RESULT_BACKEND）")
else:
    status, res = req("POST", f"/api/task/apply/{T_RESIZE}?timeout=60",
                      {"args": ["s3://a.jpg"]})
    res = body_of(res)
    check("apply（同步等待）", status == 200, f"state={res.get('state')}")
    if status == 200 and res.get("task-id"):
        status, _ = req("GET", f"/api/task/result/{res['task-id']}")
        check("task result", status == 200)
    else:
        skip("task result", "apply 未返回 task-id")

status, _ = req("POST", f"/api/task/rate-limit/{T_SEND_EMAIL}?workername={wq}&ratelimit=20/m")
check("rate-limit", status == 200)
status, _ = req("POST", f"/api/task/timeout/{T_SEND_EMAIL}?workername={wq}&soft=15&hard=30")
check("time-limit", status == 200)

section("任务查询：过滤 / 排序 / 搜索 DSL")
status, data = req("GET", "/api/tasks/table?limit=5&state=SUCCESS")
check("按状态过滤", status == 200 and all(r["state"] == "SUCCESS" for r in data["data"]),
      f"total={data.get('total')}")

status, data = req("GET", f"/api/tasks/table?limit=5&workername={wq}")
check("按 worker 过滤", status == 200, f"total={data.get('total')}")

status, data = req("GET", "/api/tasks/table?limit=5&sort_by=-runtime")
runtimes = [r["runtime"] for r in data["data"] if r["runtime"] is not None]
check("按耗时倒序", status == 200 and runtimes == sorted(runtimes, reverse=True))

for term in ["state:SUCCESS", "state:FAILURE", "result:", "args:", "kwargs:"]:
    status, data = req("GET", f"/api/tasks/table?limit=2&search={urllib.parse.quote(term)}")
    check(f"搜索 {term}", status == 200,
          f"total={data.get('total') if isinstance(data, dict) else '?'}")

status, data = req("GET", "/api/tasks/table?limit=3&offset=0")
first_page = [r["uuid"] for r in data["data"]]
status, data = req("GET", "/api/tasks/table?limit=3&offset=3")
second_page = [r["uuid"] for r in data["data"]]
check("分页不重叠", not set(first_page) & set(second_page))

section("错误处理")
status, _ = req("POST", "/api/worker/pool/grow/nonexistent-worker?n=1")
check("未知 worker -> 404", status == 404, f"-> {status}")
status, _ = req("GET", "/api/task/info/deadbeef-not-exist")
check("未知任务 -> 404", status == 404, f"-> {status}")
status, _ = req("GET", "/api/definitely-not-here")
check("未知 API -> 404 JSON", status == 404, f"-> {status}")

section("WebSocket 实时推送")
try:
    import asyncio
    import websockets

    async def ws_check():
        results: dict = {}
        ws_url = BASE.replace("http", "ws", 1) + "/ws/events"
        async with websockets.connect(ws_url) as ws:
            got_snapshot = False
            for _ in range(50):
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                if msg.get("type") == "snapshot":
                    got_snapshot = True
                    results["snapshot"] = bool(
                        msg.get("summary") and msg.get("workers") is not None
                        and msg.get("timeline") is not None
                    )
                    break
            results["got_snapshot"] = got_snapshot
            await ws.send(json.dumps({"action": "ping"}))
            pong1 = False
            for _ in range(20):
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                if msg.get("type") == "pong":
                    pong1 = True
                    break
            results["pong_action"] = pong1
            await ws.send(json.dumps({"type": "ping"}))
            pong2 = False
            for _ in range(20):
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                if msg.get("type") == "pong":
                    pong2 = True
                    break
            results["pong_type"] = pong2
        return results

    ws_res = asyncio.run(ws_check())
    check("WS 连接 + snapshot 首屏推送", ws_res.get("got_snapshot", False))
    check("WS snapshot 结构完整", ws_res.get("snapshot", False))
    check("WS 心跳 ping{action} -> pong", ws_res.get("pong_action", False))
    check("WS 心跳 ping{type} -> pong(兼容)", ws_res.get("pong_type", False))
except Exception as exc:  # pragma: no cover
    check("WebSocket 测试", False, f"异常: {exc!r}")

# ----------------------------------------------------------------------
print("\n" + "=" * 52)
print(
    f"结果：{_ok} 通过 / {_fail} 失败 / {_skipped} 跳过"
    f"　（模式：{'演示' if MOCK_MODE else '真实集群'}）"
)
if _failed_labels:
    print("失败项：")
    for label in _failed_labels:
        print(f"  - {label}")
print("=" * 52)
sys.exit(1 if _fail else 0)
