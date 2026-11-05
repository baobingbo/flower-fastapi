# FlowerUI Worker 启动说明

> 回答核心问题：**`start_worker.sh` 启动的 worker 不是由后端 `celery_app` 创建的。**
> 它是一个**独立操作系统进程**，加载的是 `examples/tasks.py` 里**另建的** Celery app（名为 `flowerui_demo`）。
> 之所以 FlowerUI 能监控到它，是因为两个 app 通过环境变量 `FLOWER_BROKER_URL` 连到了**同一个 Redis broker**。
> worker 由谁启动、代码放哪里，对 FlowerUI 都无关紧要——只要它连同一个 broker 并用 `-E` 打开了事件上报。

## 1. Worker 启动链路（文本图）

```
start_worker.sh
  │  export FLOWER_BROKER_URL=redis://127.0.0.1:6379/0   (start_worker.sh:27)
  │  export FLOWER_RESULT_BACKEND=redis://127.0.0.1:6379/1 (start_worker.sh:28)
  │  cd examples/                                          (start_worker.sh:32)
  │
  └── exec python -m celery -A tasks worker -E -l info
        -Q celery,emails,reports --pool=threads -c 4
        --hostname worker1@flowerui                        (start_worker.sh:42-44)
        │
        │  -A tasks → 导入当前目录 examples/tasks.py
        ▼
  examples/tasks.py
        app = Celery("flowerui_demo", broker=BROKER, backend=BACKEND)   (tasks.py:56)
        BROKER = FLOWER_BROKER_URL 或 CELERY_BROKER_URL 或默认 redis://127.0.0.1:6379/0 (tasks.py:45-49)
        注册 6 个业务任务 (tasks.py:69-112):
          tasks.send_email      → emails  队列 (tasks.py:62-65, 69)
          tasks.resize_image    → reports 队列 (tasks.py:62-65, 76)
          tasks.custom_job / tasks.flaky / tasks.long_task / tasks.retry_demo
        │
        │  连 broker redis://127.0.0.1:6379/0，消费 3 个队列，
        │  -E 开启事件上报（worker-online / task-* / heartbeat …）
        ▼
  ┌─────────────────────── Redis 127.0.0.1:6379（共享 broker）───────────────────────┐
  │  队列: celery, emails, reports, celeryev (事件流), 各 worker 的 control 队列       │
  └──────────────┬───────────────────────────────────────────────────┬──────────────┘
                 │ 发布事件流 / 响应 control 命令                       │ 投递任务 (send_task)
                 ▼                                                   │
  FlowerUI 后端进程 (uvicorn app.main)                                 │
    backend/app/core/celery_app.py:56  get_celery_app()               │
      capp = celery.Celery(broker=settings.broker_url)  ← FLOWER_BROKER_URL, 同名同默认
      （无业务任务；仅用作 事件消费者 + inspector + 控制/投递客户端）
      │
      ├─ services/events.py:103-116   EventReceiver 消费事件流 → state.py:48-60 处理 worker-online/offline
      ├─ services/events.py:90-95     每 5s control.enable_events() 让迟到的 worker 也发事件
      ├─ services/inspector.py:51-63  capp.control.inspect(...) 走 broker control 队列
      │                               (stats/registered/active/reserved/active_queues/…)
      └─ services/manager.py:616-634  下发任务：本地无注册 → capp.send_task(taskname) ──► 投递回 broker
```

## 2. 后端与 worker 的 broker 关系

两边**读同一个环境变量 `FLOWER_BROKER_URL`，默认值也相同**，因此默认就是同一个 Redis：

| 侧 | 代码位置 | broker 取值 |
|---|---|---|
| 后端 | `backend/app/core/config.py:20`（`env_prefix="FLOWER_"`）+ `config.py:38` | `FLOWER_BROKER_URL`，默认 `redis://127.0.0.1:6379/0` |
| 后端 app 构造 | `backend/app/core/celery_app.py:56` | `celery.Celery(broker=settings.broker_url)` |
| worker | `examples/tasks.py:45-49` | `FLOWER_BROKER_URL` 或 `CELERY_BROKER_URL`，默认 `redis://127.0.0.1:6379/0` |
| worker app 构造 | `examples/tasks.py:56` | `Celery("flowerui_demo", broker=BROKER, backend=BACKEND)` |

venv 实测（`.venv/Scripts/python.exe`）：

```
== 后端 get_celery_app() ==           == examples/tasks.py app ==
main:  None（无名 app）                 main:  flowerui_demo
broker_url:  redis://127.0.0.1:6379/0  broker_url:  redis://127.0.0.1:6379/0
result_backend: None                  result_backend:  redis://127.0.0.1:6379/1
业务任务:  []                         业务任务:  tasks.custom_job / tasks.flaky /
                                      tasks.long_task / tasks.resize_image /
                                      tasks.retry_demo / tasks.send_email
```

**结论：不是同一个 Celery app 对象（名字不同、任务注册表不同），但 broker 指向同一个 Redis，共享队列/事件流/control 通道。**

## 3. FlowerUI 如何"发现" worker

两条通道，都不关心 worker 是谁启动的（`backend/app/services/`）：

1. **事件流**（`events.py`）：`Events` 线程用 `EventReceiver(conn, handlers={"*": on_event})`（`events.py:108-116`）消费 broker 上的 **celeryev** 事件流；`state.py:48-60` 处理 `worker-online` / `worker-heartbeat` / `worker-offline`，worker 即出现在 UI。另外 `events.py:90-95` 每 5 秒 `control.enable_events()` 一次，保证 FlowerUI 启动后才上线的 worker 也会开事件。
2. **celery inspect**（`inspector.py`）：`Inspector` 对 8 个方法（`stats / registered / active / reserved / scheduled / revoked / active_queues / conf`，`inspector.py:15-24`）通过 `capp.control.inspect(...)`（`inspector.py:53`）向 worker 的 **control 队列** 发命令并收集回复；"已注册任务"列表即来自 worker 侧 `registered` 响应（`manager.py:149-167`）。

> 因此 worker 进程由 `start_worker.sh`、bat、docker 或手工 `celery` 命令创建，**只要连了同一个 broker 且开了事件（`-E` 或后端周期 enable_events），FlowerUI 就能看到它**。

## 4. 为什么在项目中"找不到" worker

- worker 是**独立进程**：`start_worker.sh:35/42` 用 `exec python -m celery -A tasks worker ...` 启动，与后端 uvicorn 进程无关。它不在后端进程内，所以翻 `backend/` 自然找不到。
- worker 的"代码"（任务定义）在 **`examples/tasks.py`**，不在 `backend/` 下；`-A tasks` 只是相对 `examples/` 目录导入该模块（`start_worker.sh:32-42`）。
- **后端进程本身不启动、不内嵌任何 worker**：`backend/app/main.py:63-77` 的 lifespan 只调用 `runtime_config.load()`、`theme_manager.start_watcher()`、`manager.startup()`；`manager.startup()`（`manager.py:51-92`）只做 broker 探测、事件采集、inspect 循环。全仓库 `backend/app` 下没有任何 worker 启动/内嵌逻辑。

## 5. `start_worker.bat` 与 `docker-compose.yml` 的等价性

| 项 | start_worker.sh | start_worker.bat | docker-compose worker（注释段） |
|---|---|---|---|
| app 模块 | `-A tasks`（examples/，sh:32,42） | `-A tasks`（bat:38-40） | `-A tasks`（compose:63-68） |
| 事件 | `-E` | `-E` | `-E` |
| 队列 | `celery,emails,reports`（sh:36/43） | 同 | 同（compose:69） |
| pool / 并发 | threads / 4（sh:29-30） | threads / 4（bat:28-29） | threads / 4（compose:69） |
| hostname | `worker1@flowerui`（sh:37/44） | 同 | 同（compose:70） |
| broker | `FLOWER_BROKER_URL` 默认 `redis://127.0.0.1:6379/0`（sh:27） | 同（bat:26） | `CELERY_BROKER_URL: redis://redis:6379/0`（compose:72）——compose 网络内的同一个 redis 容器 |

**等价**：同一 app 模块、同一任务集、同一队列/池配置；只有 broker 的主机名不同（本机 `127.0.0.1` vs compose 服务名 `redis`），逻辑上指向同一个 Redis。注意 compose 示例 worker 用的是 `CELERY_BROKER_URL`（tasks.py 的第二优先级，`tasks.py:47`），效果相同。

## 6. 两个 app 的配置差异表

| 配置 | 后端 `get_celery_app()` | worker `examples/tasks.py` | 影响 |
|---|---|---|---|
| app name | 未指定（`main=None`） | `flowerui_demo`（tasks.py:56） | 仅影响标识/日志命名；**不影响** broker 共享与任务投递（任务按 任务名+队列 路由） |
| broker | `FLOWER_BROKER_URL`，默认 `redis://127.0.0.1:6379/0`（config.py:38） | `FLOWER_BROKER_URL`/`CELERY_BROKER_URL`，同默认（tasks.py:45-49） | **相同 → 共享 broker，这是 FlowerUI 能监控 worker 的根本原因** |
| result backend | 默认 `None`（config.py:39） | `redis://127.0.0.1:6379/1`（tasks.py:50-54） | 后端不取任务结果详情；worker 结果存 redis db1，FlowerUI 从事件流看状态 |
| 任务注册 | 无业务任务（`celery_app.py:62` 的 `import_default_modules` 找不到任何模块） | 6 个业务任务（tasks.py:69-112） | UI 的"已注册任务"来自 worker 侧 inspect `registered`（manager.py:153-161） |
| task_routes | 空（可用 `FLOWER_TASK_ROUTES` JSON 注入，config.py:48-54） | `send_email→emails`、`resize_image→reports`（tasks.py:62-65） | 路由发生在**投递端**：FlowerUI 下发未指定队列时按后端路由（默认 `celery` 队列）；worker 消费 3 个队列所以仍能执行，只是队列归属与 worker 侧路由不一致 |

## 7. 如果希望 worker 使用后端的 app（统一任务注册）

背景：FlowerUI 下发任务时，后端本地 app 没有业务任务，`manager.py:616-630` 会走 `capp.send_task(taskname)` 按名投递，且任务名只要在 worker 的 `registered` 列表里即可（所以**现状已能下发并执行**）。但队列路由用的是**后端**的 `task_routes`（默认空），与 worker 侧不一致。若想让两者完全统一：

**方案 A（推荐，最小改动）：让 worker 直接复用后端的 app 工厂**

把 `examples/tasks.py` 顶部的 app 创建改为使用后端工厂（worker 进程以 `backend/` 为 `sys.path` 入口即可导入）：

```python
# examples/tasks.py（示意）
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
from app.core.celery_app import get_celery_app
app = get_celery_app()          # 与后端同一个配置来源（FLOWER_BROKER_URL / FLOWER_RESULT_BACKEND）
app.conf.update(task_routes={...})  # 把队列路由放到这里；后端可用 FLOWER_TASK_ROUTES 注入同名映射
```

这样两边 app name、broker、路由都来自 `backend/app/core/config.py` 单一来源。启动命令需相应改为
`cd backend && python -m celery -A "app.core.celery_app:get_celery_app" worker -E ...`（Celery CLI 支持 `模块:可调用` 语法），或保留 `examples/tasks.py` 作为 `celery -A tasks` 的入口、其中 import 后端工厂。

**方案 B（不动 worker）：在后端补齐路由**

给 FlowerUI 后端设置环境变量：

```
FLOWER_TASK_ROUTES={"tasks.send_email":"emails","tasks.resize_image":"reports"}
```

（config.py:48-54 支持 JSON 注入），使后端下发时的队列路由与 worker 侧一致；任务注册仍由 worker 侧 inspect 提供，无需改代码。

**方案 C：把业务任务搬进 backend/**

将 `examples/tasks.py` 的任务定义移入 `backend/app/tasks/` 并在后端 app 中注册（`get_celery_app()` 里 import 该模块）。此后 `celery -A "app.core.celery_app:get_celery_app" worker` 启动的 worker 与后端共享同一 app 对象、同一任务注册表；UI 下发走 `task.apply_async` 本地注册分支（manager.py:617-621）。代价是 worker 依赖后端包结构。

> 提醒：**app name 不同并不会导致监控/投递失败**。任务路由依据是「任务名 + 队列」，app name 只是标识。真正要保证的只有：broker 相同（`FLOWER_BROKER_URL`）、worker 开事件（`-E` 或后端周期 `enable_events`）、pool 不是 solo（否则 inspect 超时，见 start_worker.sh:16-18）。
