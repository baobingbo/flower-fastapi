#!/usr/bin/env bash
# 启动真实 Celery worker，消费 examples/tasks.py 定义的任务。
# 与 docker-compose.yml 中注释掉的示例 worker 等价（本地非容器版）。
#
#   ./start_worker.sh        # 前台运行（Ctrl+C 停止）
#   ./start_worker.sh -d     # 后台运行（daemon，写 worker.pid）
#
# 环境变量（可选）：
#   FLOWER_BROKER_URL       默认 redis://127.0.0.1:6379/0
#   FLOWER_RESULT_BACKEND   默认 redis://127.0.0.1:6379/1
#   WORKER_POOL             默认 threads（Windows 推荐）
#   WORKER_CONCURRENCY      默认 4
#
# 关于池类型（Windows 上尤其重要）：
#   prefork  默认值，但 Windows 无 fork，子进程会僵死 —— 不要用。
#   solo     单线程，能跑任务，但执行期间无法响应 inspect / 远程控制命令，
#            表现为 FlowerUI 上「已注册任务」为空、pool/consumer 操作超时。
#   threads  任务跑在工作线程，主线程仍能及时回复控制命令 —— Windows 首选。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLES="$ROOT/examples"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"; [ -x "$PY" ] || PY="$VENV/Scripts/python.exe"

export FLOWER_BROKER_URL="${FLOWER_BROKER_URL:-redis://127.0.0.1:6379/0}"
export FLOWER_RESULT_BACKEND="${FLOWER_RESULT_BACKEND:-redis://127.0.0.1:6379/1}"
POOL="${WORKER_POOL:-threads}"
CONCURRENCY="${WORKER_CONCURRENCY:-4}"

cd "$EXAMPLES"
if [ "${1:-}" = "-d" ]; then
  echo ">> 后台启动 worker（pool=$POOL, 并发=$CONCURRENCY，日志 worker.log）"
  exec "$PY" -m celery -A tasks worker -E -l info \
    -Q celery,emails,reports --pool="$POOL" -c "$CONCURRENCY" \
    --hostname worker1@flowerui \
    --logfile "$EXAMPLES/worker.log" --pidfile "$EXAMPLES/worker.pid" \
    --detach
else
  echo ">> 前台启动 worker（pool=$POOL, 并发=$CONCURRENCY）"
  exec "$PY" -m celery -A tasks worker -E -l info \
    -Q celery,emails,reports --pool="$POOL" -c "$CONCURRENCY" \
    --hostname worker1@flowerui
fi
