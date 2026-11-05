#!/bin/bash
# =============================================================================
# FlowerUI 前端服务管理脚本（前端专属，自根 manage.sh 拆分）
# -----------------------------------------------------------------------------
# 只管理前端（端口 5556 的 Vite 开发服务器 + 构建并同步到后端静态目录）。
# 后端逻辑见 ../backend/manage.sh；根目录 manage.sh 统一编排两者。
#
# 与根 manage.sh 的区别：
#   - 停止时只杀前端（按 Vite 命令行特征 + 端口 5556 精确定位），不会误伤
#     后端 uvicorn 或 celery worker
#   - 不含后端启动 / Python 依赖逻辑；构建产物会同步到 backend/flowerui/static
#
# 用法（Git Bash）:
#   ./manage.sh dev             # 开发模式：停 + 起（Vite 热更新，端口 5556）
#   ./manage.sh build           # 构建前端产物并同步到 backend/flowerui/static
#   ./manage.sh stop            # 仅停止前端
#   ./manage.sh status          # 查看前端运行状态
#   ./manage.sh clean           # 清理 frontend/logs 下历史日志
#   ./manage.sh help            # 显示帮助
#
# 端口约定：前端开发页面 5556（与 frontend/vite.config.js 保持一致）。
#
# 构建同步约定（2026-11 起）：
#   - dist/ 全量替换到 backend/flowerui/static（后端单端口托管）。后端新增的
#     配置项（如 result_backend）只在前端重建后才会出现在配置页里。
#   - 主题遵循「目录即真理」：backend/flowerui/themes 是运行时唯一真理源
#     （界面上传的新主题直接落这里，扫描 *.css 即注册）。仓库根 themes/
#     只是内置主题素材，build 默认**只补齐目标中缺失的文件，不覆盖、
#     不删除**，以免把用户上传/修改/删除的主题重置掉。
#     需要强制用仓库版本覆盖时：FLOWER_SYNC_THEMES=overwrite ./manage.sh build
# =============================================================================

set -e

# ---------- 关键：禁用 MSYS 路径转换 ----------
# Git Bash 默认会把 taskkill 的 /F 改写为 F:/，导致 taskkill 全部失败
# （表现为"无效的参数/选项 - 'F:/'"）。此处全局禁用，保证 /F /T /PID
# 等参数原样传给 Windows 程序。
export MSYS_NO_PATHCONV=1

# ---------- 路径配置 ----------
FRONTEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$FRONTEND_DIR/.."
BACKEND_DIR="$ROOT/backend"
FRONTEND_PORT=5556
LOGS_DIR="$FRONTEND_DIR/logs"     # 前端日志与 PID：frontend/logs/

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

# ---------- 路径转换（Git Bash 风格 -> Windows 风格，供 PowerShell 使用） ----------
winpath() {
    echo "$1" | sed -e 's|^/\([a-zA-Z]\)/|\1:/|' -e 's|/|\\|g'
}

# ---------- 依赖检查 ----------
ensure_node() {
    if ! command -v node &>/dev/null; then
        error "未找到 Node.js，请先安装"
        exit 1
    fi
}

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

# ---------- 停止前端（精确定位，不误杀后端 / worker） ----------
stop_frontend() {
    info "========== 停止前端服务（端口 $FRONTEND_PORT） =========="

    local has_listener=false
    if command -v netstat &>/dev/null; then
        if netstat -ano 2>/dev/null | awk -v p=":$FRONTEND_PORT" \
            '$4=="LISTENING" && $2 ~ (p "$") {found=1} END{exit !found}'; then
            has_listener=true
        fi
    fi

    if command -v taskkill &>/dev/null; then
        # ---------- Windows ----------
        # 1) PID 文件（本脚本启动时写入；记录 Windows PID 以便 taskkill /T 连树杀）
        local pidfile="$LOGS_DIR/_vite.pid"
        if [ -f "$pidfile" ]; then
            local pid
            pid=$(cat "$pidfile" 2>/dev/null || true)
            if [ -n "$pid" ]; then
                info "停止前端进程树 (PID=$pid)..."
                taskkill /F /T /PID "$pid" >/dev/null 2>&1 || true
            fi
            rm -f "$pidfile"
        fi
        # 2) 兜底：按端口提取监听 PID（PID 文件丢失 / 非本脚本启动时）
        if [ "$has_listener" = true ]; then
            for pid in $(netstat -ano 2>/dev/null | awk -v p=":$FRONTEND_PORT" '$4=="LISTENING" && $2 ~ (p "$") {print $NF}' | grep -E '^[0-9]+$'); do
                info "停止端口 $FRONTEND_PORT 上的进程 (PID=$pid)..."
                taskkill /F /T /PID "$pid" >/dev/null 2>&1 || true
            done
        fi
    elif command -v pkill &>/dev/null; then
        # ---------- Linux / macOS ----------
        pkill -f "vite" 2>/dev/null || true
        if command -v lsof &>/dev/null; then
            for pid in $(lsof -ti tcp:"$FRONTEND_PORT" 2>/dev/null || true); do
                kill -9 "$pid" 2>/dev/null || true
            done
        fi
    fi

    # 等待进程退出，避免紧接着启动时端口仍被占用
    sleep 1
    if [ "$has_listener" = false ]; then
        ok "前端未在运行"
    else
        ok "前端已停止"
    fi
}

# ---------- 状态查询 ----------
status_frontend() {
    if command -v netstat &>/dev/null; then
        if netstat -ano 2>/dev/null | awk -v p=":$FRONTEND_PORT" \
            '$4=="LISTENING" && $2 ~ (p "$") {found=1} END{exit !found}'; then
            ok "前端正在运行: http://127.0.0.1:$FRONTEND_PORT"
            return 0
        fi
    fi
    warn "前端未运行"
    return 1
}

# ---------- 同步主题（目录即真理，默认只补齐不覆盖） ----------
# backend/flowerui/themes 是运行时真理源：界面上传的 CSS 直接落在这里，
# theme_manager 扫描 *.css 即注册主题。因此不能像 dist 那样全量替换，
# 否则用户上传的主题会被删掉、改过的内置主题会被还原。
#   FLOWER_SYNC_THEMES=fill      默认，只补齐缺失文件
#   FLOWER_SYNC_THEMES=skip      完全不动主题目录
#   FLOWER_SYNC_THEMES=overwrite 用仓库版本覆盖同名文件（显式要求时才用）
sync_themes() {
    local src="$ROOT/themes"
    local dest="$BACKEND_DIR/flowerui/themes"
    local mode="${FLOWER_SYNC_THEMES:-fill}"
    if [ "$mode" = "skip" ]; then
        info "主题同步已跳过（FLOWER_SYNC_THEMES=skip）"
        return
    fi
    if [ ! -d "$src" ]; then
        warn "未找到内置主题目录 $src，跳过主题同步"
        return
    fi
    mkdir -p "$dest"
    local added=0 kept=0
    local f name
    for f in "$src"/*.css; do
        [ -e "$f" ] || continue
        name="$(basename "$f")"
        if [ -e "$dest/$name" ] && [ "$mode" != "overwrite" ]; then
            kept=$((kept + 1))
            continue
        fi
        if cp "$f" "$dest/$name"; then
            added=$((added + 1))
        else
            warn "主题复制失败: $name"
        fi
    done
    info "主题同步: 新增/更新 $added 个，保留 $kept 个（mode=$mode，目录=$dest）"
    if [ "$mode" = "overwrite" ]; then
        warn "overwrite 模式会覆盖同名主题；用户上传的非同名主题仍会保留"
    fi
    return 0
}

# ---------- 同步静态资产到后端 ----------
# 后端默认托管路径为 backend/flowerui/static（见 flowerui/main.py FRONTEND_DIST），
# 主题目录为 backend/flowerui/themes（见 theme_manager.THEMES_DIR）。
# 构建后同步一份到后端，保证后端单端口部署（根 manage.sh run）时服务最新产物。
sync_backend_assets() {
    if [ ! -d "$BACKEND_DIR/flowerui" ]; then
        warn "未找到后端目录 $BACKEND_DIR，跳过静态资产同步"
        return
    fi
    if [ ! -d "$FRONTEND_DIR/dist" ]; then
        warn "未找到构建产物 $FRONTEND_DIR/dist，跳过同步"
        return
    fi
    info "同步前端产物到 backend/flowerui/static（全量替换）..."
    rm -rf "$BACKEND_DIR/flowerui/static"
    mkdir -p "$BACKEND_DIR/flowerui/static"
    cp -r "$FRONTEND_DIR/dist/." "$BACKEND_DIR/flowerui/static/"
    sync_themes
    ok "已同步: backend/flowerui/static（全量） + backend/flowerui/themes（只补齐）"
}

# ---------- 构建前端 ----------
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
    sync_backend_assets
}

# ---------- 启动前端（开发模式，Vite） ----------
start_frontend_dev() {
    cd "$FRONTEND_DIR"
    info "启动前端 (端口 $FRONTEND_PORT)..."
    mkdir -p "$LOGS_DIR"
    npm run dev > "$LOGS_DIR/vite.log" 2>&1 &
    FRONTEND_PID=$!
    disown "$FRONTEND_PID" 2>/dev/null || true
    # 记录 Windows PID：MSYS 的 $! 与 Windows PID 不同，taskkill 需要 Windows PID
    WIN_PID=$(cat "/proc/$FRONTEND_PID/winpid" 2>/dev/null || echo "$FRONTEND_PID")
    echo "$WIN_PID" > "$LOGS_DIR/_vite.pid"
    info "前端 PID: $FRONTEND_PID (Windows PID: $WIN_PID)"
    i=0
    while [ $i -lt 30 ]; do
        if curl -s --noproxy "*" "http://127.0.0.1:$FRONTEND_PORT/" > /dev/null 2>&1; then
            ok "前端服务就绪（耗时 $((i + 1)) 秒）"
            break
        fi
        sleep 1
        i=$((i + 1))
        if [ $i -eq 30 ]; then
            warn "前端启动超时，请检查日志: $LOGS_DIR/vite.log"
        fi
    done
}

# ---------- 开发模式：停 + 起 ----------
dev_mode() {
    ensure_node
    stop_frontend
    ensure_frontend_deps
    info "========== 启动前端（开发模式） =========="
    ok "Node.js: $(node --version)"
    start_frontend_dev

    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}  FlowerUI 前端已就绪！${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""
    echo -e "  前端页面:    http://127.0.0.1:${FRONTEND_PORT}"
    echo -e "  前端日志:    ${LOGS_DIR}/vite.log"
    echo ""
    echo -e "  ${YELLOW}关闭终端不会停止服务（已在后台运行）${NC}"
    echo -e "  ${YELLOW}停止服务: ./manage.sh stop${NC}"
    echo ""
}

# ---------- 清理历史日志（frontend/logs/ 下 *.log） ----------
clean_logs() {
    info "========== 清理历史日志 =========="
    mkdir -p "$LOGS_DIR"
    rm -f "$LOGS_DIR"/*.log 2>/dev/null || true
    # 兼容旧路径残留
    rm -f "$FRONTEND_DIR"/_vite.pid "$FRONTEND_DIR"/vite.log 2>/dev/null || true
    ok "历史日志已清理"
}

# ---------- 帮助 ----------
usage() {
    echo "FlowerUI 前端服务管理脚本（自根 manage.sh 拆分，仅管理前端）"
    echo ""
    echo "用法: ./manage.sh [命令]"
    echo ""
    echo "命令:"
    echo "  dev        开发模式：停 + 起（Vite 热更新，端口 5556）"
    echo "  build      构建前端产物并同步到后端（dist → backend/flowerui/static）"
    echo "  stop       停止前端（精确定位，不误杀后端 / worker）"
    echo "  status     查看前端运行状态"
    echo "  clean      清理 frontend/logs/ 下历史日志"
    echo "  help       显示本帮助"
    echo ""
    echo "构建同步:"
    echo "  backend/flowerui/static      全量替换为 dist/（后端单端口托管）"
    echo "  backend/flowerui/themes      默认只补齐缺失的内置主题，不覆盖、不删除；"
    echo "                          界面上传的主题落在那里，属运行时真理源"
    echo "  后端新增配置项（如 result_backend）需在前端重建后才会出现在配置页"
    echo ""
    echo "环境变量:"
    echo "  FLOWER_SYNC_THEMES=fill|skip|overwrite   主题同步策略（默认 fill）"
    echo ""
    echo "示例:"
    echo "  ./manage.sh dev                                  # 开发模式"
    echo "  ./manage.sh build                                # 构建并同步到后端"
    echo "  FLOWER_SYNC_THEMES=overwrite ./manage.sh build  # 用仓库主题覆盖同名文件"
    echo "  ./manage.sh stop                                 # 停止前端"
}

# ---------- 命令分发 ----------
case "${1:-dev}" in
    dev|restart) shift || true; dev_mode "$@" ;;
    build)       build_frontend ;;   # build_frontend 内部已做 ensure_node / ensure_frontend_deps
    stop)        stop_frontend ;;
    status)      status_frontend ;;
    clean)       clean_logs ;;
    help|-h|--help) usage ;;
    *)           usage; exit 1 ;;
esac
