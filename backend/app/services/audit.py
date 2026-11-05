"""操作审计日志。

设计要点
--------
- 追加写 JSONL（``flowerui.audit.jsonl``，可用 ``FLOWER_AUDIT_FILE`` 覆盖），
  每行一条：``{ts, user, ip, action, detail, result, error?}``。
- detail 中的密文字段（basic_auth / broker_url / secret_key）自动脱敏，
  与 /api/config 的脱敏策略一致（B-04 的延伸：审计日志也不留明文）。
- 轮转：主文件超过 5MB 时整体滚动为 ``*.1``（保留一代），``*.1`` 中
  mtime 超过 30 天的旧文件在下次写入时清理。
- 审计失败绝不阻断业务动作：record() 内部吞掉所有异常。

查询走 ``GET /api/audit``（routers/audit.py），支持 limit/offset/user/action/
start/end 过滤，返回倒序（最新在前）。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Request

logger = logging.getLogger("flowerui.audit")

# t4 收尾④：默认路径锚定 backend 目录的绝对路径（按 __file__ 推导，与
# RESTART_SCRIPT / FRONTEND_DIST 的锚定方式一致），避免 CWD 变化导致审计
# 日志散落在启动目录；FLOWER_AUDIT_FILE 仍可显式覆盖。
_BACKEND_DIR = Path(__file__).resolve().parents[2]  # services/ → app/ → backend/
AUDIT_FILE = Path(
    os.environ.get("FLOWER_AUDIT_FILE") or str(_BACKEND_DIR / "flowerui.audit.jsonl")
).resolve()

_MAX_BYTES = 5 * 1024 * 1024   # 主文件轮转阈值
_ROTATED = Path(str(AUDIT_FILE) + ".1")
_RETENTION_DAYS = 30           # 滚动文件保留天数

_lock = threading.Lock()


def _client_ip(request: Optional[Request]) -> str:
    if request is None:
        return ""
    try:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client and request.client.host:
            return request.client.host
    except Exception:  # noqa: BLE001
        pass
    return ""


def _mask_detail(detail: Any) -> Any:
    """递归脱敏 detail：配置键命中密文字段时复用 runtime_config 的掩码规则。"""
    if detail is None:
        return None
    try:
        from . import runtime_config

        def _one(key: str, value: Any) -> Any:
            # t8 扩展：先按外层 key 查密文字段——命中 secret 时无论 value 是
            # 标量/list/dict 都整体交给 _mask 掩码，绝不递归进 {old,new} 这类
            # 嵌套结构（子键不命中 FIELD_MAP，递归会把明文写进审计日志）
            field = runtime_config.FIELD_MAP.get(str(key))
            if field is not None and field.secret:
                return runtime_config._mask(field, value)
            if isinstance(value, dict):
                return {k: _one(str(k), v) for k, v in value.items()}
            if isinstance(value, list):
                return [_one(key, v) for v in value]
            return value

        if isinstance(detail, dict):
            return {str(k): _one(str(k), v) for k, v in detail.items()}
        return detail
    except Exception:  # noqa: BLE001 - 脱敏失败不应影响审计主流程
        return {"_masked": True}


def _maybe_rotate_locked() -> None:
    """轮转与清理（调用方须持有 _lock）。"""
    try:
        if AUDIT_FILE.exists() and AUDIT_FILE.stat().st_size > _MAX_BYTES:
            if _ROTATED.exists():
                _ROTATED.unlink()
            AUDIT_FILE.rename(_ROTATED)
        # 清理超龄滚动文件
        if _ROTATED.exists():
            age = time.time() - _ROTATED.stat().st_mtime
            if age > _RETENTION_DAYS * 86400:
                _ROTATED.unlink()
    except OSError:
        logger.exception("审计日志轮转失败")


def record(
    action: str,
    user: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
    request: Optional[Request] = None,
    result: str = "ok",
    error: Optional[str] = None,
) -> None:
    """追加一条审计记录。绝不抛出。"""
    try:
        entry: Dict[str, Any] = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "user": user or "anonymous",
            "ip": _client_ip(request),
            "action": action,
            "detail": _mask_detail(detail),
            "result": result,
        }
        if error:
            entry["error"] = str(error)[:300]
        line = json.dumps(entry, ensure_ascii=False)
        with _lock:
            _maybe_rotate_locked()
            AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
            with AUDIT_FILE.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:  # noqa: BLE001 - 审计失败绝不阻断业务
        logger.exception("写入审计日志失败: %s", action)


def _parse_ts(value: Any) -> Optional[float]:
    """接受 ISO 8601 字符串或 epoch 秒。"""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _read_all() -> List[Dict[str, Any]]:
    """按时间正序读出滚动文件 + 主文件的全部条目（坏行跳过）。"""
    items: List[Dict[str, Any]] = []
    for path in (_ROTATED, AUDIT_FILE):
        try:
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        items.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            logger.exception("读取审计日志失败: %s", path)
    return items


def query(
    limit: int = 100,
    offset: int = 0,
    user: Optional[str] = None,
    action: Optional[str] = None,
    start: Optional[Any] = None,
    end: Optional[Any] = None,
) -> Dict[str, Any]:
    """倒序（最新在前）分页查询审计记录。"""
    start_ts = _parse_ts(start)
    end_ts = _parse_ts(end)
    matched: List[Dict[str, Any]] = []
    for item in _read_all():
        if user and item.get("user") != user:
            continue
        if action and item.get("action") != action:
            continue
        if start_ts is not None or end_ts is not None:
            try:
                ts = datetime.fromisoformat(item["ts"]).timestamp()
            except (KeyError, ValueError):
                continue
            if start_ts is not None and ts < start_ts:
                continue
            if end_ts is not None and ts > end_ts:
                continue
        matched.append(item)
    matched.reverse()
    total = len(matched)
    page = matched[offset: offset + limit] if offset < total else []
    return {"items": page, "total": total, "limit": limit, "offset": offset}


def get_logs(
    event_types: Optional[List[str]] = None,
    user: Optional[str] = None,
    start: Optional[Any] = None,
    end: Optional[Any] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """按事件类型列表（OR 语义）查询审计条目，返回前端登录日志页需要的字段形态。

    返回倒序（最新在前）；字段映射：action→event_type、ts→timestamp。
    """
    start_ts = _parse_ts(start)
    end_ts = _parse_ts(end)
    wanted = set(event_types or [])
    out: List[Dict[str, Any]] = []
    for item in _read_all():
        action = item.get("action")
        if wanted and action not in wanted:
            continue
        if user and item.get("user") != user:
            continue
        ts = None
        try:
            ts = datetime.fromisoformat(item["ts"]).timestamp()
        except (KeyError, ValueError):
            pass
        if (start_ts is not None or end_ts is not None) and ts is not None:
            if start_ts is not None and ts < start_ts:
                continue
            if end_ts is not None and ts > end_ts:
                continue
        out.append(
            {
                "event_type": action or "",
                "user": item.get("user", ""),
                "detail": item.get("detail") or {},
                "timestamp": item.get("ts"),
                "ip": item.get("ip"),
            }
        )
    out.reverse()
    return out[:limit] if limit and limit > 0 else out


def actions() -> List[str]:
    """去重后的 action 列表（供前端筛选下拉）。"""
    seen: List[str] = []
    for item in _read_all():
        a = item.get("action")
        if a and a not in seen:
            seen.append(a)
    return seen
