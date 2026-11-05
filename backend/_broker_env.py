#!/usr/bin/env python
"""从运行时配置解析 broker 参数，供周边脚本复用。

两个用途：
1. 命令行脚本（start_workers.py / manage.sh）——以 CLI 方式运行，输出 shell export 语句：
       eval "$(python _broker_env.py backend/flowerui.runtime.toml)"
2. python 脚本（send_tasks.py）——以模块方式导入：
       from _broker_env import load_conf

配置格式按扩展名自动识别：
- ``*.toml``：用 toml 库解析（**当前默认**，界面保存的配置落盘到此）
- ``*.env`` / 其它：按 KEY=VALUE 逐行解析，值用 json.loads 兼容字符串/数字/dict/null

保留 .env 解析是为了兼容旧部署；新代码请统一使用 flowerui.runtime.toml。
"""
from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Union


def _parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw.strip().strip('"')


def load_conf(path: Union[str, os.PathLike]) -> Dict[str, Any]:
    """读取运行时配置，返回 {key: value}；文件不存在返回空 dict。

    .toml 走 toml 解析器（值类型天然正确）；其它后缀按旧 KEY=VALUE 格式解析。
    """
    p = Path(path)
    if not p.is_file():
        return {}
    if p.suffix.lower() == ".toml":
        try:
            import toml
            parsed = toml.load(str(p))
            return dict(parsed) if isinstance(parsed, dict) else {}
        except Exception:
            # toml 缺失或文件损坏时降级为逐行解析，避免周边脚本整体崩溃
            pass
    return _load_env_lines(p)


def _load_env_lines(p: Path) -> Dict[str, Any]:
    """旧版 runtime.env 的 KEY=VALUE 解析（保留兼容）。"""
    conf: Dict[str, Any] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        conf[key.strip()] = _parse_value(raw)
    return conf


def resolve_conf_path(explicit: Optional[Union[str, os.PathLike]] = None) -> Path:
    """定位运行时配置文件：显式路径 > .toml（当前） > .env（旧版兼容）。"""
    here = Path(__file__).resolve().parent
    if explicit is not None:
        return Path(explicit)
    for name in ("flowerui.runtime.toml", "flowerui.runtime.env"):
        candidate = here / name
        if candidate.is_file():
            return candidate
    return here / "flowerui.runtime.toml"


def broker_settings(conf: Dict[str, Any]) -> Dict[str, str]:
    """从配置字典推导 broker 连接四元组（环境变量优先，缺省值兜底）。"""
    broker = (
        os.getenv("FLOWER_BROKER_URL")
        or conf.get("broker_url")
        or "redis://127.0.0.1:6379/0"
    )
    opts = os.getenv("FLOWER_BROKER_TRANSPORT_OPTIONS")
    if not opts:
        opts = json.dumps(conf.get("broker_transport_options") or {}, ensure_ascii=False)
    backend = os.getenv("FLOWER_RESULT_BACKEND") or conf.get("result_backend") or ""
    if not backend:
        # 按 broker_url 推导：db 换成 1（sentinel / redis 均适用）
        backend = f"{broker.rsplit('/', 1)[0]}/1" if broker[-1].isdigit() else f"{broker.rstrip('/')}/1"
    queues = {conf.get("task_default_queue") or "celery"}
    for q in (conf.get("task_routes") or {}).values():
        if isinstance(q, str):
            queues.add(q)
    return {
        "broker_url": str(broker),
        "transport_options": str(opts),
        "result_backend": str(backend),
        "queues": ",".join(sorted(queues)),
    }


def main() -> None:
    path = resolve_conf_path(sys.argv[1] if len(sys.argv) > 1 else None)
    s = broker_settings(load_conf(path))
    print(f"BROKER_URL={shlex.quote(s['broker_url'])}")
    print(f"TRANSPORT_OPTS={shlex.quote(s['transport_options'])}")
    print(f"RESULT_BACKEND={shlex.quote(s['result_backend'])}")
    print(f"QUEUES={shlex.quote(s['queues'])}")


if __name__ == "__main__":
    main()
