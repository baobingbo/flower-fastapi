"""触发后端自身重启 + 重启状态机（可靠性与健康检查）。

设计要点
--------
1. 重启通过执行 ``manage.sh restart`` 脚本（先停后起）。Windows 下自动寻找
   Git Bash（环境变量 FLOWER_BASH → PATH → Git 默认安装位置），找不到时把
   失败写入状态文件，前端据此提示，而不是静默无反应。
2. **重启状态机**（``flowerui.restart.json``，可用 FLOWER_RESTART_STATE_FILE 覆盖）：
   - 触发前写 pending：{status, requested_at, pid, script, interpreter}
   - 新进程启动时调 ``settle_on_startup()``：旧 pid 已死且不是当前进程
     （或 pid 复用：当前进程启动时间晚于请求时间）→ success
   - 仍是旧进程且超过 GRACE_SECONDS → status 接口报 timeout（脚本未生效）
3. ``GET /api/system/restart/status``（routers/system.py）暴露状态机结果，
   供前端「重启健康检查」轮询：页面重载后用 started_at > requested_at
   确认新进程已接管。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict

logger = logging.getLogger("flowerui.restart")

# 重启脚本路径（可通过环境变量覆盖）
RESTART_SCRIPT = os.environ.get(
    "FLOWER_RESTART_SCRIPT",
    os.path.join(os.path.dirname(__file__), "../../..", "manage.sh"),
)

# 重启状态文件（记录 pending/success/failed，跨进程可读）。
# t4 收尾④ 同类修复：默认路径锚定 backend 目录（与 audit.py 相同方式），
# 否则新旧进程 CWD 不一致时状态文件互不可见，健康检查会静默失效。
_BACKEND_DIR = Path(__file__).resolve().parents[2]  # services/ → app/ → backend/
STATE_FILE = Path(
    os.environ.get("FLOWER_RESTART_STATE_FILE")
    or str(_BACKEND_DIR / "flowerui.restart.json")
).resolve()

# 仍是旧进程时，超过该秒数认为重启超时（脚本未生效）
GRACE_SECONDS = 180

# 当前进程启动时间（epoch 秒），供健康检查比对
_STARTED_AT = time.time()


def _pid_alive(pid: int) -> bool:
    """跨平台检查进程是否存活。"""
    if not pid or pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:  # noqa: BLE001 - 存活探测失败按不存在处理
        return False


def _read_state() -> Dict:
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}


def _write_state(state: Dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        logger.exception("写入重启状态文件失败: %s", STATE_FILE)


def find_interpreter() -> str:
    """查找可执行 manage.sh 的 shell 解释器（Windows 优先 Git Bash）。"""
    if os.name != "nt":
        for cand in ("bash", "sh"):
            if shutil.which(cand):
                return cand
        return "bash"
    env = os.environ.get("FLOWER_BASH")
    if env and os.path.exists(env):
        return env
    for cand in ("bash", "git-bash"):
        found = shutil.which(cand)
        if found:
            return found
    for default in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ):
        if os.path.exists(default):
            return default
    return "bash"  # 交给 Popen 抛错并写入状态文件


def describe_restart_command() -> Dict:
    """返回重启脚本与解释器，便于调试与前端展示。"""
    return {"script": RESTART_SCRIPT, "interpreter": find_interpreter()}


def restart_later(delay: float = 1.2) -> Dict:
    """在后台延迟后执行重启脚本，使运行时配置变更生效。

    延迟是为了让调用方（前端）先收到 HTTP 200 响应，再真正重启服务。
    触发前把 pending 状态写入状态文件；脚本不存在 / 执行异常时写入
    failed + error，可通过 ``GET /api/system/restart/status`` 查询。
    """
    state: Dict = {
        "status": "pending",
        "requested_at": time.time(),
        "pid": os.getpid(),
        "script": os.path.abspath(RESTART_SCRIPT),
        "interpreter": find_interpreter(),
    }
    _write_state(state)

    def _run() -> None:
        try:
            logger.info(
                "准备重启 FlowerUI 服务（解释器: %s, 脚本: %s）",
                state["interpreter"],
                RESTART_SCRIPT,
            )
            time.sleep(delay)
            if not os.path.exists(RESTART_SCRIPT):
                raise FileNotFoundError(f"重启脚本未找到: {RESTART_SCRIPT}")
            subprocess.Popen(
                [state["interpreter"], RESTART_SCRIPT, "restart"],
                cwd=os.path.dirname(os.path.abspath(RESTART_SCRIPT)),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            logger.error("%s", exc)
            state.update(
                {"status": "failed", "error": str(exc)[:300], "failed_at": time.time()}
            )
            _write_state(state)
        except Exception as exc:  # noqa: BLE001 - 重启失败必须留下痕迹
            logger.exception("后端重启失败")
            state.update(
                {"status": "failed", "error": str(exc)[:300], "failed_at": time.time()}
            )
            _write_state(state)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return state


def settle_on_startup() -> None:
    """新进程启动时调用：把 pending 的重启状态收口。

    - 旧 pid 不是当前进程且已死 → success（重启确实发生了）；
    - pid 等于当前进程但本进程启动时间晚于请求时间 → pid 复用，同样判 success；
    - 否则（仍是发起重启的旧进程）保持 pending，由 status() 按时长判
      in_progress / timeout。
    """
    state = _read_state()
    if not state or state.get("status") != "pending":
        return
    old_pid = state.get("pid")
    try:
        requested_at = float(state.get("requested_at") or 0)
    except (TypeError, ValueError):
        requested_at = 0
    now = time.time()

    def _success() -> None:
        state["status"] = "success"
        state["completed_at"] = now
        _write_state(state)

    if old_pid and old_pid != os.getpid() and not _pid_alive(int(old_pid)):
        _success()
        logger.info("重启完成：新进程 %d 已接管（旧进程 %s）", os.getpid(), old_pid)
    elif old_pid and old_pid == os.getpid() and requested_at > 0 and _STARTED_AT > requested_at:
        _success()
        logger.info("重启完成（pid 复用）：当前进程 %d 启动时间晚于请求时间", os.getpid())


def status() -> Dict:
    """当前重启状态，供 GET /api/system/restart/status 使用。

    返回：{status: idle|in_progress|success|failed|timeout,
           requested_at, completed_at?, failed_at?, pid, script, interpreter,
           error?, current_pid, started_at, hint?}
    """
    now = time.time()
    state = _read_state()
    base: Dict = {
        "current_pid": os.getpid(),
        "started_at": _STARTED_AT,
        "script": os.path.abspath(RESTART_SCRIPT),
    }
    if not state:
        return {"status": "idle", **base}

    out: Dict = {**base, **state}
    if state.get("status") != "pending":
        return out

    try:
        requested_at = float(state.get("requested_at") or 0)
    except (TypeError, ValueError):
        requested_at = 0
    old_pid = state.get("pid")

    if old_pid and old_pid == os.getpid():
        if requested_at and now - requested_at > GRACE_SECONDS:
            out["status"] = "timeout"
            out["hint"] = (
                "重启脚本可能未生效（bash/脚本路径/权限问题），服务仍在旧进程上运行；"
                "可检查后端日志或手动执行 manage.sh restart"
            )
            return out
        out["status"] = "in_progress"
        return out
    if old_pid and _pid_alive(int(old_pid)):
        out["status"] = "in_progress"
        out["hint"] = "旧进程仍存活，请确认是否存在多实例冲突"
        return out
    # 旧进程已死且本进程为新进程（settle 未收口的兜底）
    out["status"] = "success"
    out.setdefault("completed_at", now)
    return out
