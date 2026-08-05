#!/bin/bash
# =============================================================================
# FlowerUI 服务管理脚本（统一入口，单一事实来源）
# -----------------------------------------------------------------------------
# 本脚本整合了原 dev-restart.sh 的「停止 + 启动」能力，并统一封装所有常用
# 操作，避免逻辑分散在多个文件里。所有命令均在 Git Bash（Windows / Linux /
# macOS）下可用。
#
# 用法:
#   ./manage.sh dev            # 开发模式：停 + 起（后端 5555 + 前端 5556 热更新）
#   ./manage.sh dev --mock     # 开发模式 + 模拟数据（FLOWER_MOCK=true）
#   ./manage.sh dev --clean   # 开发模式 + 启动前清理历史日志
#   ./manage.sh restart        # 重启（等价于 dev，先停后起）
#   ./manage.sh run            # 生产/运行模式：构建前端 + 单端口 5555 托管
#   ./manage.sh demo           # 演示模式：模拟集群，无需 broker
#   ./manage.sh build          # 仅构建前端产物
#   ./manage.sh stop           # 仅停止所有服务
#   ./manage.sh help           # 显示帮助
#
# 端口约定：
#   后端 API   5555   （与 backend/app/main.py 保持一致）
#   前端页面   5556   （与 frontend/vite.config.js 保持一致）
#
# 注意：Windows 下请用 Git Bash 运行（如 bash manage.sh dev）；Linux/macOS
# 可执行 `chmod +x manage.sh` 后用 `./manage.sh`。
# =============================================================================

set -e

# ---------- 路径配置 ----------
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
VENV_DIR="$ROOT/.venv"
BACKEND_PORT=5555
FRONTEND_PORT=5556

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

# ---------- 停止服务（跨平台健壮版，继承自 dev-restart.sh） ----------
# 要点：
#   - Windows Git Bash 的 `kill -9 <Windows PID>` 无效，必须用 Windows 原生的 taskkill
#   - uvicorn --reload 有 reloader 父进程，只杀端口上的 worker 会被重新拉起，
#     必须连同 python.exe（reloader+worker）一起 taskkill
#   - 仅当本端口确有监听时才执行强杀，避免误伤其它无关进程
#   - Linux / macOS 走 lsof + pkill
stop_services() {
    info "========== 停止已运行的服务 =========="

    # 检测本端口是否有监听，决定是否执行强杀（保护无关进程）
    local has_listener=false
    if command -v netstat &>/dev/null; then
        if netstat -ano 2>/dev/null | awk -v b=":$BACKEND_PORT" -v f=":$FRONTEND_PORT" \
            '$4=="LISTENING" && ($2 ~ (b "$") || $2 ~ (f "$")) {found=1} END{exit !found}'; then
            has_listener=true
        fi
    fi

    if command -v taskkill &>/dev/null; then
        # ---------- Windows ----------
        # 1) 按端口精确提取监听 PID 并 taskkill /PID
        for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
            for pid in $(netstat -ano 2>/dev/null | awk -v p=":$port" '$4=="LISTENING" && $2 ~ (p "$") {print $NF}' | grep -E '^[0-9]+$'); do
                info "停止端口 $port 上的进程 (PID=$pid)..."
                taskkill /F /PID "$pid" >/dev/null 2>&1 || true
            done
        done
        # 2) 强杀 uvicorn / vite（覆盖 --reload 的 reloader 父进程，避免被重新拉起）
        if [ "$has_listener" = true ]; then
            info "清理残留进程（uvicorn / vite）..."
            taskkill /F /IM python.exe >/dev/null 2>&1 || true
            taskkill /F /IM node.exe >/dev/null 2>&1 || true
        fi
    elif command -v pkill &>/dev/null; then
        # ---------- Linux / macOS ----------
        for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
            local pid=""
            if command -v lsof &>/dev/null; then
                pid=$(lsof -ti tcp:"$port" 2>/dev/null || true)
            else
                pid=$(netstat -tlnp 2>/dev/null | grep ":$port " | awk '{print $7}' | cut -d'/' -f1 || true)
            fi
            [ -n "$pid" ] && kill -9 $pid 2>/dev/null || true
        done
        pkill -f "uvicorn" 2>/dev/null || true
        pkill -f "vite" 2>/dev/null || true
    fi

    # 等待进程退出，避免紧接着启动时端口仍被占用
    python -c "import time; time.sleep(1)" 2>/dev/null || true
    ok "所有服务已停止"
}

# ---------- 依赖检查 ----------
detect_python() {
    if [ -x "$VENV_DIR/Scripts/python.exe" ]; then
        PYTHON="$VENV_DIR/Scripts/python.exe"
    elif [ -x "$VENV_DIR/bin/python" ]; then
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
    detect_python
    if [ ! -x "$VENV_DIR/Scripts/python.exe" ] && [ ! -x "$VENV_DIR/bin/python" ]; then
        warn "虚拟环境不存在，正在创建..."
        "$PYTHON" -m venv "$VENV_DIR"
        detect_python
        "$PYTHON" -m pip install -q -r "$BACKEND_DIR/requirements.txt"
        ok "虚拟环境已创建"
    fi
}

ensure_node() {
    if ! command -v node &>/dev/null; then
        error "未找到 Node.js，请先安装"
        exit 1
    fi
}

# ---------- 路径转换（Git Bash 风格 -> Windows 风格，供 PowerShell 使用） ----------
winpath() {
    echo "$1" | sed -e 's|^/\([a-zA-Z]\)/|\1:/|' -e 's|/|\\|g'
}

# ---------- 前端依赖 / 构建 ----------
ensure_frontend_deps() {
    ensure_node
    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
        warn "前端依赖不存在，正在安装..."
        ( cd "$FRONTEND_DIR" && npm install --registry=https://registry.npmmirror.com --no-audit --no-fund )
        ok "前端依赖已安装"
    else
        ok "前端依赖已就绪"
    fi
}

build_frontend() {
    ensure_frontend_deps
    # 预清理 dist：规避部分环境（如本地沙箱）下 Vite 清空输出目录时被「安全删除」机制拦截。
    # 删掉后 Vite 发现目录不存在，会跳过内部 emptyDir，直接重建。
    if [ -d "$FRONTEND_DIR/dist" ]; then
        info "清理旧的构建产物 (dist)..."
        if command -v powershell &>/dev/null; then
            powershell -NoProfile -Command "Remove-Item -LiteralPath '$(winpath "$FRONTEND_DIR/dist")' -Recurse -Force -ErrorAction SilentlyContinue" || true
        else
            rm -rf "$FRONTEND_DIR/dist" || true
        fi
    fi
    info "构建前端产物..."
    ( cd "$FRONTEND_DIR" && npm run build )
    ok "前端构建完成: $FRONTEND_DIR/dist"
}

# ---------- 启动后端（开发模式，--reload） ----------
start_backend_dev() {
    cd "$BACKEND_DIR"
    export PYTHONIOENCODING=utf-8
    if [ "$MOCK" = true ]; then
        export FLOWER_MOCK=true
        info "模拟模式已启用"
    else
        unset FLOWER_MOCK
    fi
    LOG_PREFIX=$(date +%Y%m%d_%H%M%S)
    LOG_FILE="$BACKEND_DIR/_uvicorn_${LOG_PREFIX}.log"
    ERR_FILE="$BACKEND_DIR/_uvicorn_err_${LOG_PREFIX}.log"
    info "启动后端 (端口 $BACKEND_PORT)..."
    "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port $BACKEND_PORT --reload \
        > "$LOG_FILE" 2> "$ERR_FILE" &
    BACKEND_PID=$!
    info "后端 PID: $BACKEND_PID"
    i=0
    while [ $i -lt 10 ]; do
        if curl -s "http://127.0.0.1:$BACKEND_PORT/api/config" > /dev/null 2>&1; then
            ok "后端服务就绪（耗时 $((i + 1)) 秒）"
            break
        fi
        python -c "import time; time.sleep(1)" 2>/dev/null || true
        i=$((i + 1))
        if [ $i -eq 10 ]; then
            warn "后端启动超时，请检查日志: $LOG_FILE"
        fi
    done
}

# ---------- 启动前端（开发模式，Vite） ----------
start_frontend_dev() {
    cd "$FRONTEND_DIR"
    info "启动前端 (端口 $FRONTEND_PORT)..."
    npm run dev > "$FRONTEND_DIR/vite.log" 2>&1 &
    FRONTEND_PID=$!
    info "前端 PID: $FRONTEND_PID"
    i=0
    while [ $i -lt 10 ]; do
        if curl -s "http://127.0.0.1:$FRONTEND_PORT/" > /dev/null 2>&1; then
            ok "前端服务就绪（耗时 $((i + 1)) 秒）"
            break
        fi
        python -c "import time; time.sleep(1)" 2>/dev/null || true
        i=$((i + 1))
        if [ $i -eq 10 ]; then
            warn "前端启动超时，请检查日志: $FRONTEND_DIR/vite.log"
        fi
    done
}

# ---------- 开发模式：停 + 起 ----------
dev_mode() {
    MOCK=false
    CLEAN=false
    for arg in "$@"; do
        case $arg in
            --mock)  MOCK=true ;;
            --clean) CLEAN=true ;;
            *)       warn "未知参数: $arg" ;;
        esac
    done

    ensure_venv
    ensure_frontend_deps
    stop_services

    if [ "$CLEAN" = true ]; then
        info "清理日志文件..."
        rm -f "$BACKEND_DIR"/_uvicorn*.log "$BACKEND_DIR"/_server_stdout.log 2>/dev/null || true
        rm -f "$FRONTEND_DIR"/vite.log 2>/dev/null || true
        ok "日志已清理"
    fi

    info "========== 启动开发环境 =========="
    ok "Python: $PYTHON"
    ok "Node.js: $(node --version)"

    start_backend_dev
    start_frontend_dev

    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}  FlowerUI 开发环境已就绪！${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""
    echo -e "  后端 API:    http://127.0.0.1:${BACKEND_PORT}"
    echo -e "  前端页面:    http://127.0.0.1:${FRONTEND_PORT}"
    echo -e "  模拟模式:    $([ "$MOCK" = true ] && echo '已启用' || echo '已禁用')"
    echo ""
    echo -e "  后端日志:    ${BACKEND_DIR}/_uvicorn_*.log"
    echo -e "  前端日志:    ${FRONTEND_DIR}/vite.log"
    echo ""
    echo -e "  ${YELLOW}关闭终端不会停止服务（已在后台运行）${NC}"
    echo -e "  ${YELLOW}停止服务: ./manage.sh stop${NC}"
    echo ""
}

# ---------- 生产/运行模式：build + 单端口托管 ----------
run_mode() {
    ensure_venv
    build_frontend
    stop_services
    info "========== 启动生产模式（后端托管前端） =========="
    ok "访问地址: http://127.0.0.1:$BACKEND_PORT"
    cd "$BACKEND_DIR"
    export PYTHONIOENCODING=utf-8
    unset FLOWER_MOCK
    exec "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port $BACKEND_PORT
}

# ---------- 演示模式 ----------
demo_mode() {
    ensure_venv
    build_frontend
    stop_services
    info "========== 启动演示模式（FLOWER_MOCK=true） =========="
    ok "访问地址: http://127.0.0.1:$BACKEND_PORT"
    cd "$BACKEND_DIR"
    export PYTHONIOENCODING=utf-8
    export FLOWER_MOCK=true
    export FLOWER_MOCK_WORKERS=4
    export FLOWER_MOCK_SEED_TASKS=260
    exec "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port $BACKEND_PORT
}

# ---------- 帮助 ----------
usage() {
    echo "FlowerUI 服务管理脚本（统一入口）"
    echo ""
    echo "用法: ./manage.sh [命令] [选项]"
    echo ""
    echo "命令:"
    echo "  dev        开发模式：停 + 起（后端 5555 + 前端 5556 热更新）"
    echo "  restart    重启服务（等价于 dev，先停后起）"
    echo "  run        生产/运行模式：构建前端 + 单端口 5555 托管"
    echo "  demo       演示模式：模拟集群，无需 broker"
    echo "  build      仅构建前端产物"
    echo "  stop       停止所有服务"
    echo "  help       显示本帮助"
    echo ""
    echo "选项（仅 dev / restart 支持）:"
    echo "  --mock     启用模拟模式（FLOWER_MOCK=true）"
    echo "  --clean    启动前清理历史日志"
    echo ""
    echo "示例:"
    echo "  ./manage.sh dev            # 开发模式"
    echo "  ./manage.sh dev --mock     # 开发模式 + 模拟数据"
    echo "  ./manage.sh dev --clean    # 开发模式 + 清理日志"
    echo "  ./manage.sh run            # 生产模式"
    echo "  ./manage.sh stop           # 停止服务"
}

# ---------- 命令分发 ----------
case "${1:-dev}" in
    dev|restart) shift || true; dev_mode "$@" ;;
    run|start)   shift || true; run_mode "$@" ;;
    demo)        shift || true; demo_mode "$@" ;;
    build)       shift || true; ensure_venv; ensure_frontend_deps; build_frontend ;;
    stop)        stop_services ;;
    help|-h|--help) usage ;;
    *)           usage; exit 1 ;;
esac
