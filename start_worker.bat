@echo off
REM 启动真实 Celery worker（消费 examples\tasks.py 定义的任务）。
REM 与 docker-compose.yml 中注释掉的示例 worker 等价（本地非容器版）。
REM
REM   用法: start_worker.bat
REM   建议先启动 FlowerUI(真实模式)，再运行本脚本，最后运行 seed_tasks.py
REM
REM 环境变量（可选）：
REM   FLOWER_BROKER_URL      默认 redis://127.0.0.1:6379/0
REM   FLOWER_RESULT_BACKEND  默认 redis://127.0.0.1:6379/1
REM   WORKER_POOL            默认 threads（Windows 推荐）
REM   WORKER_CONCURRENCY     默认 4
REM
REM 关于池类型（Windows 上尤其重要）：
REM   prefork  Celery 默认值，但 Windows 无 fork，子进程会僵死 —— 不要用。
REM   solo     单线程，能跑任务，但执行期间无法响应 inspect / 远程控制命令，
REM            表现为 FlowerUI 上"已注册任务"为空、pool/consumer 操作超时。
REM   threads  任务跑在工作线程，主线程仍能及时回复控制命令 —— Windows 首选。

setlocal
set SCRIPT_DIR=%~dp0
set ROOT=%SCRIPT_DIR:~0,-1%
set VENV=%ROOT%\.venv
set PY=%VENV%\Scripts\python.exe

if "%FLOWER_BROKER_URL%"=="" set FLOWER_BROKER_URL=redis://127.0.0.1:6379/0
if "%FLOWER_RESULT_BACKEND%"=="" set FLOWER_RESULT_BACKEND=redis://127.0.0.1:6379/1
if "%WORKER_POOL%"=="" set WORKER_POOL=threads
if "%WORKER_CONCURRENCY%"=="" set WORKER_CONCURRENCY=4

if not exist "%PY%" (
  echo [start_worker] 未找到虚拟环境 %PY%
  echo [start_worker] 请先在项目根目录执行: python -m venv .venv ^&^& .venv\Scripts\pip install -r backend\requirements.txt
  exit /b 1
)

REM tasks.py 位于 examples 下，必须切到该目录 -A tasks 才能导入
cd /d "%ROOT%\examples"
echo [start_worker] 启动 worker: pool=%WORKER_POOL% 并发=%WORKER_CONCURRENCY% broker=%FLOWER_BROKER_URL%
"%PY%" -m celery -A tasks worker -E -l info -Q celery,emails,reports --pool=%WORKER_POOL% -c %WORKER_CONCURRENCY% --hostname worker1@flowerui
endlocal
