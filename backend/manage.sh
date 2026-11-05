#!/bin/bash
# =============================================================================
# FlowerUI 后端服务管理脚本（后端专属，自根 manage.sh 拆分）
# -----------------------------------------------------------------------------
# 只管理后端（端口 5555），不涉及前端。前端产物已内置在 backend/app/static/，
# 生产模式直接由后端托管；前端源码开发请用根目录的 manage.sh dev。
#
# 与根 manage.sh 的区别：
#   - 停止时只杀 FlowerUI 后端进程（按 uvicorn 命令行特征 + 端口 5555 精确定位），
#     不会像根脚本那样强杀全部 python.exe，因此不会误伤 celery worker
#   - 不含前端构建/启动逻辑
#
# 用法（Git Bash）:
#   ./manage.sh dev             # 开发模式：停 + 起（--reload 热更新）
#   ./manage.sh dev --mock      # 开发模式 + 模拟数据（FLOWER_MOCK=true）
#   ./manage.sh dev --clean     # 开发模式 + 启动前清理历史日志
#   ./manage.sh restart         # 重启（等价于 dev，先停后起）
#   ./manage.sh run             # 生产模式：前台运行，单端口托管前端静态资源
#   ./manage.sh demo            # 演示模式：模拟集群，无需 broker
#   ./manage.sh deps            # 依赖：uv sync（按 uv.lock 精确还原，唯一入口）
#   ./manage.sh upgrade         # 依赖：uv sync --upgrade（升级到 py3.7 最新兼容版）
#   ./manage.sh config          # 配置体检：TOML 文件 / 环境变量 / 当前生效值
#   ./manage.sh stop            # 仅停止后端
#   ./manage.sh status          # 查看后端运行状态 + 生效配置摘要
#   ./manage.sh help            # 显示帮助
#
# worker 启动见 ./manage.sh workers（前台监控，Ctrl+C 停止）；随机发任务见 send_tasks.py。
#
# 端口约定：后端 API 5555（与 backend/app/main.py 保持一致）。
#
# 环境约定（2026-11 起，改动时务必保持）：
#   - 虚拟环境固定为 backend/.venv（uv 创建，Python 3.7.9，由 .python-version 钉死）。
#     依赖只走 `uv sync`，禁止 pip install -r requirements.txt / 手动改版本号。
#   - 静态默认配置 flowerui-settings.toml；界面改动落盘 flowerui.runtime.toml（TOML）。
#     优先级：TOML 文件 → FLOWER_ 前缀环境变量 → 代码默认值。
#   - 上述两个配置文件都是「相对当前工作目录」解析的，因此本脚本启动后端前
#     必须 cd 到 BACKEND_DIR。界面「重启系统」由 app/services/restart.py 以
#     cwd=backend/ 调用 `bash manage.sh restart`，路径一致。
#   - restart 路径不得执行 uv sync（会拖慢/阻断界面重启）；依赖同步只在
#     显式的 deps / upgrade / sync 命令中进行。
# =============================================================================

set -e

# ---------- 关键：禁用 MSYS 路径转换 ----------
# Git Bash 默认会把 taskkill 的 /F 改写为 F:/，导致 taskkill 全部失败
# （表现为"无效的参数/选项 - 'F:/'"）。此处全局禁用，保证 /F /T /PID
# 等参数原样传给 Windows 程序。
export MSYS_NO_PATHCONV=1

# ---------- 路径配置 ----------
BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$BACKEND_DIR/.."
# venv 定位顺序：backend/.venv（uv 标准环境）→ 根 .venv（旧约定，仅兼容）
if [ -x "$BACKEND_DIR/.venv/Scripts/python.exe" ] || [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
    VENV_DIR="$BACKEND_DIR/.venv"
elif [ -x "$ROOT/.venv/Scripts/python.exe" ] || [ -x "$ROOT/.venv/bin/python" ]; then
    VENV_DIR="$ROOT/.venv"
    VENV_LEGACY=true
else
    VENV_DIR=""
fi
BACKEND_PORT=5555
LOGS_DIR="$BACKEND_DIR/logs"   # 后端日志与 PID：backend/logs/（worker 在 backend/logs/workers/）

# 配置与依赖文件（均位于 backend/，且 runtime.toml 按 cwd 相对解析）
SETTINGS_TOML="$BACKEND_DIR/flowerui-settings.toml"   # 静态默认配置（可入库）
RUNTIME_TOML="$BACKEND_DIR/flowerui.runtime.toml"     # 界面改动落盘（重启生效）
PYPROJECT="$BACKEND_DIR/pyproject.toml"               # uv 依赖声明
UV_LOCK="$BACKEND_DIR/uv.lock"                        # uv 版本锁定
PY_VERSION_FILE="$BACKEND_DIR/.python-version"        # 钉死 Python 3.7


# ---------- 颜色输出 ----------
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ---------- 停止后端（精确定位，不误杀 celery worker） ----------
# 要点：
#   - 双重定位：PID 文件（start_backend 写入，--reload 时即 reloader 父进程）
#     + 端口 5555 监听者兜底；均以 taskkill /T 连进程树一起杀
#   - 按端口/命令行特征定位后端，celery worker（命令行特征是 celery）
#     不会误伤
#   - 仅当本端口确有监听时才执行兜底强杀，避免误伤其它无关进程
#   - Linux / macOS 走 pkill -f
stop_backend() {
    info "========== 停止后端服务（端口 $BACKEND_PORT） =========="

    local has_listener=false
    if command -v netstat &>/dev/null; then
        if netstat -ano 2>/dev/null | awk -v b=":$BACKEND_PORT" \
            '$4=="LISTENING" && $2 ~ (b "$") {found=1} END{exit !found}'; then
            has_listener=true
        fi
    fi

    if command -v taskkill &>/dev/null; then
        # ---------- Windows ----------
        # 1) PID 文件（本脚本启动时写入；--reload 模式下它是 reloader 父进程）
        local pidfile="$LOGS_DIR/_backend.pid"
        if [ -f "$pidfile" ]; then
            local pid
            pid=$(cat "$pidfile" 2>/dev/null || true)
            if [ -n "$pid" ]; then
                info "停止后端进程树 (PID=$pid)..."
                taskkill /F /T /PID "$pid" >/dev/null 2>&1 || true
            fi
            rm -f "$pidfile"
        fi
        # 2) 兜底：按端口提取监听 PID（PID 文件丢失 / 非本脚本启动时）
        if [ "$has_listener" = true ]; then
            for pid in $(netstat -ano 2>/dev/null | awk -v p=":$BACKEND_PORT" '$4=="LISTENING" && $2 ~ (p "$") {print $NF}' | grep -E '^[0-9]+$'); do
                info "停止端口 $BACKEND_PORT 上的进程 (PID=$pid)..."
                taskkill /F /T /PID "$pid" >/dev/null 2>&1 || true
            done
        fi
    elif command -v pkill &>/dev/null; then
        # ---------- Linux / macOS ----------
        pkill -f "uvicorn app.main:app" 2>/dev/null || true
        if command -v lsof &>/dev/null; then
            for pid in $(lsof -ti tcp:"$BACKEND_PORT" 2>/dev/null || true); do
                kill -9 "$pid" 2>/dev/null || true
            done
        fi
    fi

    # 等待进程退出，避免紧接着启动时端口仍被占用。
    # 用 bash 内建 sleep：外部 python 启动在部分环境（沙箱/安全策略）会被
    # 拦截或显著延迟，内建命令无此风险
    sleep 1
    # 端口未释放时明确告警（常见原因：残留 reloader 父进程）
    if [ "$has_listener" = true ] && netstat -ano 2>/dev/null | awk -v b=":$BACKEND_PORT" \
        '$4=="LISTENING" && $2 ~ (b "$") {found=1} END{exit !found}'; then
        warn "端口 $BACKEND_PORT 仍被占用，请检查是否有残留进程"
    fi
    if [ "$has_listener" = false ]; then
        ok "后端未在运行"
    else
        ok "后端已停止"
    fi
}

# ---------- 状态查询 ----------
# 除端口存活外，一并打印「解释器 / 配置文件 / 生效配置摘要」，
# 便于排查「界面改了 broker 但没生效」这类问题。
status_backend() {
    echo "---- 运行环境 ----"
    detect_python
    info "解释器:   $("$PYTHON" -V 2>&1)  ($PYTHON)"
    if [ -f "$PY_VERSION_FILE" ]; then
        info "钉死版本: $(cat "$PY_VERSION_FILE" 2>/dev/null)  (.python-version)"
    fi
    [ -f "$SETTINGS_TOML" ] && ok   "静态配置: $SETTINGS_TOML" \
                            || warn "静态配置缺失: $SETTINGS_TOML"
    [ -f "$RUNTIME_TOML" ]   && ok   "运行时配置: $RUNTIME_TOML（界面改动落盘于此）" \
                            || warn "运行时配置缺失: $RUNTIME_TOML（首次启动会自动生成）"
    local env_count
    env_count=$(env | grep -c '^FLOWER_' || true)
    [ "$env_count" -gt 0 ] && warn "检测到 $env_count 个 FLOWER_* 环境变量，其优先级高于 TOML 文件" \
                           || info "无 FLOWER_* 环境变量覆盖"

    echo "---- 服务状态 ----"
    if command -v netstat &>/dev/null && netstat -ano 2>/dev/null | awk -v b=":$BACKEND_PORT" \
        '$4=="LISTENING" && $2 ~ (b "$") {found=1} END{exit !found}'; then
        ok "后端正在运行: http://127.0.0.1:$BACKEND_PORT"
        printf "  healthcheck: "; curl -s --noproxy "*" "http://127.0.0.1:$BACKEND_PORT/healthcheck" || true
        echo ""
        # 从 /api/system 读取实际生效值（比读文件更可靠：含 env 覆盖与默认值）
        local sys_json
        sys_json=$(curl -s --noproxy "*" --max-time 5 "http://127.0.0.1:$BACKEND_PORT/api/system" 2>/dev/null || true)
        if [ -n "$sys_json" ]; then
            printf '%s' "$sys_json" | "$PYTHON" -c "
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print('  (无法解析 /api/system 响应)'); sys.exit(0)
for k in ('python_version', 'celery_version', 'broker_url', 'result_backend',
          'result_backend_configured', 'mock_mode'):
    if k in d:
        print('  %-26s %s' % (k + ':', d[k]))
" 2>/dev/null || printf '  %s\n' "$(printf '%s' "$sys_json" | head -c 300)"
        fi
        return 0
    fi
    warn "后端未运行"
    return 1
}

# ---------- 依赖检查 ----------
detect_python() {
    if [ -n "$VENV_DIR" ] && [ -x "$VENV_DIR/Scripts/python.exe" ]; then
        PYTHON="$VENV_DIR/Scripts/python.exe"
    elif [ -n "$VENV_DIR" ] && [ -x "$VENV_DIR/bin/python" ]; then
        PYTHON="$VENV_DIR/bin/python"
    elif command -v python3 &>/dev/null; then
        PYTHON="python3"
    elif command -v python &>/dev/null; then
        PYTHON="python"
    else
        error "未找到 Python，请先安装"
        exit 1
    fi
}

ensure_venv() {
    # dev_mode 与 start_backend 都会调用，避免重复做导入体检
    [ "${ENV_CHECKED:-false}" = true ] && return
    detect_python
    if [ -z "$VENV_DIR" ]; then
        error "未找到后端虚拟环境: $BACKEND_DIR/.venv"
        error "依赖统一由 uv 管理，请先执行: ./manage.sh deps（等价于 cd backend && uv sync）"
        exit 1
    fi
    if [ "${VENV_LEGACY:-false}" = true ]; then
        warn "当前用的是旧路径虚拟环境 $VENV_DIR；约定路径是 $BACKEND_DIR/.venv"
        warn "建议迁移: cd backend && uv sync（按 .python-version=3.7 重建）"
    fi
    if [ "${FLOWER_SKIP_ENV_CHECK:-}" = "1" ]; then
        ENV_CHECKED=true
        return
    fi
    local pyver
    pyver=$("$PYTHON" -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>/dev/null || echo "unknown")
    case "$pyver" in
        3.7.*) ok "Python $pyver（符合 .python-version）" ;;
        *)     warn "当前 Python $pyver；项目约定 3.7（$PY_VERSION_FILE），版本漂移可能导致依赖不兼容" ;;
    esac
    # 空壳 venv 是最常见的启动失败原因；kombu.Producer 还能顺带验出
    # importlib-metadata>=5 与 kombu 5.2.4 的不兼容。
    if ! "$PYTHON" -c "import fastapi, pydantic, celery, toml; from kombu import Producer" >/dev/null 2>&1; then
        error "后端依赖不完整或版本不兼容（空壳 venv / pydantic 2.x / importlib-metadata>=5）"
        error "请运行: ./manage.sh deps   # 按 uv.lock 精确还原"
        exit 1
    fi
    ENV_CHECKED=true
}

# ---------- 依赖管理：uv sync 是唯一入口 ----------
# 绝不放在 dev / restart 路径里自动执行：界面「重启系统」由
# app/services/restart.py 调用 `bash manage.sh restart`，此时联网解析依赖
# 会拖慢甚至阻断重启。依赖同步只由显式的 deps / sync / upgrade 触发。
require_uv() {
    if ! command -v uv &>/dev/null; then
        error "未找到 uv。后端依赖统一由 uv 管理（见 backend/README.md 第 3 节）"
        error "安装参考: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
}

_uv_run() {
    cd "$BACKEND_DIR" || exit 1
    info "执行: uv $*   (cwd=$BACKEND_DIR)"
    if ! uv "$@"; then
        error "uv $* 执行失败"
        exit 1
    fi
    ok "uv $* 完成"
    # uv add 会改 pyproject.toml / uv.lock，提醒随代码提交
    case "${1:-}" in
        add) info "别忘了把 pyproject.toml 与 uv.lock 一并提交" ;;
    esac
}

deps_check() {
    ensure_venv
    cd "$BACKEND_DIR" || exit 1
    info "========== 依赖体检（只读，不改动环境） =========="
    ok "uv:       $(uv --version 2>&1)"
    ok "Python:   $("$PYTHON" -V 2>&1)  ($PYTHON)"
    [ -f "$UV_LOCK" ] && ok "lock:     $UV_LOCK" \
                      || warn "lock 缺失: $UV_LOCK（运行 ./manage.sh deps 生成）"
    "$PYTHON" - <<'PY'
import importlib
mods = [
    ("fastapi", "fastapi"), ("starlette", "starlette"), ("pydantic", "pydantic"),
    ("celery", "celery"), ("kombu", "kombu"), ("redis", "redis"),
    ("toml", "toml"), ("httpx", "httpx"), ("websockets", "websockets"),
    ("importlib_metadata", "importlib-metadata"),
]
for mod, label in mods:
    try:
        m = importlib.import_module(mod)
        if mod == "importlib_metadata":
            v = m.version("importlib-metadata")
        elif mod == "pydantic":
            v = m.VERSION
        else:
            v = getattr(m, "__version__", "?")
        print("  %-24s %s" % (label, v))
    except Exception as exc:
        print("  %-24s 导入失败: %s" % (label, exc))
print("  ---- 关键约束 ----")
try:
    import pydantic
    assert pydantic.VERSION.startswith("1."), "pydantic 必须 <2（代码使用 v1 的 BaseSettings）"
    print("  [OK]   pydantic <2")
except AssertionError as exc:
    print("  [错误] %s" % exc)
try:
    import importlib_metadata
    major = int(importlib_metadata.version("importlib-metadata").split(".")[0])
    assert major < 5, "kombu 5.2.4 需要 importlib-metadata<5（entry_points().get()）"
    print("  [OK]   importlib-metadata <5")
except AssertionError as exc:
    print("  [错误] %s" % exc)
try:
    from kombu import Producer  # noqa: F401
    print("  [OK]   kombu Producer 可导入")
except Exception as exc:
    print("  [错误] kombu Producer 导入失败: %s" % exc)
PY
}

# 用法见 usage()：deps / sync / upgrade / deps --check / deps --add <pkg>
deps_cmd() {
    require_uv
    local sub="${1:-}"
    case "$sub" in
        --check|check)
            shift || true; deps_check ;;
        --upgrade|upgrade)
            shift || true; _uv_run sync --upgrade "$@" ;;
        --upgrade-package)
            shift || true
            if [ -z "${1:-}" ]; then
                error "用法: ./manage.sh deps --upgrade-package <包名>"
                exit 1
            fi
            _uv_run sync --upgrade-package "$@" ;;
        --add|add)
            shift || true
            if [ -z "${1:-}" ]; then
                error "用法: ./manage.sh deps --add <包名>"
                exit 1
            fi
            _uv_run add "$@" ;;
        sync)
            shift || true; _uv_run sync "$@" ;;
        "")
            _uv_run sync ;;
        *)
            # 其余一律当作 uv sync 的参数透传（--frozen / --dry-run / -v ...）
            _uv_run sync "$@" ;;
    esac
}

# ---------- 配置体检：TOML 文件 / 环境变量 / 生效值 ----------
# 重点拦住三类迁移期问题：文件解析失败、误用分节写法、result_backend 写成空串。
config_cmd() {
    ensure_venv
    cd "$BACKEND_DIR" || exit 1   # runtime.toml 按 cwd 解析，必须与后端启动一致
    info "========== 配置体检（TOML → FLOWER_* 环境变量 → 默认值） =========="
    "$PYTHON" - <<'PY'
import os
import re
from pathlib import Path
import toml

try:
    from app.core.config import Settings
    FIELDS = set(Settings.__fields__)
except Exception:
    FIELDS = set()
try:
    from app.services import runtime_config as _rc
    UI_FIELDS = {f.key for f in _rc.FIELDS} - FIELDS
except Exception:
    UI_FIELDS = set()
SECTION_NAMES = {"service", "celery", "routing", "capacity", "persistence",
                 "display", "auth", "demo", "broker", "worker", "monitor"}

def mask(value):
    if not isinstance(value, str):
        return value
    return re.sub(r"(://[^:@/?#]*:)([^@]+)(@)", r"\1******\3", value)

runtime_data = {}
for label, name in (("静态默认", "flowerui-settings.toml"),
                    ("运行时覆盖", "flowerui.runtime.toml")):
    p = Path(name)
    if not p.is_file():
        print("  [缺失] %-10s %s" % (label, name))
        continue
    try:
        data = toml.load(str(p))
    except Exception as exc:
        print("  [错误] %-10s %s 解析失败，整个文件会被忽略: %s" % (label, name, exc))
        print("         常见原因：写了 TOML 不支持的 `= null`；请改成注释行")
        continue
    if "runtime" in name:
        runtime_data = data
    sections = [k for k, v in data.items() if k in SECTION_NAMES and isinstance(v, dict)]
    ui_keys = [k for k in data if k in UI_FIELDS]
    unknown = [k for k in data
               if k not in FIELDS and k not in UI_FIELDS and k not in SECTION_NAMES]
    print("  [OK]   %-10s %s  (%d 个键)" % (label, name, len(data)))
    if sections:
        print("         [警告] 使用了分节 %s，这些配置不会生效，请改成顶层 KEY = VALUE" % sections)
    if ui_keys:
        print("         UI 专用键（由 runtime_config 管理，不进 Settings）: %s" % ui_keys)
    if unknown:
        print("         [提示] 未知键（回放时会被忽略）: %s" % unknown)
    if "broker_url" in data:
        print("         broker_url     = %s" % mask(data["broker_url"]))
    if "result_backend" in data:
        rb = data["result_backend"]
        if rb == "":
            print("         [错误] result_backend 写成空字符串，Celery 会抛 NotImplementedError")
        else:
            print("         result_backend = %s" % mask(rb))
    else:
        print("         result_backend = (未启用；非必须，保持注释即可)")

envs = sorted(k for k in os.environ if k.startswith("FLOWER_"))
if envs:
    print("  ---- FLOWER_* 环境变量（优先级最高，会覆盖 TOML） ----")
    for k in envs:
        v = os.environ[k]
        if any(s in k.upper() for s in ("PASSWORD", "SECRET", "TOKEN", "BROKER_URL", "BACKEND")):
            v = mask(v)
        print("    %s = %s" % (k, v))
else:
    print("  ---- 无 FLOWER_* 环境变量覆盖 ----")

print("  ---- 静态层生效值（Settings：静态 TOML + 环境变量，不含运行时覆盖） ----")
try:
    from app.core.config import settings
    for key in ("port", "broker_url", "broker_transport_options",
                "result_backend", "mock"):
        print("    %-26s %s" % (key + ":", mask(getattr(settings, key, "<无此字段>"))))
except Exception as exc:
    print("    [错误] 无法加载 app.core.config: %s" % exc)

overrides = {k: v for k, v in runtime_data.items() if k in FIELDS}
print("  ---- 运行时覆盖层（%d 项，应用 startup 时由 runtime_config.load() 回放） ----"
      % len(overrides))
for key in ("broker_url", "broker_transport_options", "result_backend", "mock"):
    if key in overrides:
        print("    %-26s %s" % (key + ":", mask(overrides[key])))
print("  查看服务真正生效值: ./manage.sh status（需后端在运行，读取 /api/system）")
print("  界面改动落盘到 flowerui.runtime.toml，需点「重启系统」或 ./manage.sh restart 生效")
PY
}

# ---------- 启动后端 ----------
# $1: 模式 dev(默认) | run(前台) | demo(mock)
# $2+: --mock（仅 dev 有意义；demo 强制 mock）/ --reload（dev 热更新，默认关）
# 说明：--reload 默认关闭。WatchFiles 对日志文件的写入也可能触发 reload 循环，
# 且 FlowerUI 有 restart.py -> manage.sh restart 的显式重启链路，热更新非必需；
# 确需时可显式传 --reload。
start_backend() {
    local mode="${1:-dev}"
    shift || true
    local mock=false
    local reload=false
    for arg in "$@"; do
        case $arg in
            --mock)   mock=true ;;
            --reload) reload=true ;;
        esac
    done
    RELOAD=$reload
    ensure_venv
    # 必须切到 backend/：flowerui.runtime.toml 按「当前工作目录」解析
    # （见 app/services/runtime_config.py 的 RUNTIME_FILE），在别处启动会
    # 读不到界面保存的配置，甚至另建一份空的运行时文件。
    cd "$BACKEND_DIR"
    export PYTHONIOENCODING=utf-8

    if [ "$mode" = "demo" ]; then
        mock=true
    fi
    if [ "$mock" = true ]; then
        # FLOWER_ 前缀环境变量优先级高于 TOML，故 --mock 可临时覆盖
        # flowerui-settings.toml / flowerui.runtime.toml 里的 mock 设置
        export FLOWER_MOCK=true
        export FLOWER_MOCK_WORKERS=4
        export FLOWER_MOCK_SEED_TASKS=260
        info "模拟模式已启用"
    else
        unset FLOWER_MOCK
    fi

    if [ "$mode" = "run" ]; then
        # 生产模式：前台运行（exec，日志直接进终端）
        info "========== 启动后端（生产模式，端口 $BACKEND_PORT） =========="
        ok "访问地址: http://127.0.0.1:$BACKEND_PORT"
        exec "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port $BACKEND_PORT
    fi

    LOG_PREFIX=$(date +%Y%m%d_%H%M%S)
    mkdir -p "$LOGS_DIR" "$LOGS_DIR/workers"
    LOG_FILE="$LOGS_DIR/uvicorn_${LOG_PREFIX}.log"
    ERR_FILE="$LOGS_DIR/uvicorn_err_${LOG_PREFIX}.log"
    local reload_flag=""
    [ "$RELOAD" = true ] && reload_flag="--reload"
    info "启动后端 (端口 $BACKEND_PORT, 模式=$mode${reload_flag:+, $reload_flag})..."
    # 后台启动 + disown：脱离 shell 的 SIGHUP，保证"关闭终端不停止服务"。
    # 不用 nohup：MSYS 的 nohup 可能 fork 子进程后自行退出，导致 $! 与真正
    # 进程对不上；直接 & 时 $! 即 python 进程，/proc/<pid>/winpid 拿到的
    # Windows PID 有效，stop 时 taskkill /T 连子进程树一起杀。
    "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port $BACKEND_PORT $reload_flag \
        > "$LOG_FILE" 2> "$ERR_FILE" &
    BACKEND_PID=$!
    disown "$BACKEND_PID" 2>/dev/null || true
    # 记录 Windows PID：MSYS 的 $! 与 Windows PID 不同，taskkill 需要 Windows PID。
    # /proc/<pid>/winpid 是 MSYS 提供的映射；读取失败（如 Linux）时回退 $!。
    WIN_PID=$(cat "/proc/$BACKEND_PID/winpid" 2>/dev/null || echo "$BACKEND_PID")
    echo "$WIN_PID" > "$LOGS_DIR/_backend.pid"
    info "后端 PID: $BACKEND_PID (Windows PID: $WIN_PID)"
    i=0
    while [ $i -lt 10 ]; do
        if curl -s --noproxy "*" "http://127.0.0.1:$BACKEND_PORT/api/config" > /dev/null 2>&1; then
            ok "后端服务就绪（耗时 $((i + 1)) 秒）"
            break
        fi
        sleep 1
        i=$((i + 1))
        if [ $i -eq 10 ]; then
            warn "后端启动超时，请检查日志: $LOG_FILE"
        fi
    done
}

# ---------- 开发模式：停 + 起 ----------
dev_mode() {
    local MOCK=false
    local CLEAN=false
    local RELOAD=false
    for arg in "$@"; do
        case $arg in
            --mock)   MOCK=true ;;
            --clean)  CLEAN=true ;;
            --reload) RELOAD=true ;;
            *)        warn "未知参数: $arg" ;;
        esac
    done

    ensure_venv
    stop_backend

    if [ "$CLEAN" = true ]; then
        clean_logs
    fi

    info "========== 启动后端（开发模式） =========="
    ok "Python: $PYTHON"
    if [ "$MOCK" = true ] && [ "$RELOAD" = true ]; then
        start_backend dev --mock --reload
    elif [ "$MOCK" = true ]; then
        start_backend dev --mock
    elif [ "$RELOAD" = true ]; then
        start_backend dev --reload
    else
        start_backend dev
    fi

    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}  FlowerUI 后端已就绪！${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""
    echo -e "  后端 API:    http://127.0.0.1:${BACKEND_PORT}"
    echo -e "  模拟模式:    $([ "$MOCK" = true ] && echo '已启用' || echo '已禁用')"
    echo ""
    echo -e "  后端日志:    ${LOGS_DIR}/uvicorn_*.log"
    echo -e "  Worker 日志: ${LOGS_DIR}/workers/_worker_*.log"
    echo -e "  启动 worker: ./manage.sh workers  或  ${BACKEND_DIR}/start_workers.py start"
    echo -e "  随机发任务:  ${BACKEND_DIR}/send_tasks.py"
    echo ""
    echo -e "  ${YELLOW}关闭终端不会停止服务（已在后台运行）${NC}"
    echo -e "  ${YELLOW}停止服务: ./manage.sh stop${NC}"
    echo ""
}

# ---------- worker 启动（前台，调用 start_workers.py 监控模式） ----------
# 设计：所有命令前台执行，不弹新窗口、不后台守护。
#   ./manage.sh workers [N=4] [--no-restart] [--interval 秒]
# start_workers.py 通过 _broker_env.resolve_conf_path() 优先读
# backend/flowerui.runtime.toml（兼容旧 .env），因此界面改的 broker
# 对 worker 同样生效；这里只做前台透传，不再重复拼装 broker 参数。
workers_cmd() {
    ensure_venv
    cd "$BACKEND_DIR"
    export PYTHONIOENCODING=utf-8
    info "========== 前台启动 celery worker（Ctrl+C 停止并带走全部 worker） =========="
    # 用 exec 让 python 接管前台，Ctrl+C 直达 start_workers.py 的监控循环
    exec "$PYTHON" start_workers.py start "$@"
}

# ---------- 清理历史日志（backend/logs/ 下 *.log，保留 PID） ----------
clean_logs() {
    info "========== 清理历史日志 =========="
    mkdir -p "$LOGS_DIR" "$LOGS_DIR/workers"
    rm -f "$LOGS_DIR"/*.log 2>/dev/null || true
    rm -f "$LOGS_DIR"/workers/*.log 2>/dev/null || true
    # 兼容旧路径残留
    rm -f "$BACKEND_DIR"/_uvicorn*.log "$BACKEND_DIR"/_server_stdout.log 2>/dev/null || true
    rm -f "$BACKEND_DIR"/_*.pid "$BACKEND_DIR"/_worker_*.log "$BACKEND_DIR"/_workers.stopped 2>/dev/null || true
    ok "历史日志已清理（PID 文件保留在 $LOGS_DIR）"
}

# ---------- 帮助 ----------
usage() {
    echo "FlowerUI 后端服务管理脚本（自根 manage.sh 拆分，仅管理后端）"
    echo ""
    echo "用法: ./manage.sh [命令] [选项]"
    echo ""
    echo "服务命令:"
    echo "  dev        开发模式：停 + 起（--reload 默认关，可显式开启热更新）"
    echo "  restart    重启（等价于 dev，先停后起；界面「重启系统」走此命令）"
    echo "  run        生产模式：前台运行，单端口托管前端静态资源"
    echo "  demo       演示模式：模拟集群，无需 broker"
    echo "  stop       停止后端（精确定位，不误杀 celery worker）"
    echo "  status     查看运行环境 + 后端状态 + 生效配置摘要"
    echo "  clean      清理 backend/logs/ 下历史日志（保留 PID）"
    echo "  workers    前台启动并监控 celery worker（Ctrl+C 停止）"
    echo ""
    echo "依赖命令（uv 为唯一入口，禁止 pip install -r requirements.txt）:"
    echo "  deps                              uv sync（按 uv.lock 精确还原）"
    echo "  deps --upgrade                    uv sync --upgrade（升级到 py3.7 最新兼容版）"
    echo "  deps --upgrade-package <包名>     uv sync --upgrade-package <包名>"
    echo "  deps --add <包名>                 uv add <包名>（改 pyproject.toml + uv.lock）"
    echo "  deps --check                      只读体检：版本清单 + 两个必要上界"
    echo "  deps --frozen                     等价于 uv sync --frozen（参数可透传）"
    echo "  sync / upgrade                    deps / deps --upgrade 的快捷别名"
    echo ""
    echo "配置命令:"
    echo "  config     配置体检：两个 TOML 是否可解析 / 有无分节误用 /"
    echo "             FLOWER_* 覆盖 / result_backend 是否误写成空串 / 生效值"
    echo ""
    echo "选项（仅 dev / restart 支持）:"
    echo "  --mock     启用模拟模式（FLOWER_MOCK=true，优先级高于 TOML）"
    echo "  --clean    启动前清理历史日志"
    echo "  --reload   开启 uvicorn 热更新（默认关；WatchFiles 可能被日志写入触发"
    echo "             reload 循环，确需热更新时显式开启）"
    echo ""
    echo "环境约定:"
    echo "  venv      backend/.venv（uv 创建，Python 3.7.9，由 .python-version 钉死）"
    echo "  静态配置  backend/flowerui-settings.toml（扁平 KEY = VALUE，不要分节）"
    echo "  运行时    backend/flowerui.runtime.toml（界面改动落盘，重启生效）"
    echo "  优先级    TOML 文件 → FLOWER_* 环境变量 → 代码默认值"
    echo "  跳过体检  FLOWER_SKIP_ENV_CHECK=1 ./manage.sh dev"
    echo ""
    echo "worker 启动: ./manage.sh workers [N=4]  前台启动 N 个 worker 并持续监控（Ctrl+C 停止）"
    echo "            其它操作（stop/status/logs）直接用 start_workers.py："
    echo "            python start_workers.py status | stop | logs 1 -f"
    echo "            随机发任务: python send_tasks.py [--count N]"
    echo ""
    echo "示例:"
    echo "  ./manage.sh deps              # 首次安装 / 重装依赖"
    echo "  ./manage.sh deps --check      # 确认 pydantic<2 与 importlib-metadata<5"
    echo "  ./manage.sh config            # 排查「界面改了 broker 没生效」"
    echo "  ./manage.sh dev --mock        # 开发模式 + 模拟数据"
    echo "  ./manage.sh run               # 生产模式"
}

# ---------- 命令分发 ----------
case "${1:-dev}" in
    dev|restart)    shift || true; dev_mode "$@" ;;
    run|start)      start_backend run ;;
    demo)           start_backend demo ;;
    stop)           stop_backend ;;
    status)         status_backend ;;
    clean)          clean_logs ;;
    workers)        shift || true; workers_cmd "$@" ;;
    deps|sync)      shift || true; deps_cmd "$@" ;;
    upgrade)        shift || true; deps_cmd --upgrade "$@" ;;
    config)         config_cmd ;;
    help|-h|--help) usage ;;
    *)              usage; exit 1 ;;
esac
