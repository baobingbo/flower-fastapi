"""FlowerUI 功能测试公共夹具。

设计要点
--------
1. 全离线：FLOWER_MOCK=true 启用内置模拟集群，无需 Redis/Celery worker；
2. 零污染：运行时配置 / 审计 / 重启状态 / SQLite 用户库全部重定向到
   会话级临时目录，绝不触碰 backend/ 下的真实数据文件；
3. 安全重启：FLOWER_RESTART_SCRIPT 指向无害的 dummy 脚本（exit 0），
   任何用例触发 /api/system/restart 都不会真的重启进程；
4. 鉴权模型：SQLite 用户库（初始 admin/admin123），auth_enabled=true，
   与生产默认一致——测试顺带覆盖 401/403 路径。

用法：在 backend/ 目录下运行 pytest（收集配置见 pytest.ini）。
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Dict

BACKEND_DIR = Path(__file__).resolve().parents[1]

# ----------------------------------------------------------------------
# 必须在 import app 之前设置环境变量（Settings 在 import 时读环境）。
# ----------------------------------------------------------------------
TEST_TMP = Path(tempfile.mkdtemp(prefix="flowerui-tests-"))

_DUMMY_RESTART = TEST_TMP / "dummy_restart.sh"
_DUMMY_RESTART.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

os.environ.update(
    {
        "FLOWER_MOCK": "true",
        "FLOWER_AUTH_ENABLED": "true",
        "FLOWER_DEBUG": "false",
        "FLOWER_RUNTIME_CONFIG_FILE": str(TEST_TMP / "flowerui.runtime.env"),
        "FLOWER_AUDIT_FILE": str(TEST_TMP / "flowerui.audit.jsonl"),
        "FLOWER_RESTART_STATE_FILE": str(TEST_TMP / "flowerui.restart.json"),
        "FLOWER_DB_PATH": str(TEST_TMP / "flowerui.db"),
        "FLOWER_RESTART_SCRIPT": str(_DUMMY_RESTART),
        "FLOWER_THEMES_DIR": str(TEST_TMP / "themes"),
    }
)
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_USER = "admin"
ADMIN_PASS = "admin123"


def _login_token(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, "登录失败 %s: %s %s" % (username, resp.status_code, resp.text[:120])
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def client():
    """共享 TestClient（lifespan 只跑一次）。"""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin_headers(client) -> Dict[str, str]:
    """admin（role=admin，拥有全部权限）的 Bearer 头。"""
    return {"Authorization": "Bearer " + _login_token(client, ADMIN_USER, ADMIN_PASS)}


def _make_user_headers(client, admin_headers: Dict[str, str], role: str) -> Dict[str, str]:
    """创建指定角色的用户并返回其 Bearer 头。"""
    name = role + "_" + uuid.uuid4().hex[:8]
    password = "Pass1234!" + role
    resp = client.post(
        "/api/users", json={"username": name, "password": password, "role": role},
        headers=admin_headers,
    )
    assert resp.status_code in (200, 201), resp.text[:200]
    token = _login_token(client, name, password)
    return {"Authorization": "Bearer " + token, "X-Test-Username": name}


@pytest.fixture(scope="session")
def viewer_headers(client, admin_headers) -> Dict[str, str]:
    """viewer 角色（仅 task.view 权限）。"""
    return _make_user_headers(client, admin_headers, "viewer")


@pytest.fixture(scope="session")
def operator_headers(client, admin_headers) -> Dict[str, str]:
    """operator 角色（task.view + task.apply + worker.manage）。"""
    return _make_user_headers(client, admin_headers, "operator")


@pytest.fixture(scope="session")
def mock_worker(client, admin_headers) -> str:
    """模拟集群里第一个在线 worker 名。"""
    rows = client.get("/api/workers/table", headers=admin_headers).json()["data"]
    online = [r["name"] for r in rows if r["status"]]
    assert online, "mock 集群应有在线 worker"
    return online[0]


@pytest.fixture(scope="session")
def mock_task(client, admin_headers) -> str:
    """模拟集群注册任务里的第一个任务名（mock 模式下形如 app.tasks.send_email）。"""
    reg = client.get("/api/task/registered", headers=admin_headers).json()
    assert reg.get("tasks"), "mock 集群应注册演示任务"
    return reg["tasks"][0]
