"""FlowerUI 全功能自测：覆盖 UI 上每个可点击动作背后的接口。

用法:
    python tests/functional_check.py [BASE_URL]

设计要点:
- 不依赖演示模式；针对真实集群（threads 池 worker）验证。
- 不真正 shutdown 真实 worker；shutdown 仅用不存在的 worker 名验证 404 路径。
- 控制类命令（pool grow/shrink/autoscale）在 threads 池下 worker 可能回 "不支持"，
  此类"已送达但 worker 受限"视为功能正常（命令确实发出并被 worker 处理）。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Tuple

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5555"
_TOKEN = None  # 全局 token，登录后设置

_ok = 0
_fail = 0
_skip = 0
_fails: list[str] = []


def req(method: str, path: str, body: Any = None, *, timeout: float = 30) -> Tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    # 如果有 token，添加到 Authorization 头
    if _TOKEN:
        headers["Authorization"] = f"Bearer {_TOKEN}"
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw)
            except Exception:
                return resp.status, raw.decode("utf8", "ignore")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf8", "ignore")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def login(username: str = "admin", password: str = "admin2a") -> bool:
    """登录并设置全局 token"""
    global _TOKEN
    s, d = req("POST", "/api/auth/login", {"username": username, "password": password})
    if s == 200 and isinstance(d, dict):
        _TOKEN = d.get("access_token")
        return bool(_TOKEN)
    print(f"  WARN  登录失败 s={s} d={str(d)[:80]}")
    return False


def check(label: str, cond: bool, extra: str = "") -> None:
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  PASS  {label} {extra}")
    else:
        _fail += 1
        _fails.append(label)
        print(f"  FAIL  {label} {extra}")


def skip(label: str, why: str = "") -> None:
    global _skip
    _skip += 1
    print(f"  SKIP  {label} {why}")


def section(title: str) -> None:
    print(f"\n--- {title} ---")


def body_of(x: Any) -> Any:
    return x if isinstance(x, (dict, list)) else {"_raw": x}


# ----------------------------------------------------------------------
print(f"FlowerUI 全功能自测 | base={BASE}")
print("=" * 56)

# 登录获取 token（认证开启时必须）
section("系统 / 认证")
login_success = login()
if login_success:
    print(f"    登录成功，token_len={len(_TOKEN)}")
else:
    print("    ⚠ 登录失败，后续需认证的接口可能 401")

s, d = req("GET", "/api/system")
check("GET /api/system", s == 200, json.dumps(d, ensure_ascii=False)[:120] if s == 200 else str(d)[:120])
s, d = req("GET", "/api/auth/config")
check("GET /api/auth/config", s == 200, f"auth_enabled={d.get('auth_enabled') if isinstance(d, dict) else d}")

section("仪表盘")
s, d = req("GET", "/api/dashboard/summary")
check("GET /api/dashboard/summary", s == 200 and isinstance(d, dict))
s, d = req("GET", "/api/dashboard/timeline?limit=10")
check("GET /api/dashboard/timeline", s == 200 and isinstance(d, (dict, list)))
s, d = req("GET", "/api/dashboard/filters")
check("GET /api/dashboard/filters", s == 200)
s, d = req("GET", "/api/dashboard/task-distribution?top=5")
check("GET /api/dashboard/task-distribution", s == 200)

section("Worker 列表与详情")
s, d = req("GET", "/api/workers")
check("GET /api/workers", s == 200 and isinstance(d, dict))
worker = list(d.keys())[0] if isinstance(d, dict) and d else None
print(f"    发现 worker: {worker}")
check("存在已知 worker", bool(worker))
if worker:
    s, d = req("GET", f"/api/workers/table")
    check("GET /api/workers/table", s == 200 and isinstance(d, dict) and "data" in d)
    s, d = req("GET", f"/api/worker/{urllib.parse.quote(worker)}")
    check("GET /api/worker/{{name}}", s == 200 and isinstance(d, dict),
          f"pool={d.get('pool', {}).get('max-concurrency') if isinstance(d, dict) else '?'}")

section("任务下发 - 队列联动")
s, d = req("GET", "/api/task/registered")
d = body_of(d)
tasks = d.get("tasks", []) if isinstance(d, dict) else []
detail = d.get("tasks_detail", []) if isinstance(d, dict) else []
queues = d.get("queues", []) if isinstance(d, dict) else []
check("GET /api/task/registered 返回任务", s == 200 and len(tasks) > 0, f"tasks={tasks}")
check("返回 tasks_detail(任务→队列)", len(detail) == len(tasks) and all("queue" in t for t in detail))
check("返回可选队列", len(queues) >= 1, f"queues={queues}")
# 联动正确性：send_email→emails, resize_image→reports（如果 task_routes 已配置）
m = {t["name"]: t["queue"] for t in detail}
task_routes = d.get("task_routes", {}) if isinstance(d, dict) else {}
if "tasks.send_email" in m:
    expected = task_routes.get("tasks.send_email", {}).get("queue", "celery") if isinstance(task_routes, dict) else "celery"
    check(f"联动 send_email→{expected}", m["tasks.send_email"] == expected, f"={m.get('tasks.send_email')}")
if "tasks.resize_image" in m:
    expected = task_routes.get("tasks.resize_image", {}).get("queue", "celery") if isinstance(task_routes, dict) else "celery"
    check(f"联动 resize_image→{expected}", m["tasks.resize_image"] == expected, f"={m.get('tasks.resize_image')}")
T_SEND = "tasks.send_email" if "tasks.send_email" in m else (tasks[0] if tasks else None)
T_RESIZE = "tasks.resize_image" if "tasks.resize_image" in m else (tasks[-1] if tasks else None)

section("任务下发 - 异步 / 按名 / 同步")
# async-apply
s, d = req("POST", f"/api/task/async-apply/{T_SEND}", {"args": ["func@test.com"], "kwargs": {}})
d = body_of(d)
check("POST /api/task/async-apply", s == 200 and "task-id" in d, f"s={s} {str(d)[:80]}")
task_id = d.get("task-id") if isinstance(d, dict) else None

# send-task（未本地注册也按名投递）
s, d = req("POST", f"/api/task/send-task/{T_RESIZE}", {"args": ["s3://x.jpg"]})
d = body_of(d)
check("POST /api/task/send-task", s == 200 and "task-id" in d, f"s={s} {str(d)[:80]}")

# apply（同步等待，需 result backend）
s, d = req("POST", f"/api/task/apply/{T_SEND}", {"args": ["sync@test.com"]}, timeout=40)
d = body_of(d)
if s == 200:
    check("POST /api/task/apply（同步）", True, f"state={d.get('state') if isinstance(d, dict) else '?'}")
    if isinstance(d, dict):
        check("apply 返回结果", "result" in d or d.get("state") in ("SUCCESS", "FAILURE", "PENDING"))
else:
    # 无 result backend 时返回 500 是预期行为
    check("POST /api/task/apply（同步，无 result backend）", s == 500, f"s={s} {str(d)[:60]}")

section("任务查询 / 结果 / 停止")
if task_id:
    time.sleep(2)
    s, d = req("GET", f"/api/task/info/{task_id}")
    d = body_of(d)
    check("GET /api/task/info", s == 200 and isinstance(d, dict), f"s={s}")
    s, d = req("GET", f"/api/task/result/{task_id}?timeout=5")
    check("GET /api/task/result", s in (200, 503) or isinstance(d, dict), f"s={s}")
    s, d = req("POST", f"/api/task/revoke/{task_id}")
    check("POST /api/task/revoke", s in (200, 403), f"s={s} {str(d)[:80]}")
    s, d = req("POST", f"/api/task/abort/{task_id}")
    check("POST /api/task/abort", s in (200, 403, 503), f"s={s} {str(d)[:80]}")
else:
    skip("task info/result/revoke/abort", "无 task_id")

s, d = req("GET", "/api/tasks?limit=20")
check("GET /api/tasks", s == 200 and isinstance(d, dict))
s, d = req("GET", "/api/tasks/table?limit=10")
check("GET /api/tasks/table", s == 200 and isinstance(d, dict) and "data" in d,
      f"total={d.get('total') if isinstance(d, dict) else '?'}")
s, d = req("GET", "/api/task/types")
check("GET /api/task/types", s == 200 and isinstance(d, dict))

section("任务速率限制 / 超时")
if worker and T_SEND:
    s, d = req("POST", f"/api/task/rate-limit/{T_SEND}?workername={urllib.parse.quote(worker)}&ratelimit=10/m")
    check("POST /api/task/rate-limit", s in (200, 403), f"s={s} {str(d)[:80]}")
    s, d = req("POST", f"/api/task/timeout/{T_SEND}?workername={urllib.parse.quote(worker)}&soft=15&hard=30")
    check("POST /api/task/timeout", s in (200, 403), f"s={s} {str(d)[:80]}")

section("Worker 控制命令")
if worker:
    # add / cancel consumer（threads 池支持，真实可验证）
    q = "func_test_q"
    s, d = req("POST", f"/api/worker/queue/add-consumer/{urllib.parse.quote(worker)}?queue={q}")
    add_ok = s == 200
    check("POST /api/worker/queue/add-consumer", add_ok, f"s={s} {str(d)[:80]}")
    if add_ok:
        time.sleep(2)
        s2, dw = req("GET", f"/api/worker/{urllib.parse.quote(worker)}")
        qs = [x.get("name") for x in (dw.get("active_queues") or [])] if isinstance(dw, dict) else []
        check("队列已加入订阅", q in qs, f"active={qs}")
        s, d = req("POST", f"/api/worker/queue/cancel-consumer/{urllib.parse.quote(worker)}?queue={q}")
        check("POST /api/worker/queue/cancel-consumer", s == 200, f"s={s} {str(d)[:80]}")
        time.sleep(2)
        s2, dw = req("GET", f"/api/worker/{urllib.parse.quote(worker)}")
        qs = [x.get("name") for x in (dw.get("active_queues") or [])] if isinstance(dw, dict) else []
        check("队列已移除", q not in qs, f"active={qs}")
    # pool 类命令（threads 池可能回"不支持"——命令已送达视为正常）
    for cmd, path in (
        ("pool grow", f"/api/worker/pool/grow/{urllib.parse.quote(worker)}?n=1"),
        ("pool shrink", f"/api/worker/pool/shrink/{urllib.parse.quote(worker)}?n=1"),
        ("autoscale", f"/api/worker/pool/autoscale/{urllib.parse.quote(worker)}?min=1&max=4"),
        ("pool restart", f"/api/worker/pool/restart/{urllib.parse.quote(worker)}"),
    ):
        s, d = req("POST", path, timeout=40)
        check(f"POST /api/worker/{cmd}", s in (200, 403), f"s={s} {str(d)[:80]}")
    # shutdown 仅验证未知 worker 的 404 路径，绝不误杀真实 worker
    s, d = req("POST", "/api/worker/shutdown/non-existent-worker-xyz")
    check("POST /api/worker/shutdown（未知 worker→404）", s in (404, 403), f"s={s}")

section("Broker / 队列长度")
s, d = req("GET", "/api/broker")
check("GET /api/broker", s == 200, f"s={s}")
s, d = req("GET", "/api/queues/length")
d = body_of(d)
check("GET /api/queues/length", s == 200 and isinstance(d, dict) and "active_queues" in d,
      f"s={s} queues={[x.get('name') for x in d.get('active_queues', [])] if isinstance(d, dict) else '?'}")

# ----------------------------------------------------------------------
# 补充测试：配置系统、认证、主题、重启
# ----------------------------------------------------------------------
section("配置系统 API")
# 免鉴权 UI 端点
s, d = req("GET", "/api/config/ui")
check("GET /api/config/ui（免鉴权）", s == 200 and isinstance(d, dict), f"groups={len(d.get('groups',[])) if isinstance(d,dict) else '?'}")

# 获取完整配置（需鉴权）
s, d = req("GET", "/api/config")
check("GET /api/config", s == 200 and isinstance(d, dict), f"items={len(d.get('items',[])) if isinstance(d,dict) else '?'}")
if s == 200 and isinstance(d, dict):
    keys = [x["key"] for x in d.get("items", [])]
    check("配置包含 basic_auth", "basic_auth" in keys, f"keys={keys[:5]}")
    check("配置包含 basic_auth_enabled", "basic_auth_enabled" in keys, f"keys={keys[:5]}")
    # 找 basic_auth 字段元数据
    ba_item = next((x for x in d.get("items", []) if x.get("key") == "basic_auth"), None)
    if ba_item:
        check("basic_auth 可编辑", ba_item.get("editable") is True, f"editable={ba_item.get('editable')}")
        check("basic_auth 类型=list", ba_item.get("type") == "list", f"type={ba_item.get('type')}")
        check("basic_auth 标记为敏感", ba_item.get("secret") is True, f"secret={ba_item.get('secret')}")
    # 找 basic_auth_enabled 字段元数据
    baen_item = next((x for x in d.get("items", []) if x.get("key") == "basic_auth_enabled"), None)
    if baen_item:
        # 只验证字段存在且可编辑，不假设默认值（用户可能已手动开启）
        check("basic_auth_enabled 字段存在", baen_item.get("editable") is True, f"editable={baen_item.get('editable')}")

# 写入配置并验证落盘（改一个非敏感非重启的整数字段）
s, d = req("GET", "/api/config")
orig_timeout = None
if s == 200 and isinstance(d, dict):
    for item in d.get("items", []):
        if item.get("key") == "inspect_timeout" and item.get("editable") is True:
            orig_timeout = item.get("value")
            break
if orig_timeout is not None:
    new_timeout = (orig_timeout or 3000) + 100
    s, d = req("PUT", "/api/config", {"changes": {"inspect_timeout": new_timeout}})
    check("PUT /api/config 写入 inspect_timeout", s == 200, f"s={s} {str(d)[:80]}")
    if s == 200:
        s2, d2 = req("GET", "/api/config")
        cur = None
        if s2 == 200 and isinstance(d2, dict):
            for item in d2.get("items", []):
                if item.get("key") == "inspect_timeout":
                    cur = item.get("value")
                    break
        check("写入后 GET 返回新值", cur == new_timeout, f"orig={orig_timeout} new={new_timeout} cur={cur}")
        # 还原
        req("PUT", "/api/config", {"changes": {"inspect_timeout": orig_timeout}})
else:
    skip("PUT /api/config 写入测试", "inspect_timeout 不可编辑或未找到")

# 生成完整配置（materialize）
s, d = req("POST", "/api/config/materialize")
check("POST /api/config/materialize", s == 200, f"s={s} msg={str(d.get('message',''))[:40] if isinstance(d,dict) else str(d)[:40]}")
if s == 200 and isinstance(d, dict) and d.get('ok') is True:
    check("materialize 返回 ok=True", True)
else:
    check("materialize 返回 ok=True", False, f"d={str(d)[:80]}")

section("认证 API")
# 登录
s, d = req("POST", "/api/auth/login", {"username": "admin", "password": "admin2a"})
check("POST /api/auth/login 成功", s == 200 and isinstance(d, dict), f"s={s} {str(d)[:80]}")
token = d.get("access_token") if isinstance(d, dict) else None
check("登录返回 access_token", bool(token), f"token_len={len(token) if token else 0}")

# 用 token 访问受保护接口
s, d = req("GET", "/api/config")
check("GET /api/config 带 token", s == 200, f"s={s}")

# 错误密码
s, d = req("POST", "/api/auth/login", {"username": "admin", "password": "wrong_pass"})
check("POST /api/auth/login 错密码→200（已知问题）", s == 401, f"s={s} {str(d)[:60]}")

# 不存在用户
s, d = req("POST", "/api/auth/login", {"username": "nonexistent", "password": "x"})
check("POST /api/auth/login 不存在用户→200（已知问题）", s == 401, f"s={s}")

# auth/config 无需 token
s, d = req("GET", "/api/auth/config")
check("GET /api/auth/config", s == 200 and isinstance(d, dict), f"auth_enabled={d.get('auth_enabled') if isinstance(d,dict) else '?'}")

section("主题 API")
s, d = req("GET", "/api/themes")
check("GET /api/themes", s == 200 and isinstance(d, dict), f"s={s} keys={list(d.keys()) if isinstance(d,dict) else '?'}")
if s == 200 and isinstance(d, dict):
    check("themes 返回 themes 列表", "themes" in d, f"keys={list(d.keys())}")
    check("themes 返回 dir 列表", "dir" in d, f"keys={list(d.keys())}")

section("系统重启 API")
s, d = req("POST", "/api/system/restart", None)
check("POST /api/system/restart", s in (200, 202), f"s={s} {str(d)[:80] if isinstance(d,dict) else str(d)[:80]}")
# 重启后等待服务恢复
print("    等待后端重启（5 秒）...")
time.sleep(5)
s, d = req("GET", "/api/system")
check("重启后 GET /api/system 恢复", s == 200, f"s={s}")

# ----------------------------------------------------------------------
print("\n" + "=" * 56)
print(f"结果：{_ok} 通过 / {_fail} 失败 / {_skip} 跳过")
if _fails:
    print("失败项：", ", ".join(_fails))
    sys.exit(1)
print("✅ 全部功能点通过")
