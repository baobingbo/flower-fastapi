"""WebSocket 实时通道：鉴权、首屏快照、心跳、订阅。"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.ws


def _token(admin_headers: dict) -> str:
    return admin_headers["Authorization"].split(" ", 1)[1]


def _wait_pong(ws) -> bool:
    for _ in range(30):
        m = ws.receive_json()
        if m.get("type") == "pong":
            return True
    return False


def test_ws_requires_token(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/events") as ws:
            ws.receive_json()  # 未鉴权连接应被关闭（4401）


def test_ws_snapshot_and_pong(client, admin_headers):
    with client.websocket_connect("/ws/events?token=" + _token(admin_headers)) as ws:
        # 首屏快照
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        assert isinstance(msg["summary"], dict)
        assert msg["workers"] is not None
        assert msg["timeline"] is not None
        # 心跳：{action: ping} 与 {type: ping} 两种形态都要回 pong
        for payload in ({"action": "ping"}, {"type": "ping"}):
            ws.send_json(payload)
            assert _wait_pong(ws), "心跳未回 pong: " + str(payload)


def test_ws_subscribe_then_ping(client, admin_headers):
    """订阅指令不应破坏连接，之后心跳仍正常。"""
    with client.websocket_connect("/ws/events?token=" + _token(admin_headers)) as ws:
        ws.receive_json()  # snapshot
        ws.send_json({"action": "subscribe", "types": ["summary"]})
        ws.send_json({"action": "ping"})
        assert _wait_pong(ws), "订阅后心跳未回 pong"
