"""系统与其它模块：重启状态机、仪表盘、主题、告警、Beat 调度、初始化接口。"""
from __future__ import annotations

import json
import os
import time

from conftest import TEST_TMP

STATE_FILE = TEST_TMP / "flowerui.restart.json"


# ----------------------------------------------------------------------
# 重启状态机（dummy 脚本，绝不真重启）
# ----------------------------------------------------------------------
def test_restart_status_public_and_idle(client):
    STATE_FILE.unlink(missing_ok=True)
    r = client.get("/api/system/restart/status")
    assert r.status_code == 200  # 状态查询免鉴权（前端重载后轮询用）
    body = r.json()
    assert body["status"] == "idle"
    assert body["current_pid"] > 0 and body["started_at"]


def test_restart_trigger_in_progress(client, admin_headers):
    r = client.post("/api/system/restart", headers=admin_headers)
    assert r.status_code == 200, r.text[:200]
    time.sleep(0.5)
    body = client.get("/api/system/restart/status").json()
    # dummy 脚本不会真的重启：当前进程仍是发起方 → in_progress
    assert body["status"] in ("in_progress", "pending"), body
    assert body["pid"] == body["current_pid"]


def test_restart_failed_when_script_missing(client):
    from app.services import restart as restart_service

    orig = restart_service.RESTART_SCRIPT
    restart_service.RESTART_SCRIPT = str(TEST_TMP / "no_such_script.sh")
    try:
        restart_service.restart_later(delay=0.1)
        time.sleep(0.7)
        body = client.get("/api/system/restart/status").json()
        assert body["status"] == "failed" and body.get("error"), body
    finally:
        restart_service.RESTART_SCRIPT = orig


def test_restart_success_after_new_process_takeover(client):
    """旧进程已死 + settle_on_startup() → success。"""
    from app.services import restart as restart_service

    STATE_FILE.write_text(
        json.dumps({
            "status": "pending",
            "requested_at": time.time() - 10,
            "pid": 99999999,  # 不存在的旧 pid
            "script": "x",
            "interpreter": "bash",
        }),
        encoding="utf-8",
    )
    restart_service.settle_on_startup()
    body = client.get("/api/system/restart/status").json()
    assert body["status"] == "success" and body.get("completed_at")


def test_restart_timeout_hint(client):
    STATE_FILE.write_text(
        json.dumps({
            "status": "pending",
            "requested_at": time.time() - 600,  # 超过 GRACE_SECONDS
            "pid": os.getpid(),
            "script": "x",
            "interpreter": "bash",
        }),
        encoding="utf-8",
    )
    body = client.get("/api/system/restart/status").json()
    assert body["status"] == "timeout" and body.get("hint")
    STATE_FILE.unlink(missing_ok=True)


# ----------------------------------------------------------------------
# 仪表盘 / 概览
# ----------------------------------------------------------------------
def test_dashboard_endpoints(client, admin_headers):
    r = client.get("/api/dashboard/summary", headers=admin_headers)
    assert r.status_code == 200 and isinstance(r.json(), dict)
    assert client.get("/api/dashboard/snapshot", headers=admin_headers).status_code == 200
    r = client.get("/api/dashboard/timeline?limit=10", headers=admin_headers)
    assert r.status_code == 200
    r = client.get("/api/dashboard/filters", headers=admin_headers)
    assert r.status_code == 200
    r = client.get("/api/dashboard/task-distribution?top=5", headers=admin_headers)
    assert r.status_code == 200


# ----------------------------------------------------------------------
# 主题
# ----------------------------------------------------------------------
def test_themes_list_and_file(client, admin_headers):
    r = client.get("/api/themes", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert "themes" in body and "dir" in body
    # base.css 公共令牌文件可下载
    r = client.get("/api/themes/files/base.css")
    assert r.status_code == 200
    assert "text/css" in r.headers.get("content-type", "")
    assert client.get("/api/themes/files/nope.css").status_code == 404


def test_theme_upload_delete_roundtrip(client, admin_headers):
    # 主题文件必须包含与文件名一致的 [data-theme='xxx'] 选择器（上传校验）
    css = "[data-theme='test_theme_zz'] { --fu-accent: #ff6600; }\n"
    r = client.post(
        "/api/themes",
        files={"file": ("test_theme_zz.css", css.encode(), "text/css")},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text[:200]
    theme_id = r.json()["theme"]["id"]
    ids = [t["id"] for t in client.get("/api/themes", headers=admin_headers).json()["themes"]]
    assert theme_id in ids
    r = client.delete("/api/themes/" + theme_id, headers=admin_headers)
    assert r.status_code == 200
    ids = [t["id"] for t in client.get("/api/themes", headers=admin_headers).json()["themes"]]
    assert theme_id not in ids


# ----------------------------------------------------------------------
# 告警
# ----------------------------------------------------------------------
def test_alerts_rules_crud(client, admin_headers):
    r = client.post(
        "/api/alerts/rules",
        json={"name": "zz_test_rule", "task_name": "app.tasks.send_email", "op": "*", "threshold": 0},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text[:200]
    rule_id = r.json()["id"]
    # 列表
    rules = client.get("/api/alerts/rules", headers=admin_headers).json()["rules"]
    assert any(x["id"] == rule_id for x in rules)
    # 更新
    r = client.put("/api/alerts/rules/" + rule_id, json={"enabled": False}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    # 删除
    assert client.delete("/api/alerts/rules/" + rule_id, headers=admin_headers).status_code == 200
    assert client.get("/api/alerts/rules", headers=admin_headers).json()["count"] >= 0
    # 未知规则 404
    assert client.delete("/api/alerts/rules/zzz", headers=admin_headers).status_code == 404


def test_alerts_channels_and_status(client, admin_headers):
    assert client.get("/api/alerts/channels", headers=admin_headers).status_code == 200
    r = client.get("/api/alerts/status", headers=admin_headers)
    assert r.status_code == 200
    assert "alert_enabled" in r.json()


# ----------------------------------------------------------------------
# Beat 调度
# ----------------------------------------------------------------------
def test_beats_crud(client, admin_headers):
    name = "zz_test_beat"
    r = client.get("/api/beats", headers=admin_headers)
    assert r.status_code == 200
    r = client.post(
        "/api/beats",
        json={"name": name, "task": "app.tasks.send_email", "schedule": "60.0"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text[:200]
    names = [b["name"] for b in client.get("/api/beats", headers=admin_headers).json()["beats"]]
    assert name in names
    r = client.delete("/api/beats/" + name, headers=admin_headers)
    assert r.status_code == 200
    assert client.delete("/api/beats/no-such-beat", headers=admin_headers).status_code == 404


# ----------------------------------------------------------------------
# 初始化接口
# ----------------------------------------------------------------------
def test_init_status(client, admin_headers):
    r = client.get("/api/init/status", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["initialized"] is True
    assert body["user_count"] >= 1


def test_init_run_idempotent_guard(client, admin_headers):
    """已初始化时重复执行应被 400 拒绝（防误重置）。"""
    r = client.post("/api/init/run", headers=admin_headers)
    assert r.status_code == 400
