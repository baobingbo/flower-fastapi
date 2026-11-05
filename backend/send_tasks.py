#!/usr/bin/env python
"""随机发送一批 Celery 测试任务（默认 10 条）。

两种投递方式：
  --mode api      （默认）走 FlowerUI 后端 API：
                  POST /api/task/send-task/<任务名>
                  与前端"下发任务"页面同一链路，能完整体验监控系统。
  --mode direct   绕过 API 直连 broker（celery send_task），
                  后端未启动时也能压测 worker。

任务定义来自 examples/tasks.py（与 start_workers.py 启动的 worker 一致），
broker 配置自动从 backend/flowerui.runtime.toml 读取（环境变量优先）。

用法（Git Bash，venv 下）:
  .venv/Scripts/python.exe send_tasks.py                    # API 模式发 10 条
  .venv/Scripts/python.exe send_tasks.py --count 20         # 发 20 条
  .venv/Scripts/python.exe send_tasks.py --mode direct      # 直连 broker
  .venv/Scripts/python.exe send_tasks.py --poll             # 发送后等待终态
  .venv/Scripts/python.exe send_tasks.py --seed 42          # 固定随机种子（复现）
  .venv/Scripts/python.exe send_tasks.py --list             # 只看任务池，不发送
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

# 复用 _broker_env.py 的配置解析（本脚本在 backend/ 下运行）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _broker_env import broker_settings, load_conf, resolve_conf_path  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent
# 界面保存的配置落盘到 flowerui.runtime.toml；resolve_conf_path 会兼容旧 .env
RUNTIME_ENV = resolve_conf_path()
TASKS_DIR = ROOT / "examples"

TEMPLATES = ["welcome", "reset_password", "invoice", "newsletter", "alert"]


def _custom_job(rnd: random.Random) -> Dict[str, Any]:
    return {"args": [rnd.randint(1, 100), rnd.randint(1, 100)]}


def _send_email(rnd: random.Random) -> Dict[str, Any]:
    return {
        "args": [
            f"user{rnd.randint(1, 999)}@example.com",
            rnd.choice(TEMPLATES),
        ]
    }


def _resize_image(rnd: random.Random) -> Dict[str, Any]:
    return {
        "args": [
            f"s3://bucket/img/{rnd.randint(1, 99)}.jpg",
            rnd.choice([64, 128, 256, 512]),
        ]
    }


def _long_task(rnd: random.Random) -> Dict[str, Any]:
    # 步数压短（2~4），10 条随机任务整体可在 ~1 分钟内跑完
    return {"kwargs": {"steps": rnd.randint(2, 4)}}


# 任务池：名字 -> 参数生成器（权重相同，随机抽取）
TASK_POOL: List[Tuple[str, Callable[[random.Random], Dict[str, Any]]]] = [
    ("tasks.custom_job", _custom_job),
    ("tasks.send_email", _send_email),
    ("tasks.resize_image", _resize_image),
    ("tasks.flaky", lambda rnd: {}),
    ("tasks.long_task", _long_task),
    ("tasks.retry_demo", lambda rnd: {}),
]


def api_base_url() -> str:
    conf = load_conf(RUNTIME_ENV)
    host = conf.get("host") or "0.0.0.0"
    if host in ("0.0.0.0", "::", ""):
        host = "127.0.0.1"
    port = conf.get("port") or 5555
    prefix = conf.get("url_prefix") or ""
    return f"http://{host}:{port}{prefix}"


def post_json(url: str, payload: Dict[str, Any], timeout: float = 10.0) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_json(url: str, timeout: float = 10.0) -> Dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_via_api(base: str, name: str, params: Dict[str, Any]) -> str:
    resp = post_json(f"{base}/api/task/send-task/{name}", params)
    return resp.get("task-id") or resp.get("task_id") or ""


def send_via_direct(name: str, params: Dict[str, Any]) -> str:
    """绕过 API，用 examples/tasks.py 的同一个 Celery app 直投 broker。

    注意：tasks.py 在 import 时即读取 FLOWER_BROKER_URL 等环境变量，
    因此必须先 export 再 import（顺序不能反），否则会用默认的无密码
    redis://127.0.0.1:6379/0 去连，触发 NOAUTH 重试直到超时。
    """
    s = broker_settings(load_conf(RUNTIME_ENV))
    os.environ["FLOWER_BROKER_URL"] = s["broker_url"]
    os.environ["FLOWER_BROKER_TRANSPORT_OPTIONS"] = s["transport_options"]
    os.environ["FLOWER_RESULT_BACKEND"] = s["result_backend"]

    sys.path.insert(0, str(TASKS_DIR))
    from tasks import app as celery_app  # noqa: PLC0415 - 延迟导入，api 模式不需要

    result = celery_app.send_task(
        name,
        args=params.get("args") or [],
        kwargs=params.get("kwargs") or {},
    )
    return result.id


def poll_states(base: str, task_ids: List[str], timeout: float = 60.0) -> Dict[str, str]:
    """轮询任务终态；超时未终态的标注 TIMEOUT。"""
    states: Dict[str, str] = {}
    deadline = time.time() + timeout
    pending = list(task_ids)
    while pending and time.time() < deadline:
        for tid in list(pending):
            try:
                info = get_json(f"{base}/api/task/info/{tid}")
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                continue
            state = info.get("state") or ""
            if state in ("SUCCESS", "FAILURE", "REVOKED"):
                states[tid] = state
                pending.remove(tid)
        if pending:
            time.sleep(1.0)
    for tid in pending:
        states[tid] = "TIMEOUT"
    return states


def main() -> None:
    parser = argparse.ArgumentParser(
        description="随机发送 Celery 测试任务（默认 10 条）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--count", "-n", type=int, default=10, help="发送数量（默认 10）")
    parser.add_argument(
        "--mode",
        choices=["api", "direct"],
        default="api",
        help="投递方式：api 走后端 API（默认）；direct 直连 broker",
    )
    parser.add_argument("--poll", action="store_true", help="发送后轮询等待终态（仅 api 模式）")
    parser.add_argument("--seed", type=int, default=None, help="随机种子（复现同一批任务）")
    parser.add_argument("--interval", type=float, default=0.2, help="每条任务间隔秒数（默认 0.2）")
    parser.add_argument("--list", action="store_true", help="只展示任务池，不发送")
    args = parser.parse_args()

    rnd = random.Random(args.seed)

    if args.list:
        print("任务池（等权随机抽取）:")
        for name, _ in TASK_POOL:
            print(f"  - {name}")
        return

    s = broker_settings(load_conf(RUNTIME_ENV))
    base = api_base_url()
    print(f">> 模式: {args.mode} | 数量: {args.count}", flush=True)
    print(f">> broker: {s['broker_url']}", flush=True)
    if args.mode == "api":
        print(f">> API: {base}", flush=True)
        # 预检后端可达性，给出明确错误而不是一串堆栈
        try:
            get_json(f"{base}/api/config", timeout=5)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(
                f"[ERROR] 无法连接 FlowerUI 后端（{base}）：{exc}\n"
                "         请先启动后端（backend/manage.sh dev），"
                "或改用 --mode direct 直连 broker 发送。",
                file=sys.stderr,
            )
            sys.exit(2)

    sent: List[Tuple[str, str, Dict[str, Any]]] = []
    for i in range(args.count):
        name, gen = rnd.choice(TASK_POOL)
        params = gen(rnd)
        try:
            if args.mode == "api":
                tid = send_via_api(base, name, params)
            else:
                tid = send_via_direct(name, params)
        except Exception as exc:  # noqa: BLE001 - 单条失败不中断整批
            print(f"[WARN] 第 {i + 1} 条 {name} 发送失败: {exc}")
            continue
        sent.append((name, tid, params))
        arg_desc = params.get("args") or params.get("kwargs") or ""
        print(f"  [{i + 1:>2}/{args.count}] {name:<22} {str(arg_desc):<40} -> {tid}")
        if args.interval > 0 and i < args.count - 1:
            time.sleep(args.interval)

    print(f"\n>> 已发送 {len(sent)}/{args.count} 条任务。")

    if args.poll and sent:
        print(">> 等待任务终态（最多 60s）...")
        states = poll_states(base, [tid for _, tid, _ in sent])
        print("\n  任务                                状态")
        print("  " + "-" * 50)
        for name, tid, _ in sent:
            print(f"  {name:<22} {tid[:8]}  {states.get(tid, '?')}")
        ok = sum(1 for v in states.values() if v == "SUCCESS")
        fail = sum(1 for v in states.values() if v == "FAILURE")
        print(f"\n>> 终态统计: SUCCESS={ok} FAILURE={fail} 其他={len(states) - ok - fail}")
        print(">> 在 FlowerUI 的 Tasks / Dashboard 页查看实时数据。")


if __name__ == "__main__":
    main()
