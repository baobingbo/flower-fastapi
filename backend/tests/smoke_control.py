"""演示模式下的控制面 / 任务下发端到端冒烟测试。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from flowerui.main import app  # noqa: E402


def show(label, value, limit=240):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    print(f"[{label}] {text[:limit]}")


def main() -> int:
    failures = []
    with TestClient(app) as c:
        rows = c.get("/api/workers/table").json()["data"]
        show("workers", [(r["name"], r["status"]) for r in rows])
        online = [r["name"] for r in rows if r["status"]]
        assert online, "没有在线 worker"
        w = online[0]

        d = c.get(f"/api/worker/{w}").json()
        show("worker.detail.keys", sorted(d.keys()))
        show("worker.pool", {"concurrency": d["pool"].get("max-concurrency"),
                             "queues": [q["name"] for q in d["active_queues"]],
                             "conf_keys": len(d["conf"]), "rusage": len(d["rusage"])})

        checks = [
            ("pool.grow", c.post(f"/api/worker/pool/grow/{w}?n=2")),
            ("pool.shrink", c.post(f"/api/worker/pool/shrink/{w}?n=1")),
            ("pool.restart", c.post(f"/api/worker/pool/restart/{w}")),
            ("pool.autoscale", c.post(f"/api/worker/pool/autoscale/{w}?min=2&max=10")),
            ("queue.add", c.post(f"/api/worker/queue/add-consumer/{w}?queue=newq")),
            ("queue.cancel", c.post(f"/api/worker/queue/cancel-consumer/{w}?queue=newq")),
            ("task.rate-limit",
             c.post(f"/api/task/rate-limit/app.tasks.send_email?workername={w}&ratelimit=10/m")),
            ("task.timeout",
             c.post(f"/api/task/timeout/app.tasks.send_email?workername={w}&soft=30&hard=60")),
        ]
        for label, resp in checks:
            show(label, f"{resp.status_code} {resp.text}")
            if resp.status_code != 200:
                failures.append(label)

        r = c.post("/api/task/send-task/app.tasks.send_email",
                   json={"args": ["a@b.com"], "kwargs": {"template": "welcome"}})
        show("send-task", f"{r.status_code} {r.text}")
        tid = r.json()["task-id"]

        show("task.info", c.get(f"/api/task/info/{tid}").json())
        show("task.revoke", c.post(f"/api/task/revoke/{tid}?terminate=true").json())

        r = c.post("/api/task/apply/app.tasks.resize_image?timeout=12",
                   json={"args": ["s3://bucket/x.jpg"], "kwargs": {"width": 800}})
        show("task.apply", f"{r.status_code} {r.text}")
        applied = r.json().get("task-id")
        if r.json().get("state") not in ("SUCCESS", "FAILURE", "RETRY", "REVOKED"):
            failures.append("task.apply 未等到终态")

        show("task.result", c.get(f"/api/task/result/{applied}").json())
        show("task.abort", c.post(f"/api/task/abort/{tid}").json())

        r = c.post("/api/task/async-apply/app.tasks.charge_order", json={"args": [1]})
        show("task.async-apply", f"{r.status_code} {r.text}")

        show("unknown.worker", c.post("/api/worker/pool/grow/nope?n=1").status_code)
        show("unknown.task", c.get("/api/task/info/does-not-exist").status_code)

        show("search.state", c.get("/api/tasks/table?search=state:SUCCESS&limit=2").json()["total"])
        show("filter.state", c.get("/api/tasks/table?state=FAILURE&limit=2").json()["total"])
        show("sort", [t["name"] for t in
                      c.get("/api/tasks/table?sort_by=name&limit=3").json()["data"]])
        show("queues.length", c.get("/api/queues/length").json())

        show("worker.shutdown", c.post(f"/api/worker/shutdown/{w}").json())
        after = c.get("/api/workers/table").json()["data"]
        show("workers.after", [(x["name"], x["status"]) for x in after])

        # WebSocket
        with c.websocket_connect("/ws/events") as ws:
            first = ws.receive_json()
            show("ws.snapshot", {"type": first["type"],
                                 "workers": len(first["workers"]),
                                 "summary_keys": len(first["summary"])})
            ws.send_json({"action": "ping"})
            for _ in range(5):
                msg = ws.receive_json()
                if msg.get("type") == "pong":
                    show("ws.pong", msg)
                    break

    print("\n=== 失败项:", failures or "无")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
