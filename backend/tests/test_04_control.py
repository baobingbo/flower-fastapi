"""Worker 控制面与 Broker：进程池、队列消费、shutdown、broker/队列长度。"""
from __future__ import annotations

import urllib.parse


def _w(name: str) -> str:
    return urllib.parse.quote(name)


def test_workers_list(client, admin_headers):
    d = client.get("/api/workers", headers=admin_headers).json()
    assert isinstance(d, dict) and d
    t = client.get("/api/workers/table", headers=admin_headers).json()
    assert isinstance(t["data"], list) and t["data"]
    assert any(r["status"] for r in t["data"])


def test_worker_detail(client, admin_headers, mock_worker):
    d = client.get("/api/worker/" + _w(mock_worker), headers=admin_headers).json()
    for key in ("pool", "broker", "rusage", "active_queues", "registered", "conf", "total"):
        assert key in d, "详情缺字段 " + key
    assert d["pool"]["max-concurrency"] > 0


def test_unknown_worker_404(client, admin_headers):
    assert client.get("/api/worker/no-such-worker-xyz", headers=admin_headers).status_code == 404
    assert client.post("/api/worker/pool/grow/no-such-worker-xyz?n=1", headers=admin_headers).status_code == 404
    assert client.post("/api/worker/shutdown/no-such-worker-xyz", headers=admin_headers).status_code == 404


def test_pool_control(client, admin_headers, mock_worker):
    w = _w(mock_worker)
    assert client.post(f"/api/worker/pool/grow/{w}?n=2", headers=admin_headers).status_code == 200
    assert client.post(f"/api/worker/pool/shrink/{w}?n=1", headers=admin_headers).status_code == 200
    assert client.post(f"/api/worker/pool/autoscale/{w}?min=2&max=10", headers=admin_headers).status_code == 200
    assert client.post(f"/api/worker/pool/restart/{w}", headers=admin_headers).status_code == 200


def test_queue_consumer_toggle(client, admin_headers, mock_worker):
    w = _w(mock_worker)
    assert client.post(f"/api/worker/queue/add-consumer/{w}?queue=zz_test_q", headers=admin_headers).status_code == 200
    d = client.get("/api/worker/" + w, headers=admin_headers).json()
    assert "zz_test_q" in [q["name"] for q in d["active_queues"]]
    assert client.post(f"/api/worker/queue/cancel-consumer/{w}?queue=zz_test_q", headers=admin_headers).status_code == 200


def test_broker_and_queues(client, admin_headers):
    r = client.get("/api/broker", headers=admin_headers)
    assert r.status_code == 200
    r = client.get("/api/queues/length", headers=admin_headers)
    assert r.status_code == 200
    assert "active_queues" in r.json()


def test_workers_export(client, admin_headers):
    r = client.get("/api/workers/export", headers=admin_headers)
    assert r.status_code == 200
