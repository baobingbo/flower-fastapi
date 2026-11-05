#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""FlowerUI Celery Worker 批量启动脚本（纯 Python，跨 Windows/Linux）。

设计要点（对应 Git Bash on Windows 下 nohup 不可用的场景）：
  1. 多进程启动：每个 worker 是脚本的子进程（subprocess.Popen），全部共享
     当前终端——不会弹多个新窗口（Windows 不加 CREATE_NEW_CONSOLE）。
  2. 保活替代 nohup：不再追求"父进程退出后 worker 还活着"；改为前台管家
     (supervisor) 模式——脚本常驻，持续监控 worker 状态，Ctrl+C 时先优雅
     停止全部 worker，再退出脚本。终端关闭/脚本被杀，worker 一并结束。
  3. Ctrl+C 传播控制：子进程被放进独立进程组（Windows: CREATE_NEW_PROCESS_GROUP，
     POSIX: start_new_session），控制台的 Ctrl+C 不会直达 worker，由脚本统一
     发停止信号，避免"父子同时收到 Ctrl+C 打架"导致半死不活。
  4. 崩溃自愈：worker 异常退出时自动重启（可用 --no-restart 关闭），单个
     worker 最多重启 5 次，超过则放弃并提示查看日志。

broker 配置自动从 backend/flowerui.runtime.toml 读取（复用 _broker_env.py），
后端切哨兵/单机模式后 worker 自动跟随，无需手工传环境变量。

用法：
  python start_workers.py start [N=4]   # 前台启动 N 个 worker 并持续监控（Ctrl+C 停止）
  python start_workers.py stop          # 从外部停止全部 worker（会通知监控中的脚本退出）
  python start_workers.py status        # 查看运行状态
  python start_workers.py logs [N] [-f] # 查看/跟踪第 N 个 worker 日志
  python start_workers.py help

start 附加选项：
  --no-restart        worker 崩溃后不自动重启（默认自动重启）
  --interval 5        状态刷新间隔秒数（默认 5）

环境变量覆盖（优先级高于 runtime.toml）：
  FLOWER_BROKER_URL / FLOWER_BROKER_TRANSPORT_OPTIONS / FLOWER_RESULT_BACKEND
  WORKER_CONCURRENCY（默认 4）/ WORKER_POOL（默认 threads，Windows 必须）
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

if os.name == "nt":
    import ctypes  # noqa: F401  Windows 控制台 API（SetConsoleCtrlHandler）

# _broker_env.py 与本脚本同目录，允许从任意 cwd 直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _broker_env import broker_settings, load_conf, resolve_conf_path  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent
TASKS_DIR = ROOT / "examples"
# 界面保存的配置落盘到 flowerui.runtime.toml；resolve_conf_path 会兼容旧 .env
RUNTIME_ENV = resolve_conf_path()
# 日志 / PID / 停止标记统一放在 backend/logs/workers/，避免污染 backend/ 目录
LOGS_DIR = BACKEND_DIR / "logs" / "workers"
STOP_MARKER = LOGS_DIR / "_workers.stopped"  # 外部 stop 时落下，通知监控循环退出
DEFAULT_COUNT = 4

IS_WINDOWS = os.name == "nt"

# Windows 进程创建标志
CREATE_NEW_PROCESS_GROUP = 0x00000200  # 独立进程组（不收发控制台 Ctrl+C，也不弹新窗口）

MAX_RESTARTS = 5        # 单个 worker 异常退出后的最大自动重启次数
RESTART_DELAY = 2.0     # 崩溃后重启前的等待秒数（防热循环）
READY_TIMEOUT = 60      # 等待 worker 就绪的最长秒数
SHUTDOWN_TIMEOUT = 15   # Ctrl+C 后等待 worker 优雅退出的最长秒数

# ---------- 终端颜色（git bash / Linux 均支持 ANSI；不支持时也无害） ----------
GREEN, CYAN, YELLOW, RED, NC = "\033[0;32m", "\033[0;36m", "\033[1;33m", "\033[0;31m", "\033[0m"


def info(msg: str) -> None:
    print(f"{CYAN}[INFO]{NC} {msg}")


def ok(msg: str) -> None:
    print(f"{GREEN}[OK]{NC} {msg}")


def warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{NC} {msg}")


def error(msg: str) -> None:
    print(f"{RED}[ERROR]{NC} {msg}")


# ---------- Python 定位：优先 venv，回退当前解释器 ----------
def detect_python() -> str:
    candidates = [
        BACKEND_DIR / ".venv" / ("Scripts/python.exe" if IS_WINDOWS else "bin/python"),
        ROOT / ".venv" / ("Scripts/python.exe" if IS_WINDOWS else "bin/python"),
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return sys.executable


# ---------- PID / 日志文件 ----------
def pid_file(n: int) -> Path:
    return LOGS_DIR / f"_worker_{n}.pid"


def log_file(n: int) -> Path:
    return LOGS_DIR / f"_worker_{n}.log"


def safe_unlink(path: Path) -> None:
    """删除文件，不存在时静默忽略。

    原写法 ``Path.unlink(missing_ok=True)`` 是 Python 3.8 才加入的参数，而本项目
    backend/.venv 固定为 Python 3.7.9，直接调用会抛
    ``TypeError: unlink() got an unexpected keyword argument 'missing_ok'``。
    这里改用 ``os.remove`` 并自行捕获 FileNotFoundError，语义与 missing_ok=True
    一致（其余 OSError 照常抛出），也不依赖可能被运行环境包装的 Path.unlink。
    """
    try:
        os.remove(str(path))
    except FileNotFoundError:
        pass


def all_pid_numbers() -> list[int]:
    nums = []
    for f in LOGS_DIR.glob("_worker_*.pid"):
        try:
            nums.append(int(f.stem.split("_")[-1]))
        except ValueError:
            continue
    return sorted(nums)


# ---------- 进程存活判断（跨平台，无需 psutil） ----------
def pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if IS_WINDOWS:
        try:
            out = subprocess.run(
                ["tasklist", "/NH", "/FI", f"PID eq {pid}"],
                capture_output=True, timeout=10,
                # 中文 Windows 控制台输出为 GBK 字节，按 utf-8+replace 解码，
                # 关键判定词 "python" 是 ASCII 不受影响
                encoding="utf-8", errors="replace",
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            return False
        return "python" in out.lower()
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 进程存在但不属于当前用户
    except OSError:
        return False


# ---------- 信号发送：先优雅、后强杀 ----------
def signal_stop(proc: subprocess.Popen) -> None:
    """给 worker 发停止信号（不杀树，先给它机会做 warm shutdown）。"""
    if IS_WINDOWS:
        # CTRL_BREAK_EVENT 需配合 CREATE_NEW_PROCESS_GROUP，只发给本组
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        except (OSError, ValueError):
            pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def force_kill(proc: subprocess.Popen) -> None:
    """强杀 worker 进程树（连 billiard 子进程）。"""
    if IS_WINDOWS:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True, encoding="utf-8", errors="replace",
        )
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def kill_pid_tree(pid: int) -> None:
    """按裸 PID 杀进程树（供外部 stop 命令使用）。"""
    if IS_WINDOWS:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, encoding="utf-8", errors="replace",
        )
    else:
        try:
            os.killpg(pid, signal.SIGTERM)
            time.sleep(0.5)
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass


# ---------- Worker 运行时对象 ----------
class Worker:
    def __init__(self, n: int) -> None:
        self.n = n
        self.proc: subprocess.Popen | None = None
        self.log_fh = None
        self.started_at = 0.0
        self.last_restart = 0.0
        self.restarts = 0
        self.gave_up = False
        self.exit_reported = False


def fmt_uptime(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ---------- 启动单个 worker ----------
def launch_worker(w: Worker, env: dict[str, str], queues: str, pool: str, concurrency: str, python: str) -> None:
    logf = log_file(w.n)
    if w.log_fh is None:
        # buffering=1 行缓冲：子进程写入能尽快落到磁盘
        w.log_fh = open(logf, "a", encoding="utf-8", buffering=1)
    cmd = [
        python, "-m", "celery", "-A", "tasks", "worker", "-E", "-l", "info",
        "-Q", queues,
        "--pool", pool, "-c", concurrency,
        "--hostname", f"worker{w.n}@flowerui",
        "--logfile", str(logf),
    ]
    # 独立进程组：控制台 Ctrl+C 不直达子进程，由脚本统一下发停止信号；
    # 不加 CREATE_NEW_CONSOLE，不弹新窗口。
    if IS_WINDOWS:
        kwargs = {"creationflags": CREATE_NEW_PROCESS_GROUP}
    else:
        kwargs = {"start_new_session": True}
    w.proc = subprocess.Popen(
        cmd, cwd=str(TASKS_DIR), env=env,
        stdin=subprocess.DEVNULL, stdout=w.log_fh, stderr=w.log_fh,
        close_fds=True, **kwargs,
    )
    w.started_at = time.monotonic()
    w.last_restart = w.started_at
    w.exit_reported = False
    # Windows 下 Popen.pid 即 Windows PID，无 MSYS winpid 映射问题
    pid_file(w.n).write_text(str(w.proc.pid), encoding="utf-8")


def log_ready(w: Worker) -> bool:
    try:
        return "ready." in log_file(w.n).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


# ---------- 状态报告行 ----------
def report(workers: dict[int, Worker]) -> None:
    parts = []
    for n, w in sorted(workers.items()):
        if w.proc is not None and w.proc.poll() is None:
            tag = f"运行 {fmt_uptime(time.monotonic() - w.started_at)}"
            if w.restarts:
                tag += f" · 重启{w.restarts}次"
            parts.append(f"{GREEN}worker{n}{NC} PID={w.proc.pid} {tag}")
        else:
            code = w.proc.returncode if w.proc is not None else "?"
            parts.append(f"{RED}worker{n}{NC} 已退出(code={code})")
    print(f"[监控 {datetime.now():%H:%M:%S}] " + " | ".join(parts), flush=True)


# ---------- 关闭全部 worker ----------
def remote_shutdown(alive: list[Worker], env: dict[str, str], python: str) -> None:
    """通过 broker 控制通道广播 warm shutdown（跑完当前任务再退出）。

    Windows 上 CTRL_BREAK_EVENT  celery 并不处理（会瞬间被杀），taskkill 更是
    硬杀；远程 control shutdown 才是跨平台通用的优雅停机方式。broker 不通时
    超时降级到信号/强杀，不影响收敛。
    """
    dests = [f"worker{w.n}@flowerui" for w in alive]
    # celery 5.x click CLI：destination 走 -d（逗号分隔），超时走 -t
    cmd = [python, "-m", "celery", "-A", "tasks", "control",
           "-t", "10", "-d", ",".join(dests), "shutdown"]
    try:
        subprocess.run(cmd, cwd=str(TASKS_DIR), env=env, capture_output=True,
                       encoding="utf-8", errors="replace", timeout=20)
        info("已向 " + ", ".join(dests) + " 广播优雅停机指令（warm shutdown）")
    except subprocess.TimeoutExpired:
        warn("优雅停机指令超时，转入信号/强制停止")
    except OSError as e:
        warn(f"优雅停机指令执行失败: {e}，转入信号/强制停止")


def shutdown(workers: dict[int, Worker], env: dict[str, str], python: str, reason: str) -> None:
    info(f"========== {reason}：正在停止全部 worker ==========")
    alive = [w for w in workers.values() if w.proc is not None and w.proc.poll() is None]
    if alive:
        remote_shutdown(alive, env, python)
    # 远程指令可能没送达（worker 卡死/broker 抖动），补发本地信号
    for w in alive:
        if w.proc.poll() is None:
            signal_stop(w.proc)

    deadline = time.monotonic() + SHUTDOWN_TIMEOUT
    while time.monotonic() < deadline:
        if all(w.proc.poll() is not None for w in alive):
            break
        time.sleep(0.3)

    for w in alive:
        if w.proc.poll() is None:
            warn(f"worker{w.n} 未在 {SHUTDOWN_TIMEOUT}s 内退出，强杀进程树")
            force_kill(w.proc)

    for w in workers.values():
        if w.log_fh:
            w.log_fh.close()
        safe_unlink(pid_file(w.n))
    ok("全部 worker 已停止，脚本退出")


# ---------- 启动前清理陈旧 PID 文件 ----------
def cleanup_stale_pidfiles() -> None:
    """清理上一轮异常退出（硬杀/断电）留下的 PID 文件。

    硬杀父进程时 worker 作为独立进程组的子进程不会随之死亡（Windows 无
    父死子殉机制），若仍存活则保留 PID 文件并告警，交由用户决定 stop 或
    手动处理；已死的直接清掉，避免 status 误报。
    """
    live = []
    for n in all_pid_numbers():
        try:
            pid = int(pid_file(n).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = 0
        if pid and pid_alive(pid):
            live.append((n, pid))
        else:
            safe_unlink(pid_file(n))
    if live:
        warn("检测到上次异常退出后仍存活的 worker：" +
             "、".join(f"worker{n}(PID={pid})" for n, pid in live) +
             "。将与新 worker 并存消费队列，建议先 `python start_workers.py stop` 清理")


# ---------- 前台管家：启动 + 监控 ----------
def supervise(count: int, restart: bool, interval: float) -> None:
    if not (TASKS_DIR / "tasks.py").is_file():
        error(f"未找到任务定义: {TASKS_DIR / 'tasks.py'}")
        sys.exit(1)

    s = broker_settings(load_conf(RUNTIME_ENV))
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["FLOWER_BROKER_URL"] = s["broker_url"]
    env["FLOWER_BROKER_TRANSPORT_OPTIONS"] = s["transport_options"]
    env["FLOWER_RESULT_BACKEND"] = s["result_backend"]

    info(f"Broker:         {s['broker_url']}")
    info(f"传输选项:       {s['transport_options'] or '（无）'}")
    info(f"Result backend: {s['result_backend']}")
    info(f"消费队列:       {s['queues']}")

    python = detect_python()
    concurrency = os.getenv("WORKER_CONCURRENCY", "4")
    pool = os.getenv("WORKER_POOL", "threads")  # Windows 必须 threads/solo

    safe_unlink(STOP_MARKER)  # 清掉上一轮外部 stop 的残留标记
    LOGS_DIR.mkdir(parents=True, exist_ok=True)  # 确保日志目录存在
    cleanup_stale_pidfiles()              # 清理硬杀残留的 PID 文件

    info(f"========== 启动 {count} 个 worker（pool={pool}, 并发={concurrency}） ==========")
    info("worker 均为本脚本的子进程（同一终端，不弹新窗口）；Ctrl+C 停止脚本并带走全部 worker")
    workers: dict[int, Worker] = {}
    for n in range(1, count + 1):
        w = Worker(n)
        # 清掉上一轮日志：celery --logfile 是追加写，残留的 ready. 行会让
        # 就绪检测假阳性
        log_file(n).write_text("", encoding="utf-8")
        launch_worker(w, env, s["queues"], pool, concurrency, python)
        workers[n] = w
        ok(f"worker{n}@flowerui 已启动 (PID={w.proc.pid}), 日志: {log_file(n)}")

    # ---------- 信号处理：Ctrl+C / 外部 SIGTERM -> 优雅停机 ----------
    stop_flag = {"stop": False, "reason": "Ctrl+C"}

    def on_signal(signum, _frame):
        if not stop_flag["stop"]:
            stop_flag["stop"] = True
            stop_flag["reason"] = "收到 Ctrl+C" if signum == signal.SIGINT else f"收到信号 {signum}"

    signal.signal(signal.SIGINT, on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, on_signal)

    if IS_WINDOWS:
        # CREATE_NEW_PROCESS_GROUP 创建的进程组默认禁用 Ctrl+C（MSDN 行为）。
        # 本进程正常是从终端前台启动（本就启用），此处是防御性设置：万一被
        # 别的程序以"新进程组"方式拉起来（或测试框架模拟 Ctrl+C），也能收到。
        try:
            ctypes.windll.kernel32.SetConsoleCtrlHandler(None, False)
        except Exception:
            pass

    # ---------- 监控循环 ----------
    ready_deadline = time.monotonic() + READY_TIMEOUT
    ready_done = False
    last_report = 0.0
    info("等待 worker 就绪...（Ctrl+C 可随时中断）")
    try:
        while not stop_flag["stop"]:
            now = time.monotonic()

            # 1) 外部 stop 命令落下标记 -> 监控循环退出
            if STOP_MARKER.exists():
                stop_flag["stop"] = True
                stop_flag["reason"] = "外部 stop 命令"
                break

            # 2) 回收已退出的 worker：报告 + 按需重启
            for w in workers.values():
                if w.proc is None or w.proc.poll() is None:
                    continue
                if not w.exit_reported:
                    w.exit_reported = True
                    if w.proc.returncode == 0:
                        info(f"worker{w.n} 正常退出 (code=0)")
                    else:
                        error(f"worker{w.n} 异常退出 (code={w.proc.returncode})，日志: {log_file(w.n)}")
                # 外部 stop 刚落标记时不要重启（否则会出现"杀了又起"的重启风暴），
                # 保持死亡状态，下一轮循环顶部看到标记即整体停机
                if restart and not w.gave_up and not STOP_MARKER.exists() \
                        and now - w.last_restart >= RESTART_DELAY:
                    if w.restarts >= MAX_RESTARTS:
                        w.gave_up = True
                        error(f"worker{w.n} 重启次数已达上限（{MAX_RESTARTS} 次），放弃自愈，请检查日志")
                    else:
                        w.restarts += 1
                        warn(f"worker{w.n} 第 {w.restarts} 次自动重启...")
                        launch_worker(w, env, s["queues"], pool, concurrency, python)
                        ok(f"worker{w.n} 已重启 (PID={w.proc.pid})")

            # 3) 就绪检测（日志出现 ready.）
            if not ready_done:
                if all(log_ready(w) for w in workers.values()):
                    ready_done = True
                    ok(f"{count}/{count} 个 worker 已就绪，进入监控（每 {interval:g}s 刷新状态）")
                elif now > ready_deadline:
                    ready_done = True
                    warn(f"等待 {READY_TIMEOUT}s 后仍有 worker 未就绪，请查看日志: {LOGS_DIR}/_worker_*.log")

            # 4) 周期状态报告
            if ready_done and now - last_report >= interval:
                report(workers)
                last_report = now

            # 5) 全部退出且无法自愈 -> 结束监控
            if all(
                (w.proc is None or w.proc.poll() is not None) and (not restart or w.gave_up)
                for w in workers.values()
            ):
                error("全部 worker 已退出且不会重启，监控结束")
                break

            time.sleep(0.5)
    finally:
        safe_unlink(STOP_MARKER)
        shutdown(workers, env, python, stop_flag["reason"])


# ---------- 外部停止（按 PID 文件） ----------
def stop_workers() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    info("========== 停止全部 @flowerui worker ==========")
    killed = 0
    for n in all_pid_numbers():
        try:
            pid = int(pid_file(n).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = 0
        if pid and pid_alive(pid):
            kill_pid_tree(pid)
            killed += 1
            info(f"worker{n}@flowerui 进程树已停止 (PID={pid})")
        else:
            warn(f"worker{n}@flowerui (PID={pid}) 未在运行或已被停止")
        safe_unlink(pid_file(n))
    if killed:
        ok(f"已停止 {killed} 个 worker")
    else:
        ok("没有运行中的 @flowerui worker")
    # 落下标记：若本脚本的监控循环正在运行，通知它退出（否则它会把 worker 重启回来）
    STOP_MARKER.write_text(str(time.time()), encoding="utf-8")


# ---------- 状态查询 ----------
def status_workers() -> int:
    nums = all_pid_numbers()
    if not nums:
        warn("没有通过本脚本启动的 worker")
        return 1
    found = 0
    for n in nums:
        try:
            pid = int(pid_file(n).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = 0
        if pid and pid_alive(pid):
            ok(f"worker{n}@flowerui 运行中 (PID={pid})")
            found += 1
        else:
            # 只提示不删：保留 PID 文件便于 stop 清理
            warn(f"worker{n}@flowerui 未在运行（PID 文件保留，stop 时清理）")
    return 0 if found else 1


# ---------- 日志查看 ----------
def logs_workers(n: int, follow: bool) -> None:
    logf = log_file(n)
    if not logf.is_file():
        error(f"日志文件不存在: {logf}（worker {n} 未启动过？）")
        sys.exit(1)
    if not follow:
        lines = logf.read_text(encoding="utf-8", errors="ignore").splitlines()
        print("\n".join(lines[-40:]))
        return
    info(f"跟踪 {logf}（Ctrl+C 退出）...")
    with open(logf, encoding="utf-8", errors="ignore") as f:
        f.seek(0, os.SEEK_END)
        try:
            while True:
                line = f.readline()
                if line:
                    print(line, end="", flush=True)
                else:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            return


# ---------- 命令分发 ----------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="FlowerUI Celery Worker 批量启动脚本（跨 Windows/Linux，无需 nohup）"
    )
    parser.add_argument("cmd", nargs="?", default="start",
                        choices=["start", "stop", "restart", "status", "logs", "help"],
                        help="子命令（默认 start：前台启动并持续监控，Ctrl+C 停止）")
    parser.add_argument("count", nargs="?", type=int, default=DEFAULT_COUNT,
                        help=f"worker 数量，仅 start/restart 有效（默认 {DEFAULT_COUNT}）")
    parser.add_argument("--no-restart", action="store_true",
                        help="worker 崩溃后不自动重启（默认自动重启，单个最多 5 次）")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="监控状态刷新间隔秒数（默认 5）")
    parser.add_argument("-f", "--follow", action="store_true",
                        help="logs 子命令持续跟踪日志（等价 tail -f）")
    args = parser.parse_args()

    if args.cmd == "help":
        parser.print_help()
        print(f"""
常用示例：
  python start_workers.py start 4          # 前台启动 4 个 worker 并持续监控
  python start_workers.py start 4 --no-restart   # 崩溃不自动重启
  python start_workers.py start 4 --interval 2   # 每 2s 刷新一次状态
  python start_workers.py status           # 查看运行状态
  python start_workers.py logs 1 -f        # 跟踪第 1 个 worker 日志
  python send_tasks.py --count 10          # 随机发 10 个任务
  python start_workers.py stop             # 从另一个终端停止全部 worker

监控循环行为：
  - worker 异常退出 -> 自动重启（最多 5 次/个），达上限后放弃并提示查日志
  - 每 --interval 秒打印一行状态（PID / 运行时长 / 重启次数）
  - Ctrl+C -> 先优雅停止全部 worker（最多等 {SHUTDOWN_TIMEOUT}s），再退出脚本
  - 关终端 / 杀脚本 -> worker 作为子进程一并结束，不会残留

环境变量覆盖：
  FLOWER_BROKER_URL=redis://:YOUR_PASSWORD@127.0.0.1:6379/0 python start_workers.py start
  WORKER_CONCURRENCY=8 WORKER_POOL=prefork python start_workers.py start
""")
        return

    if args.cmd == "stop":
        stop_workers()
    elif args.cmd == "status":
        sys.exit(status_workers())
    elif args.cmd == "logs":
        logs_workers(args.count, args.follow)
    else:  # start / restart
        supervise(args.count, restart=not args.no_restart, interval=args.interval)


if __name__ == "__main__":
    main()
