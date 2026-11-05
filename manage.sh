#!/bin/bash
# =============================================================================
# FlowerUI 统一入口管理脚本（编排层，仅调度子脚本）
# -----------------------------------------------------------------------------
# 本脚本只做「编排」，不做具体启停逻辑。后端逻辑在 backend/manage.sh，
# 前端逻辑在 frontend/manage.sh。此处按命令把工作分派给对应子脚本，避免
# 逻辑分散在多处、难以维护。
#
# 用法:
#   ./manage.sh dev            # 开发模式：后端(5555) + 前端(5556) 热更新
#   ./manage.sh dev --mock     # 开发模式 + 模拟数据（FLOWER_MOCK=true，转发给后端）
#   ./manage.sh dev --clean    # 开发模式 + 启动前清理历史日志（转发给后端）
#   ./manage.sh dev --reload   # 开发模式 + uvicorn 热更新（转发给后端）
#   ./manage.sh restart        # 重启（等价于 dev，先停后起）
#   ./manage.sh run            # 生产/运行模式：构建前端 + 后端单端口 5555 托管
#   ./manage.sh demo           # 演示模式：构建前端 + 模拟集群，无需 broker
#   ./manage.sh build          # 仅构建前端产物并同步到后端
#   ./manage.sh deps           # 后端依赖：uv sync（转发给后端，唯一入口）
#   ./manage.sh upgrade        # 后端依赖：uv sync --upgrade
#   ./manage.sh config         # 后端配置体检（TOML / 环境变量 / 生效值）
#   ./manage.sh status         # 查看前后端状态 + 后端环境摘要
#   ./manage.sh workers [N]    # 前台启动 celery worker（转发给后端）
#   ./manage.sh stop           # 停止后端与前端
#   ./manage.sh clean          # 清理 backend/logs、frontend/logs 下全部历史日志（前后端 + worker，保留 PID）
#   ./manage.sh pack <项目路径> [输出文件名]
#                             # 按指定项目下的 .gitignore 排除，打包成 .tar.gz
#   ./manage.sh help           # 显示帮助
#
# 端口约定：后端 API 5555；前端页面 5556（与各自子脚本保持一致）。
# 环境约定：后端依赖只走 backend/.venv + uv sync（Python 3.7.9）；
#           静态配置 backend/flowerui-settings.toml、运行时 backend/flowerui.runtime.toml。
# 注意：Windows 下请用 Git Bash 运行（如 bash manage.sh dev）。
# =============================================================================

set -e

# ---------- 关键：禁用 MSYS 路径转换 ----------
export MSYS_NO_PATHCONV=1

# ---------- 路径配置 ----------
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"

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

# ---------- 子脚本调度 ----------
call_backend() {
    if [ ! -x "$BACKEND_DIR/manage.sh" ] && [ ! -f "$BACKEND_DIR/manage.sh" ]; then
        error "未找到后端脚本: $BACKEND_DIR/manage.sh"
        return 1
    fi
    bash "$BACKEND_DIR/manage.sh" "$@"
}
call_frontend() {
    if [ ! -x "$FRONTEND_DIR/manage.sh" ] && [ ! -f "$FRONTEND_DIR/manage.sh" ]; then
        error "未找到前端脚本: $FRONTEND_DIR/manage.sh"
        return 1
    fi
    bash "$FRONTEND_DIR/manage.sh" "$@"
}

# ---------- 打包：按项目 .gitignore 排除 ----------
# 思路：
#   1. 解析项目路径为绝对路径；输出默认放在「项目父目录 / 项目名.tar.gz」，
#      确保压缩包不会落入被打包目录内（避免自包含）。
#   2. 排除列表优先用 git（git 会精确解析项目内的 .gitignore，含所有
#      通配符 / 注释 / 取反规则）：`git ls-files --ignored --exclude-standard
#      --others --directory` 列出「未跟踪且被忽略」的文件 / 目录，喂给
#      tar --exclude-from。
#   3. 若项目不在 git 仓库内、但自身有 .gitignore，则回退为 tar 直接读取
#      该 .gitignore（通配符可用，! 取反 / 注释可能不精确）。
#   4. 始终排除 .git 版本库目录。
pack_cmd() {
    local proj="${1:-}"
    local out="${2:-}"
    if [ -z "$proj" ]; then
        error "用法: ./manage.sh pack <项目路径> [输出文件名]"
        return 1
    fi
    local proj_abs
    proj_abs="$(cd "$proj" 2>/dev/null && pwd)" || { error "目录不存在: $proj"; return 1; }
    local base; base="$(basename "$proj_abs")"

    [ -z "$out" ] && out="$(dirname "$proj_abs")/$base.tar.gz"
    # 防止输出文件落在被打包目录内导致自包含：若输出位于项目子树内，移到项目父目录
    local out_abs out_dir out_name
    out_dir="$(cd "$(dirname "$out")" 2>/dev/null && pwd)"
    out_name="$(basename "$out")"
    out_abs="$out_dir/$out_name"
    case "$out_abs" in
        "$proj_abs"/*) out="$(dirname "$proj_abs")/$out_name" ;;
    esac
    mkdir -p "$(dirname "$out")"

    info "打包项目: $proj_abs"
    info "输出文件: $out"

    local excl; excl="$(mktemp)"
    # 始终排除版本库目录
    echo ".git" >> "$excl"

    # 注意：原生 git 不识别 MSYS 风格绝对路径（/d/projects/...），`git -C` 会报
    # "cannot change to"。因此先 cd 进项目目录（cd 是 shell 内建，能正确解析
    # /d/...），再在当前目录下执行 git，路径问题即消除。
    # 通过 git rev-parse --show-prefix 拿到「项目相对仓库根的路径」，作为 tar 的
    # 打包目标；打包仓库根本身时前缀为空，目标记为 `.`。
    local repo_root target
    repo_root="$( cd "$proj_abs" && git rev-parse --show-toplevel 2>/dev/null )" || repo_root=""
    if [ -n "$repo_root" ]; then
        target="$( cd "$proj_abs" && git rev-parse --show-prefix 2>/dev/null )"
        target="${target%/}"          # 去掉结尾斜杠
        [ -z "$target" ] && target="."
        info "依据 $proj_abs 下 .gitignore（经 git 解析）排除忽略文件..."
        # 注意：git ls-files --directory 输出的目录带结尾斜杠（如 frontend/node_modules/），
        # 而 tar --exclude-from 对「结尾斜杠的目录模式」匹配失效（实测含斜杠的条目不生效）。
        # 因此统一去掉结尾斜杠；tar 对「frontend/node_modules」这种无斜杠模式能正确排除整棵子树。
        ( cd "$repo_root" && git ls-files --ignored --exclude-standard --others --directory -z 2>/dev/null \
            | tr '\0' '\n' | sed 's#/$##' >> "$excl" )
        ( cd "$repo_root" && tar -czf "$out" --exclude-from="$excl" "$target" )
    elif [ -f "$proj_abs/.gitignore" ]; then
        warn "项目不在 git 仓库内，回退为直接读取 .gitignore（通配符可用，! 取反 / 注释可能不精确）"
        # 过滤掉注释 / 空行 / 取反行，并去掉目录结尾斜杠，提升 tar 兼容性
        ( cd "$proj_abs" && tar -czf "$out" --exclude-from=<(grep -vE '^#|^$|^!' "$proj_abs/.gitignore" | sed 's#/$##') . )
    else
        warn "未发现 .gitignore，打包全部内容（仅排除 .git）"
        ( cd "$proj_abs" && tar -czf "$out" . )
    fi
    rm -f "$excl"

    ok "打包完成: $out ($(du -h "$out" 2>/dev/null | cut -f1))"
}

# ---------- 帮助 ----------
usage() {
    echo "FlowerUI 统一入口（编排层：仅调度 backend / frontend 子脚本）"
    echo ""
    echo "用法: ./manage.sh [命令] [选项]"
    echo ""
    echo "服务命令:"
    echo "  dev        开发模式：后端(5555) + 前端(5556) 热更新"
    echo "  restart    重启服务（等价于 dev，先停后起）"
    echo "  run        生产/运行模式：构建前端 + 后端单端口 5555 托管"
    echo "  demo       演示模式：构建前端 + 模拟集群，无需 broker"
    echo "  build      仅构建前端产物并同步到 backend/flowerui/static"
    echo "  stop       停止后端与前端"
    echo "  clean      清理 backend/logs、frontend/logs 下全部历史日志（前后端 + worker，保留 PID）"
    echo "  status     查看前后端状态 + 后端环境/配置摘要"
    echo "  workers [N=4]          前台启动并监控 celery worker（转发 backend/manage.sh）"
    echo ""
    echo "后端依赖 / 配置（转发 backend/manage.sh，uv 为唯一入口）:"
    echo "  deps [uv sync 参数]     按 uv.lock 还原；如 deps --check / deps --upgrade"
    echo "  upgrade                 升级全部依赖到 py3.7 最新兼容版"
    echo "  config                  配置体检：TOML / FLOWER_* 环境变量 / 生效值"
    echo ""
    echo "工具命令:"
    echo "  pack <路径> [输出]   按指定项目下的 .gitignore 排除，打包成 .tar.gz"
    echo "                       （uv.lock / .python-version 未被忽略，会随包带上）"
    echo "  help       显示本帮助"
    echo ""
    echo "选项（仅 dev / restart 转发给后端）:"
    echo "  --mock     启用模拟模式（FLOWER_MOCK=true）"
    echo "  --clean    启动前清理历史日志"
    echo "  --reload   开启后端 uvicorn 热更新（默认关）"
    echo ""
    echo "示例:"
    echo "  ./manage.sh deps                 # 首次安装 / 重装后端依赖"
    echo "  ./manage.sh deps --check         # 依赖体检"
    echo "  ./manage.sh config               # 排查「界面改了 broker 没生效」"
    echo "  ./manage.sh dev                  # 开发模式"
    echo "  ./manage.sh dev --mock           # 开发模式 + 模拟数据"
    echo "  ./manage.sh run                  # 生产模式"
    echo "  ./manage.sh stop                 # 停止服务"
    echo "  ./manage.sh pack ./backend       # 打包 backend（排除 .venv 等）"
    echo "  ./manage.sh pack ./frontend out/frontend.tar.gz"
}

# ---------- 命令分发 ----------
case "${1:-dev}" in
    dev|restart)
        shift || true
        call_backend dev "$@"
        call_frontend dev
        ;;
    run|start)
        shift || true
        call_frontend build
        call_backend run
        ;;
    demo)
        shift || true
        call_frontend build
        call_backend demo
        ;;
    build)
        shift || true
        call_frontend build
        ;;
    stop)
        call_backend stop
        call_frontend stop
        ;;
    clean)
        call_backend clean
        call_frontend clean
        ;;
    status)
        # 子脚本在「未运行」时返回 1；此处只做展示，不应中断另一端查询
        call_backend status || true
        call_frontend status || true
        ;;
    workers)
        shift || true
        call_backend workers "$@"
        ;;
    deps|sync)
        shift || true
        call_backend deps "$@"
        ;;
    upgrade)
        shift || true
        call_backend upgrade "$@"
        ;;
    config)
        call_backend config
        ;;
    pack)
        shift || true
        pack_cmd "$@"
        ;;
    help|-h|--help) usage ;;
    *)           usage; exit 1 ;;
esac
