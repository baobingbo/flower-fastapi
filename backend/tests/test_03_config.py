"""配置系统：查看/修改/校验/脱敏/备份回滚/materialize/审计联动。"""
from __future__ import annotations

import pytest

from conftest import TEST_TMP


@pytest.fixture()
def config_keys(client, admin_headers):
    """当前配置键值快照。"""
    return {x["key"]: x for x in client.get("/api/config", headers=admin_headers).json()["items"]}


def test_config_ui_public(client):
    """界面默认值免鉴权（登录页也要用）。"""
    r = client.get("/api/config/ui")
    assert r.status_code == 200
    body = r.json()
    assert "theme" in body and "transport" in body


def test_config_describe(client, admin_headers, config_keys):
    body = client.get("/api/config", headers=admin_headers).json()
    assert {"groups", "items", "runtime_file", "overrides", "editable_keys"} <= set(body)
    # 关键字段元数据
    assert "basic_auth" in config_keys
    assert config_keys["basic_auth"]["secret"] is True
    assert config_keys["inspect_timeout"]["editable"] is True
    assert config_keys["inspect_timeout"]["max"] == 60000


def test_config_update_and_readback(client, admin_headers, config_keys):
    orig = config_keys["inspect_timeout"]["value"]
    new = orig + 250
    r = client.put("/api/config", json={"changes": {"inspect_timeout": new}}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["applied"] == {"inspect_timeout": new}
    cur = {x["key"]: x for x in client.get("/api/config", headers=admin_headers).json()["items"]}
    assert cur["inspect_timeout"]["value"] == new
    # 还原
    client.put("/api/config", json={"changes": {"inspect_timeout": orig}}, headers=admin_headers)


def test_config_rejects_invalid(client, admin_headers):
    assert client.put("/api/config", json={"changes": {"inspect_timeout": 999999}}, headers=admin_headers).status_code == 400
    assert client.put("/api/config", json={"changes": {"no_such_key": 1}}, headers=admin_headers).status_code == 400
    # 只读字段（editable=False）不可通过 API 修改
    assert client.put("/api/config", json={"changes": {"alert_rules": "[]"}}, headers=admin_headers).status_code == 400


def test_config_secret_masking(client, admin_headers):
    """secret 字段绝不外发明文：oauth2_client_secret 应整体打码。"""
    items = {x["key"]: x for x in client.get("/api/config", headers=admin_headers).json()["items"]}
    val = items["oauth2_client_secret"]["value"]
    assert val in (None, "", "******")
    text = str(items)
    assert "oauth-secret" not in text


def test_config_backup_flow(client, admin_headers):
    """改动产生备份 → 列表 → 回滚 → 再备份 → 删除 → 路径穿越拒绝。"""
    before = len(list(TEST_TMP.glob("*.bak")))
    # 改一个非重启字段（触发备份）
    client.put("/api/config", json={"changes": {"auto_refresh": False}}, headers=admin_headers)
    baks = sorted(TEST_TMP.glob("*.bak"), key=lambda p: p.stat().st_mtime)
    assert len(baks) == before + 1

    r = client.get("/api/config/backups", headers=admin_headers)
    assert r.status_code == 200
    blist = r.json()["backups"]
    assert len(blist) >= 1
    latest = blist[0]

    # 回滚到最新备份（内容 = 改 auto_refresh 之前）
    r = client.post("/api/config/backups/restore", json={"name": latest["name"]}, headers=admin_headers)
    assert r.status_code == 200, r.text[:200]
    items = {x["key"]: x for x in client.get("/api/config", headers=admin_headers).json()["items"]}
    assert items["auto_refresh"]["value"] is True

    # 回滚本身也应建新备份
    assert len(list(TEST_TMP.glob("*.bak"))) > len(baks)

    # 删除备份
    r = client.request("DELETE", "/api/config/backups", json={"name": latest["name"]}, headers=admin_headers)
    assert r.status_code == 200

    # 路径穿越必须被拒
    r = client.request("DELETE", "/api/config/backups", json={"name": "../../etc/passwd"}, headers=admin_headers)
    assert 400 <= r.status_code < 500


def test_config_materialize(client, admin_headers):
    r = client.post("/api/config/materialize", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert (TEST_TMP / str(body["backup"])).is_file() if body.get("backup") else True


def test_config_reset(client, admin_headers):
    # 先改一个值，再 reset
    client.put("/api/config", json={"changes": {"auto_refresh": False}}, headers=admin_headers)
    r = client.post("/api/config/reset", json={"keys": ["auto_refresh"]}, headers=admin_headers)
    assert r.status_code == 200
    assert "auto_refresh" in r.json()["restored"]


def test_config_audit_trail(client, admin_headers):
    """配置操作应留审计（含错误路径）。"""
    client.put("/api/config", json={"changes": {"auto_refresh": False}}, headers=admin_headers)
    client.put("/api/config", json={"changes": {"inspect_timeout": 999999}}, headers=admin_headers)
    r = client.get("/api/audit?action=config.update&limit=50", headers=admin_headers)
    assert r.status_code == 200
    actions = r.json()
    assert actions["total"] >= 2
    results = {i["result"] for i in actions["items"]}
    assert "ok" in results and "error" in results


def test_audit_list_and_actions(client, admin_headers):
    r = client.get("/api/audit", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] > 0 and body["items"]
    # 倒序：最新在前
    r2 = client.get("/api/audit/actions", headers=admin_headers)
    assert r2.status_code == 200
    assert "auth.login" in r2.json()["actions"]
    # 分页生效
    r3 = client.get("/api/audit?limit=1", headers=admin_headers)
    assert len(r3.json()["items"]) <= 1
