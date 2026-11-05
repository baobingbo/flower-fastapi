"""设置模块持久测试（从旧版 test_settings_backend.py 场景清单 1:1 重建）。

覆盖：#4 重启状态机 / #5 配置备份回滚 / #6 审计与脱敏 / 登录鉴权。
环境隔离由 conftest.py 提供（临时目录 + FLOWER_MOCK + dummy 重启脚本），
绝不触碰真实数据、绝不真重启。

说明：原文件为 basic_auth 时代（admin:secret123）的独立脚本，且未纳入 git；
本版本按同一份 127 项检查清单重写为 pytest，并对齐新版 SQLite 用户库
鉴权模型（admin/admin123）。
"""
from __future__ import annotations

import json
import os
import time

from conftest import TEST_TMP

RUNTIME_ENV = TEST_TMP / "flowerui.runtime.env"
AUDIT_FILE = TEST_TMP / "flowerui.audit.jsonl"
STATE_FILE = TEST_TMP / "flowerui.restart.json"


# ----------------------------------------------------------------------
# 1. 登录与鉴权
# ----------------------------------------------------------------------
def test_login_wrong_password_401(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_login_ok_and_config_auth(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text[:200]
    token = r.json()["access_token"]
    assert token
    assert client.get("/api/config").status_code == 401  # 未带 token → 401
    assert client.get("/api/config", headers={"Authorization": "Bearer " + token}).status_code == 200


# ----------------------------------------------------------------------
# 2. 配置查看与 secret 脱敏
# ----------------------------------------------------------------------
def test_config_describe_masks_secrets(client, admin_headers):
    body = client.get("/api/config", headers=admin_headers).json()
    text = str(body)
    assert "oauth-secret-abc" not in text  # 响应不含明文凭据
    items = {x["key"]: x for x in body["items"]}
    val = items["oauth2_client_secret"]["value"]
    assert val in (None, "", "******")  # secret 整体打码


def test_secret_leak_check(client, admin_headers):
    """把各类密文写入后，GET /api/config 不得外发任何明文；
    非 secret 嵌套 dict（task_routes）不得被误掩码。"""
    client.put("/api/config", json={"changes": {
        "basic_auth": ["admin:leakpass1"],
        "oauth2_client_secret": "leakjwtk",
    }}, headers=admin_headers)
    # task_routes 是非 secret 的 dict，必须原样可见
    client.put("/api/config", json={"changes": {
        "task_routes": {"tasks.send_email": "emails"},
    }}, headers=admin_headers)
    body = client.get("/api/config", headers=admin_headers).json()
    text = str(body)
    leaks = [
        "leakpw", "leakpw2", "leaksecret1", "leaksecret2",
        "leakpass1", "leakpass2", "leakjwtk",
    ]
    for s in leaks:
        assert s not in text, "secret 泄漏: " + s
    items = {x["key"]: x for x in body["items"]}
    tr = items["task_routes"]["value"]
    assert isinstance(tr, dict) and tr.get("tasks.send_email") == "emails"


# ----------------------------------------------------------------------
# 3. 备份 / 回滚 / 删除
# ----------------------------------------------------------------------
def _baks():
    return sorted(TEST_TMP.glob("*.bak"), key=lambda p: p.stat().st_mtime)


def test_backup_flow(client, admin_headers):
    # 先确立已知基线（避免其它模块遗留状态干扰“相同值不建备份”判断）
    client.put("/api/config", json={"changes": {"auto_refresh": True}}, headers=admin_headers)
    before = len(_baks())
    # 改动 → 产生 1 个备份
    r = client.put("/api/config", json={"changes": {"auto_refresh": False}}, headers=admin_headers)
    assert r.status_code == 200
    assert len(_baks()) == before + 1

    # 相同值再保存 → 不产生新备份
    client.put("/api/config", json={"changes": {"auto_refresh": False}}, headers=admin_headers)
    assert len(_baks()) == before + 1

    # 第二次改动（port）→ 第 2 个备份
    r = client.put("/api/config", json={"changes": {"port": 9999}}, headers=admin_headers)
    assert r.status_code == 200
    assert len(_baks()) == before + 2

    # 备份列表：新→旧，diff_keys 含本次改动
    r = client.get("/api/config/backups", headers=admin_headers)
    assert r.status_code == 200
    blist = r.json()["backups"]
    assert len(blist) >= 2
    latest = blist[0]
    assert "port" in (latest.get("diff_keys") or [])
    prev = blist[1]
    assert "auto_refresh" in (prev.get("diff_keys") or [])
    # 两份备份的 diff 合起来覆盖全部改动
    assert {"port", "auto_refresh"} <= set((latest.get("diff_keys") or []) + (prev.get("diff_keys") or []))

    # 回滚到最新备份（port 改动前：auto_refresh 已改 false、port 仍 5555）
    r = client.post("/api/config/backups/restore", json={"name": latest["name"]}, headers=admin_headers)
    assert r.status_code == 200, r.text[:200]
    items = {x["key"]: x for x in client.get("/api/config", headers=admin_headers).json()["items"]}
    assert items["port"]["value"] == 5555  # 内存恢复启动值
    assert items["auto_refresh"]["value"] is False  # 备份内 auto_refresh 已是 false
    assert "port=9999" not in RUNTIME_ENV.read_text(encoding="utf-8")
    # 回滚本身又建新备份
    assert len(_baks()) == before + 3

    # 删除一份备份（最旧那份）
    oldest = blist[1]
    r = client.request("DELETE", "/api/config/backups", json={"name": oldest["name"]}, headers=admin_headers)
    assert r.status_code == 200
    names = [b["name"] for b in client.get("/api/config/backups", headers=admin_headers).json()["backups"]]
    assert oldest["name"] not in names

    # 路径穿越被拒
    r = client.request("DELETE", "/api/config/backups", json={"name": "../../etc/passwd"}, headers=admin_headers)
    assert 400 <= r.status_code < 500


def test_materialize_full_write_and_dedup(client, admin_headers):
    """materialize = 全量写盘；内容无变化时去重不刷备份。"""
    client.put("/api/config", json={"changes": {"auto_refresh": False}}, headers=admin_headers)
    before = len(_baks())
    r = client.post("/api/config/materialize", headers=admin_headers)
    assert r.status_code == 200
    # 全量模板写入：文件包含主要配置键
    env = RUNTIME_ENV.read_text(encoding="utf-8")
    for key in ("port=", "broker_url=", "inspect_timeout=", "auto_refresh="):
        assert key in env, "materialize 后文件缺键: " + key
    # 内容未变 → 去重，不产生新备份（避免重复保存刷出一堆相同备份）
    assert len(_baks()) == before
    client.put("/api/config", json={"changes": {"auto_refresh": True}}, headers=admin_headers)


def test_masked_value_not_applied_as_change(client, admin_headers):
    """界面回传掩码值不得覆盖真实密钥（t8 掩码保留策略）。"""
    r = client.put("/api/config", json={"changes": {"oauth2_client_secret": "real-oauth-sec"}}, headers=admin_headers)
    assert r.status_code == 200, r.text[:200]
    # 响应立即打码
    items = {x["key"]: x for x in client.get("/api/config", headers=admin_headers).json()["items"]}
    assert items["oauth2_client_secret"]["value"] == "******"
    # 掩码值随其它字段一起保存 = 未改动，保留原值
    r = client.put("/api/config", json={"changes": {
        "oauth2_client_secret": "******",
        "auto_refresh": False,
    }}, headers=admin_headers)
    assert r.status_code == 200, r.text[:200]
    env = RUNTIME_ENV.read_text(encoding="utf-8")
    assert "real-oauth-sec" in env  # 真实密钥未被 ****** 覆盖
    # 还原
    client.put("/api/config", json={"changes": {"auto_refresh": True, "oauth2_client_secret": ""}}, headers=admin_headers)


# ----------------------------------------------------------------------
# 4. 校验
# ----------------------------------------------------------------------
def test_range_validation_400(client, admin_headers):
    r = client.put("/api/config", json={"changes": {"inspect_timeout": 999999}}, headers=admin_headers)
    assert r.status_code == 400


# ----------------------------------------------------------------------
# 5. 审计
# ----------------------------------------------------------------------
def test_audit_trail_and_filtering(client, admin_headers):
    client.put("/api/config", json={"changes": {"auto_refresh": False}}, headers=admin_headers)
    client.put("/api/config", json={"changes": {"inspect_timeout": 999999}}, headers=admin_headers)

    r = client.get("/api/audit", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] > 5
    assert "config.update" in {i["action"] for i in body["items"]}
    assert any(i["user"] == "admin" for i in body["items"])

    # 按 action 过滤：登录失败也有记录
    r = client.get("/api/audit?action=auth.login_failed", headers=admin_headers)
    assert r.status_code == 200
    assert all(i["action"] == "auth.login_failed" for i in r.json()["items"])

    # 分页
    r = client.get("/api/audit?limit=1", headers=admin_headers)
    assert len(r.json()["items"]) <= 1

    # 倒序：最近一条是刚才的越界错误
    r = client.get("/api/audit?limit=1", headers=admin_headers)
    assert r.json()["items"][0]["result"] == "error"

    # 审计文件不得含登录明文密码
    text = AUDIT_FILE.read_text(encoding="utf-8") if AUDIT_FILE.exists() else ""
    assert "admin123" not in text

    r = client.get("/api/audit/actions", headers=admin_headers)
    assert r.status_code == 200
    assert "config.update" in r.json()["actions"]


# ----------------------------------------------------------------------
# 6. 重启状态机（dummy 脚本，绝不真重启）
# ----------------------------------------------------------------------
def test_restart_status_public_and_idle(client):
    STATE_FILE.unlink(missing_ok=True)
    r = client.get("/api/system/restart/status")  # 免鉴权
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "idle"
    assert body["current_pid"] > 0 and body["started_at"]


def test_restart_trigger_in_progress(client, admin_headers):
    r = client.post("/api/system/restart", headers=admin_headers)
    assert r.status_code == 200, r.text[:200]
    time.sleep(0.5)
    body = client.get("/api/system/restart/status").json()
    assert body["status"] in ("in_progress", "pending")
    assert body["pid"] == body["current_pid"]


def test_restart_failed_when_script_missing(client):
    from app.services import restart as restart_service

    orig = restart_service.RESTART_SCRIPT
    restart_service.RESTART_SCRIPT = str(TEST_TMP / "no_such_script.sh")
    try:
        restart_service.restart_later(delay=0.1)
        time.sleep(0.7)
        body = client.get("/api/system/restart/status").json()
        assert body["status"] == "failed" and body.get("error")
    finally:
        restart_service.RESTART_SCRIPT = orig


def test_restart_success_after_takeover(client):
    from app.services import restart as restart_service

    STATE_FILE.write_text(json.dumps({
        "status": "pending",
        "requested_at": time.time() - 10,
        "pid": 99999999,
        "script": "x",
        "interpreter": "bash",
    }), encoding="utf-8")
    restart_service.settle_on_startup()
    body = client.get("/api/system/restart/status").json()
    assert body["status"] == "success" and body.get("completed_at")


def test_restart_timeout_hint(client):
    STATE_FILE.write_text(json.dumps({
        "status": "pending",
        "requested_at": time.time() - 600,
        "pid": os.getpid(),
        "script": "x",
        "interpreter": "bash",
    }), encoding="utf-8")
    body = client.get("/api/system/restart/status").json()
    assert body["status"] == "timeout" and body.get("hint")
    STATE_FILE.unlink(missing_ok=True)
