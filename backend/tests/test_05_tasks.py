"""任务：下发（同步/异步/按名/重试/撤销/中止）、结果、查询（过滤/排序/搜索/分页）。"""
from __future__ import annotations

import time


def test_registered_tasks(client, admin_headers, mock_task):
    reg = client.get("/api/task/registered", headers=admin_headers).json()
    assert mock_task in reg["tasks"]
    assert reg["queues"]
    # 任务→队列联动信息
    detail = {t["name"]: t["queue"] for t in reg["tasks_detail"]}
    assert all(q for q in detail.values())


def test_task_types_and_queues(client, admin_headers):
    r = client.get("/api/task/types", headers=admin_headers)
    assert r.status_code == 200 and r.json()["task-types"]
    r = client.get("/api/queues/length", headers=admin_headers)
    assert r.status_code == 200


def test_async_apply_and_lifecycle(client, admin_headers):
    r = client.post(
        "/api/task/async-apply/app.tasks.send_email",
        json={"args": ["life@y.com"], "kwargs": {"template": "welcome"}},
        headers=admin_headers,
    )
    assert r.status_code == 200
    tid = r.json()["task-id"]
    assert tid
    # 任务信息（mock 下事件几乎即时）
    deadline = time.time() + 10
    info_status = 0
    while time.time() < deadline:
        info_status = client.get("/api/task/info/" + tid, headers=admin_headers).status_code
        if info_status == 200:
            break
        time.sleep(0.5)
    assert info_status == 200
    info = client.get("/api/task/info/" + tid, headers=admin_headers).json()
    assert "state" in info and "children_tasks" in info
    # 撤销 + 终止
    assert client.post("/api/task/revoke/" + tid + "?terminate=true", headers=admin_headers).status_code == 200
    # 中止（已撤销任务也应有确定性响应）
    assert client.post("/api/task/abort/" + tid, headers=admin_headers).status_code in (200, 403, 503)


def test_apply_sync(client, admin_headers):
    r = client.post(
        "/api/task/apply/app.tasks.resize_image?timeout=15",
        json={"args": ["s3://bucket/x.jpg"], "kwargs": {"width": 800}},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body.get("state") in ("SUCCESS", "FAILURE", "RETRY", "REVOKED")
    if body.get("state") == "SUCCESS":
        assert "result" in body
    # 结果回查
    tid = body.get("task-id")
    if tid:
        assert client.get("/api/task/result/" + tid, headers=admin_headers).status_code == 200


def test_send_task_by_name(client, admin_headers):
    r = client.post(
        "/api/task/send-task/app.tasks.charge_order",
        json={"args": [1]},
        headers=admin_headers,
    )
    assert r.status_code == 200 and r.json().get("task-id")


def test_task_retry(client, admin_headers):
    r = client.post(
        "/api/task/async-apply/app.tasks.send_email", json={"args": ["retry@y.com"]},
        headers=admin_headers,
    )
    tid = r.json()["task-id"]
    time.sleep(1.0)  # 等任务进入状态内存
    r2 = client.post("/api/task/retry/" + tid, headers=admin_headers)
    assert r2.status_code == 200
    assert r2.json().get("task-id") != tid
    # 未知任务 → 404
    assert client.post("/api/task/retry/does-not-exist", headers=admin_headers).status_code == 404


def test_unknown_task_404(client, admin_headers):
    assert client.get("/api/task/info/deadbeef-not-exist", headers=admin_headers).status_code == 404


def test_rate_limit_and_timeout(client, admin_headers, mock_worker):
    import urllib.parse

    w = urllib.parse.quote(mock_worker)
    assert client.post(
        f"/api/task/rate-limit/app.tasks.send_email?workername={w}&ratelimit=10/m", headers=admin_headers
    ).status_code == 200
    assert client.post(
        f"/api/task/timeout/app.tasks.send_email?workername={w}&soft=15&hard=30", headers=admin_headers
    ).status_code == 200
    # soft 与 hard 都缺 → 400
    assert client.post(
        f"/api/task/timeout/app.tasks.send_email?workername={w}", headers=admin_headers
    ).status_code == 400


def test_tasks_table_filter_sort_search(client, admin_headers):
    # 状态过滤
    r = client.get("/api/tasks/table?limit=5&state=SUCCESS", headers=admin_headers).json()
    assert all(x["state"] == "SUCCESS" for x in r["data"])
    # worker 过滤
    r = client.get("/api/tasks/table?limit=5", headers=admin_headers).json()
    assert r["total"] > 0
    # 排序：按耗时倒序
    r = client.get("/api/tasks/table?limit=10&sort_by=-runtime", headers=admin_headers).json()
    rts = [x["runtime"] for x in r["data"] if x["runtime"] is not None]
    assert rts == sorted(rts, reverse=True)
    # 分页不重叠
    p1 = [x["uuid"] for x in client.get("/api/tasks/table?limit=3&offset=0", headers=admin_headers).json()["data"]]
    p2 = [x["uuid"] for x in client.get("/api/tasks/table?limit=3&offset=3", headers=admin_headers).json()["data"]]
    assert not set(p1) & set(p2)
    # 搜索 DSL
    for term in ("state:SUCCESS", "state:FAILURE", "args:", "kwargs:"):
        r = client.get("/api/tasks/table?limit=2&search=" + term.replace(":", "%3A"), headers=admin_headers)
        assert r.status_code == 200


def test_tasks_export_and_timeline(client, admin_headers):
    assert client.get("/api/tasks/export?limit=10", headers=admin_headers).status_code == 200
    assert client.get("/api/tasks/timeline?limit=10", headers=admin_headers).status_code == 200


def test_dag(client, admin_headers):
    r = client.get("/api/dag/tasks?limit=10", headers=admin_headers)
    assert r.status_code == 200
