"""认证与用户管理：登录、JWT 校验、登录日志、用户/角色 CRUD、RBAC 权限边界。"""
from __future__ import annotations


def test_auth_config_public(client):
    r = client.get("/api/auth/config")
    assert r.status_code == 200
    body = r.json()
    assert body["auth_enabled"] is True
    assert "oauth2_provider" in body


def test_login_admin(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["username"] == "admin"
    assert body["role"] == "admin"
    perm_names = {p["name"] if isinstance(p, dict) else p for p in body["permissions"]}
    assert {"task.view", "task.apply", "config.manage", "user.manage"} <= perm_names


def test_login_wrong_password_401(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_login_unknown_user_401(client):
    r = client.post("/api/auth/login", json={"username": "ghost_user", "password": "x"})
    assert r.status_code == 401


def test_protected_endpoint_requires_token(client):
    assert client.get("/api/config").status_code == 401
    assert client.get("/api/config", headers={"Authorization": "Bearer bad.token.here"}).status_code == 401


def test_login_logs(client, admin_headers):
    # admin 已登录过（fixture）+ 本文件有用 401 失败记录
    r = client.get("/api/auth/login-logs?limit=50", headers=admin_headers)
    assert r.status_code == 200
    items = r.json()["items"]
    assert isinstance(items, list)
    assert any(i["event_type"] == "auth.login" for i in items)
    assert any(i["event_type"] == "auth.login_failed" for i in items)


def test_users_crud(client, admin_headers):
    name = "crud_user"
    # 创建
    r = client.post("/api/users", json={"username": name, "password": "Crud1234!"}, headers=admin_headers)
    assert r.status_code in (200, 201)
    # 重复创建 → 409
    r = client.post("/api/users", json={"username": name, "password": "Crud1234!"}, headers=admin_headers)
    assert r.status_code == 409
    # 查询
    r = client.get("/api/users/" + name, headers=admin_headers)
    assert r.status_code == 200 and r.json()["username"] == name
    # 列表包含该用户
    names = [u["username"] for u in client.get("/api/users", headers=admin_headers).json()]
    assert name in names
    # 弱密码拒绝
    r = client.post("/api/users", json={"username": "weakuser", "password": "123456"}, headers=admin_headers)
    assert r.status_code == 400
    # 管理员重置密码后可登录（该端点接收 {password}）
    r = client.post(
        "/api/users/" + name + "/password",
        json={"password": "New12345!"},
        headers=admin_headers,
    )
    assert r.status_code in (200, 201), r.text[:200]
    assert client.post("/api/auth/login", json={"username": name, "password": "New12345!"}).status_code == 200
    # 删除
    r = client.delete("/api/users/" + name, headers=admin_headers)
    assert r.status_code in (200, 201, 204)
    assert client.get("/api/users/" + name, headers=admin_headers).status_code == 404


def test_roles_and_permissions(client, admin_headers):
    # 角色列表
    r = client.get("/api/roles", headers=admin_headers)
    assert r.status_code == 200
    role_names = [x["name"] for x in r.json()]
    assert {"admin", "operator", "viewer"} <= set(role_names)
    # 权限列表
    r = client.get("/api/permissions", headers=admin_headers)
    assert r.status_code == 200
    perm_names = {x["name"] for x in r.json()}
    assert {"task.view", "config.manage", "user.manage"} <= perm_names
    # 某用户的角色
    r = client.get("/api/users/admin/roles", headers=admin_headers)
    assert r.status_code == 200
    role_names = [x["name"] for x in r.json()]
    assert "admin" in role_names


def test_rbac_viewer_cannot_manage(client, admin_headers, viewer_headers):
    # viewer 可读任务列表（task.view）
    assert client.get("/api/tasks?limit=1", headers=viewer_headers).status_code == 200
    # viewer 不能改配置 / 建用户 / 控 worker / 下发任务
    assert client.put("/api/config", json={"changes": {"auto_refresh": False}}, headers=viewer_headers).status_code == 403
    assert client.post("/api/users", json={"username": "hacker", "password": "Hacker1234!"}, headers=viewer_headers).status_code == 403
    assert client.post("/api/worker/pool/grow/celery@node-1?n=1", headers=viewer_headers).status_code == 403
    assert client.post("/api/task/async-apply/app.tasks.send_email", json={"args": ["x@y.com"]}, headers=viewer_headers).status_code == 403
    assert client.post("/api/system/restart", headers=viewer_headers).status_code == 403


def test_rbac_operator_can_dispatch_but_not_config(client, admin_headers, operator_headers):
    # operator 可下发任务、控制 worker
    r = client.post("/api/task/async-apply/app.tasks.send_email", json={"args": ["op@y.com"]}, headers=operator_headers)
    assert r.status_code == 200
    # 但不能改配置 / 建用户
    assert client.put("/api/config", json={"changes": {"auto_refresh": False}}, headers=operator_headers).status_code == 403
    assert client.post("/api/users", json={"username": "hacker2", "password": "Hacker1234!"}, headers=operator_headers).status_code == 403
