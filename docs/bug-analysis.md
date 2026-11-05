# FlowerUI 代码 Bug 审计报告

- 审计对象：`flowerui-fastapi`（FastAPI + Vue 3 + Element Plus 的 Celery 实时监控平台，Flower 2.0.1 前后端分离重构版）
- 审计范围：`backend/app/**`（core / services / api/routers / tests）、`frontend/src/**`、`Dockerfile`、`docker-compose.yml`、`manage.sh`、`restart.py` 等部署脚本
- 审计方式：逐文件通读 + 关键行为在真实 venv（Python 3.13.12 / celery 5.6.3 / redis 8.1.0 / fastapi 0.141.1）中写验证脚本实测
- 说明：每条 bug 均给出 file:line 级定位与触发条件；已用代码/运行证据排除的疑似问题见附录 B「已排查、未构成 bug 的项」

## 目录

- [统计汇总](#统计汇总)
- [P0 致命（1 个）](#p0-致命)
- [P1 严重（8 个）](#p1-严重)
- [P2 一般（18 个）](#p2-一般)
- [P3 轻微（21 个）](#p3-轻微)
- [附录 A：验证方法与证据](#附录-a验证方法与证据)
- [附录 B：已排查、未构成 bug 的项](#附录-b已排查未构成-bug-的项)

## 统计汇总

| 严重程度 | 数量 | 编号 |
|---|---|---|
| P0 致命 | 1 | P0-1 |
| P1 严重 | 8 | P1-1 … P1-8 |
| P2 一般 | 18 | P2-1 … P2-18 |
| P3 轻微 | 21 | P3-1 … P3-21 |
| **合计** | **48** | |

按主类别分布：安全 8、错误处理/状态码 7、资源泄漏 5、并发/异步 6、数据一致性 7、前后端契约 5、前端定时器/内存 4、部署/配置 8、信息泄露 4、其余为代码卫生/UX（部分条目跨类，按主类计）。

---

## P0 致命

### P0-1 Docker 部署下前端完全不可用

- **位置**：`Dockerfile:47` 与 `backend/app/main.py:37-42`
- **问题描述**：Dockerfile 把前端构建产物复制到容器内 `/app/static`：
  ```dockerfile
  COPY --from=frontend /build/dist ./static
  ```
  但 `main.py` 查找静态资源的路径是：
  ```python
  FRONTEND_DIST = Path(
      os.environ.get(
          "FLOWER_FRONTEND_DIST",
          Path(__file__).resolve().parents[2] / "frontend" / "dist",
      )
  )
  ```
  容器中 `main.py` 位于 `/app/app/main.py`，`parents[2]` 为 `/`，即查找 `/frontend/dist` —— 该路径在容器内不存在，且 Dockerfile 没有设置 `FLOWER_FRONTEND_DIST`。结果：静态文件不挂载、SPA 404 兜底（`main.py:114-123`）也找不到 `index.html`，所有页面路由都返回 JSON「前端未构建」。API 正常但 Web 界面完全不可用 —— 官方 Docker 部署路径下产品不可用。
- **触发条件**：`docker compose up --build`（或任何按 Dockerfile 构建的容器）后访问 `http://host:5555`。
- **修复方案**：
  ```dockerfile
  # 方案 A（推荐）：显式指定前端目录
  ENV FLOWER_FRONTEND_DIST=/app/static
  COPY --from=frontend /build/dist ./static
  ```
  或方案 B：把产物放到 `main.py` 默认查找的相对位置 `COPY --from=frontend /build/dist ./frontend/dist`。建议在 Dockerfile 加一条构建自检（`test -f /app/static/index.html`）防回归。
- **验证方法**：`docker compose up -d --build && curl -i http://127.0.0.1:5555/`，应返回 index.html（text/html）而非 JSON 404；容器内 `docker exec flowerui ls /app/static` 应有 index.html。

## P1 严重

### P1-1 CORS 默认通配 + 允许凭据，任意站点可带凭据跨域请求

- **位置**：`backend/app/main.py:90-96`、`backend/app/core/config.py:31`
- **问题描述**：默认配置 `cors_origins: List[str] = ["*"]`，且中间件固定 `allow_credentials=True`：
  ```python
  app.add_middleware(
      CORSMiddleware,
      allow_origins=settings.cors_origins,
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  ```
  已在本机用 Starlette 实测验证：`allow_origins=["*"]` + `allow_credentials=True` 时，Starlette 会**回显请求方任意 Origin** 并附带 `Access-Control-Allow-Credentials: true`（实测 `Origin: http://evil.example.com` → 响应 `access-control-allow-origin: http://evil.example.com` + `credentials: true`，预检同样放行）。等价于对互联网上任何站点开放带凭据跨域访问本 API。当前 API 用 Bearer token（存 localStorage）风险相对受控，但一旦引入 cookie 会话等可被浏览器自动携带的凭据即为完整 CSRF/凭据外泄通道；且该默认值直接面向公网部署。
- **触发条件**：使用默认配置启动（未设置 `FLOWER_CORS_ORIGINS`），任意第三方网页发起跨域请求。
- **修复方案**：
  ```python
  # config.py：默认值收紧
  cors_origins: List[str] = []

  # main.py：通配时禁止携带凭据，显式白名单时才允许
  origins = settings.cors_origins
  app.add_middleware(
      CORSMiddleware,
      allow_origins=origins,
      allow_credentials=bool(origins) and "*" not in origins,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  ```
  并在 `runtime_config.py:98` 的 cors_origins 字段描述中补充「填 * 将不携带凭据」。
- **验证方法**：`curl -i -H "Origin: http://evil.example.com" http://127.0.0.1:5555/api/dashboard/summary`，默认配置下不应出现 `access-control-allow-origin: http://evil.example.com`。

### P1-2 basic_auth 为空时存在 admin:admin 后门

- **位置**：`backend/app/core/security.py:50-51`
- **问题描述**：
  ```python
  # 如果没有配置凭据但开启了认证，使用默认凭据
  if not basic_auth_list:
      basic_auth_list = ["admin:admin"]
  ```
  只要 `auth_enabled=True` 而 `basic_auth` 列表为空，任何人都能用 `admin:admin` 登录获得完整权限（控制 worker、下发任务、改配置、重启后端）。可触发路径并不少见：
  1. 用户在配置页打开 `basic_auth_enabled` 开关但还没填凭据 → 认证立即开启（`config.py:56-61`），此时登录页接受 `admin:admin`；
  2. 配置了 `auth`（邮箱白名单正则）但 `basic_auth` 为空时 `auth_enabled` 同样为 True（`config.py:60-61`：`bool(basic_auth) or bool(auth)`）→ 仍是 `admin:admin` 后门；
  3. 运维手动设 `FLOWER_BASIC_AUTH_ENABLED=true` 但忘配 `FLOWER_BASIC_AUTH`。

  前端 `CredentialsEditor.vue:29-31` 在列表为空时还会展示默认 `admin:admin` 占位行，进一步误导用户认为这是「正常默认账号」。
- **触发条件**：`basic_auth_enabled=true` 且 `basic_auth` 为空（见上）。
- **修复方案**：
  ```python
  # security.py：空凭据列表时拒绝所有登录
  if not basic_auth_list:
      logger.error("basic_auth_enabled 已开启但未配置任何凭据，拒绝所有登录")
      return False
  ```
  同时在 `runtime_config.update()` 中校验：`basic_auth_enabled` 被置为 True 时 `basic_auth` 必须非空，否则抛 `ConfigError`。
- **验证方法**：清空 `basic_auth`、开启 `basic_auth_enabled` 后 `POST /api/auth/login {"username":"admin","password":"admin"}`，应返回 401。

### P1-3 GET /api/config 向任意登录用户明文返回全部用户凭据

- **位置**：`backend/app/services/runtime_config.py:264-266`（`describe()`）
- **问题描述**：
  ```python
  # basic_auth 是「可编辑的敏感项」：返回真实值便于界面直接编辑，
  # 脱敏逻辑只作用于只读敏感项。
  "value": value if (include_secret_values or f.editable) else _mask(f, value),
  ```
  `basic_auth` 字段为 `secret=True, editable=True`（`runtime_config.py:158-160`），因此 `GET /api/config` 会返回**所有用户 `user:password` 明文**。后果：
  1. 任意已登录的低权用户（如 bob）打开系统配置页，即可从响应/组件内存中读到 admin 及其他所有用户的密码 —— 多用户场景下等于全量凭据泄露，前端「只能编辑自己」的 UI 限制（`CredentialsEditor.vue:69-72`）形同虚设；
  2. 当 `auth_enabled=False`（默认部署）时，`get_current_user` 直接放行 `anonymous`（`security.py:99-100`），**任何匿名访问者**都能 `GET /api/config` 拿到已配置的凭据。

  这直接违背本模块 docstring 的自我承诺（`runtime_config.py:13`：「脱敏：…basic_auth 的密码部分不外发明文」）。
- **触发条件**：`GET /api/config`（登录用户；认证关闭时匿名即可）。
- **修复方案**：
  ```python
  # runtime_config.py describe()：敏感项一律脱敏；编辑用「掩码项=不变」语义
  "value": value if include_secret_values else _mask(f, value),
  ```
  配套：`update()` 中对 `basic_auth` 采用合并策略 —— 值等于掩码形态（含 `******`）的条目保持原值不变，新明文条目才替换/追加；`PUT /api/config` 响应里的 `config` 同样走脱敏。
- **验证方法**：配置两个用户后，用其中一个用户登录 `GET /api/config`，`items` 中 `basic_auth.value` 不含明文密码；关闭认证后匿名请求同样脱敏。

### P1-4 认证过程把明文凭据写入日志

- **位置**：`backend/app/core/security.py:45-46`
- **问题描述**：
  ```python
  logger.info(f"basic_auth from runtime: {basic_auth_list}")
  logger.info(f"basic_auth from settings: {settings.basic_auth}")
  ```
  `verify_basic_credentials` 在**每次登录、每次带 Basic 头的请求**（`get_current_user → _from_basic_header`，即每个受保护 API 请求）都会以 INFO 级别把完整 `user:password` 列表打进日志。`manage.sh` 会把 stderr 重定向到 `_uvicorn_err_*.log` 长期保存，等于把全部账号密码明文落盘；登录接口高频调用时日志还会被凭据刷屏。
- **触发条件**：认证开启后任何一次登录或 Basic 认证请求。
- **修复方案**：删除这两行（或降为 `logger.debug("basic_auth 条目数=%d", len(basic_auth_list))` 只记数量）。
- **验证方法**：登录后检查 `_uvicorn_err_*.log` / stdout，不应再出现 `user:password` 明文。

### P1-5 /api/task/apply 可无限阻塞，耗尽线程池（DoS）

- **位置**：`backend/app/api/routers/tasks.py:189-206`、`backend/app/services/manager.py:630-645`（`apply_task` 的 `wait=True` 分支）
- **问题描述**：
  ```python
  # manager.py
  if wait:
      result = await self._run(result.get, propagate=False, timeout=timeout)
  ```
  当 `timeout=None`（`tasks.py:195` `timeout: Optional[float] = Query(None, ge=1)` 允许不传）时，`result.get(timeout=None)` **无限等待**，占用 `run_in_executor` 的默认线程池（`min(32, cpu+4)` 线程）。revoke / pool grow / inspect / broker 查询等所有控制面操作都走同一默认线程池 —— 攻击者（或误操作的脚本客户端）只要并发发起若干不带 timeout 的 `/api/task/apply?wait=true`（指向永远不会执行的队列/不存在的任务名），即可把所有 worker 线程占满，整个控制面瘫痪。前端页面默认传了 timeout=10，所以这是 API 契约层面的漏洞（curl/脚本即可触发）。
- **触发条件**：`POST /api/task/apply` 带 `wait=true` 且不传 `timeout`，或任务名使其永不执行。
- **修复方案**：
  ```python
  # tasks.py：等待模式必须有上界
  async def task_apply(payload: ApplyPayload,
                       wait: bool = Query(False),
                       timeout: float = Query(30.0, ge=1, le=300)) -> ...:
  # manager.py 防御：timeout = min(float(timeout or 60.0), 300.0)
  ```
- **验证方法**：`curl -X POST '.../api/task/apply?wait=true' -H 'Content-Type: application/json' -d '{"taskname":"no.such.task"}'`（不传 timeout），修复后应立即 422 或按默认上限返回；修复前连接永久挂起，并发 10+ 请求后其他控制操作明显卡死。

### P1-6 Dashboard/Monitor 页 15s 定时器永不清理，每次进入累加一个

- **位置**：`frontend/src/views/DashboardView.vue:123`、`frontend/src/views/MonitorView.vue:120`
- **问题描述**：
  ```js
  // DashboardView.vue onMounted
  await loadDistribution()
  setInterval(loadDistribution, 15000)   // ← 无句柄、无任何清理
  ```
  两个页面都只用了 `onMounted`，**没有 `onBeforeUnmount`/`onUnmounted`** 清理 interval（对比 `TasksView.vue:126`、`BrokerView.vue:70` 都正确做了 `clearInterval`）。组件卸载后闭包存活，定时器继续每 15s 调 `GET /api/dashboard/task-distribution`（服务端还要遍历内存中全部任务）；且每次重新进入页面 `onMounted` 再建一个新的 —— 在 Dashboard↔Monitor↔Tasks 间来回切换 N 次后，浏览器里就有 N 个并行 15s 轮询，随使用时间线性增长（内存 + 无效请求双重泄漏），浏览器长时间挂着会越来越卡。
- **触发条件**：进入「监控总览」或「实时监控」页后切换到其他页面（离开即开始泄漏），反复进出持续累加。
- **修复方案**：
  ```js
  let distTimer = null
  onMounted(async () => {
    if (!store.timeline.length) { /* ... */ }
    await loadDistribution()
    distTimer = setInterval(loadDistribution, 15000)
  })
  onBeforeUnmount(() => clearInterval(distTimer))
  ```
  MonitorView 同理。
- **验证方法**：进入 Dashboard 后打开 Network 面板切到其他页，`task-distribution` 请求应停止（修复前持续每 15s 一次）；来回切换 5 次后 DevTools 定时器数量不再增长。

### P1-7 manage.sh stop 会杀死本机全部 python/node 进程

- **位置**：`manage.sh:78-81`（Windows 兜底）、`manage.sh:83-95`（Linux 兜底）
- **问题描述**：按端口查不到 PID 时的兜底逻辑：
  ```bash
  # 2) 兜底：按进程名 taskkill（reloader 父进程不占端口，必须杀进程名）
  taskkill /F /IM python.exe >/dev/null 2>&1 || true
  taskkill /F /IM node.exe  >/dev/null 2>&1 || true
  ```
  `taskkill /F /IM python.exe` 会杀掉**整台机器上所有** python.exe / node.exe 进程 —— 包括用户其他项目的开发服务器、IDE 内置解释器、数据脚本等，属破坏性操作。Linux 分支的 `pkill -f "uvicorn"` / `pkill -f "vite"`（`manage.sh:94-95`）同样会命中无关进程。`dev-restart.ps1:50-70` 用 `Get-NetTCPConnection -LocalPort` 精确按 PID 杀进程，才是正确做法，`manage.sh` 应与其对齐。
- **触发条件**：Windows 下执行 `./manage.sh stop` 且第一步按端口取 PID 失败（解析不到、权限问题或端口被非预期进程占用）。
- **修复方案**：删除按进程名的兜底，改为「按端口解析失败时直接报错并提示手动处理」；Linux 分支用 `lsof` 精确按 PID 杀：
  ```bash
  elif command -v lsof &>/dev/null; then
      lsof -ti:"$BACKEND_PORT" | xargs -r kill -9
      lsof -ti:"$FRONTEND_PORT" | xargs -r kill -9
  else
      log_warn "无法安全解析端口占用进程，请手动停止"
  fi
  ```
- **验证方法**：另开终端启动无关的 `python -m http.server 8000` 与常驻 node 进程，执行 `manage.sh stop`，修复后这两个进程应存活。

### P1-8 RabbitMQ 非默认 vhost 时请求错误的 Management API

- **位置**：`backend/app/services/broker.py:40`（vhost 解析）、`broker.py:55-61`（`RabbitMQ.queues` 的 URL 构造）
- **问题描述**：
  ```python
  self.vhost = quote(self.vhost, "") or "/" if self.vhost != "/" else self.vhost
  ...
  self.http_api = f"http://{self.user}:{self.password}@{self.hostname}:{self.port}/api/{self.vhost}"
  ...
  url = urljoin(self.http_api, "queues/" + self.vhost)
  ```
  对非默认 vhost（如 `amqp://guest:guest@localhost:5672/myvhost`），已用 urljoin 实测：最终 URL 为 `http://guest:guest@localhost:15672/api/queues/myvhost` —— 这是**默认 vhost 下名为 myvhost 的「单个队列详情」端点**，而不是列出 myvhost 全部队列的 `http://.../api/myvhost/queues`。RabbitMQ 对不存在的队列返回 404 → `queues()` 静默返回 `[]`，Broker 页显示「无法获取队列信息」。即：只要 broker URL 带非空 vhost，RabbitMQ 集群的队列监控完全失效且无任何报错。（默认 vhost 时该式子还会构造出 `/api/queues//` 双斜杠 URL，行为依赖 RabbitMQ 的路径归一化，同样建议一并修正。）
- **触发条件**：`broker_url` 形如 `amqp://user:pass@host:5672/<非默认 vhost>`。
- **修复方案**：
  ```python
  # 正确构造 Management API 列表地址
  url = self.http_api.rstrip("/") + "/queues"   # http://host:15672/api/{vhost}/queues
  ```
  建议加一个不依赖真实 RabbitMQ 的 URL 构造单元测试（断言字符串）。
- **验证方法**：本地起 RabbitMQ 建 vhost `test` 与队列，`FLOWER_BROKER_URL=amqp://guest:guest@127.0.0.1:5672/test` 启动，`GET /api/broker` 应返回该 vhost 的队列列表。

## P2 一般

### P2-1 运行时修改 worker/任务容量上限实际无效

- **位置**：`backend/app/main.py:45-51`（`_apply_capacity`）、`backend/app/services/runtime_config.py:122-125`
- **问题描述**：配置页把「Worker 上限 / 任务上限」标为**可热更新**（`editable=True`、无 `restart=True`），保存后触发钩子：
  ```python
  def _apply_capacity(_value=None) -> None:
      state = getattr(manager, "state", None)
      if state is None:
          return
      state.max_workers_in_memory = settings.max_workers
      state.max_tasks_in_memory = settings.max_tasks
  ```
  但已核对 celery 5.6.3 源码（`celery/events/state.py:413-419`、`kombu/utils/functional.py:44-83`）：真正的容量限制保存在 `state.workers.limit` / `state.tasks.limit`（LRUCache 实例属性，`__setitem__`/`update` 时动态读取 `self.limit`）；`State.max_workers_in_memory` 只是初始化时的记账字段。因此修改 `max_*_in_memory` **对 LRU 淘汰毫无作用**，界面提示「已更新」但实际容量不变，直到进程重启。
- **触发条件**：在系统配置页修改「Worker 上限」或「任务上限」并保存（不重启）。
- **修复方案**：
  ```python
  def _apply_capacity(_value=None) -> None:
      state = getattr(manager, "state", None)
      if state is None:
          return
      state.workers.limit = settings.max_workers   # LRUCache 动态读 limit，立即生效
      state.tasks.limit = settings.max_tasks
      state.max_workers_in_memory = settings.max_workers
      state.max_tasks_in_memory = settings.max_tasks
  ```
- **验证方法**：mock 模式把「任务上限」调小（如 200）并保存，继续产生任务后 `GET /api/system` 的 `tasks_in_memory` 应在新上限处封顶（修复前保持原上限）。

### P2-2 WS 模式下 Worker 表格永不实时更新

- **位置**：`backend/app/services/manager.py:104-117`（`_timeline_loop` 只推 `summary`/`timeline`）、`frontend/src/stores/app.js:85-92`
- **问题描述**：后端每 2s 广播的只有 `timeline` 与 `summary`（聚合数字），worker 列表行（`worker_rows()`）只在 WS 连接建立时的 `snapshot` 帧（`ws.py:51-58`）推送一次；前端 `app.js` 的 `summary` 处理器也只更新 `summary.value`，不更新 `workers.value`。结果：WS 模式下 Dashboard 的 Worker 表格、Workers 页表格在首屏快照之后就**冻结**（新上线/掉线的 worker、活跃任务数变化都看不到），侧栏却显示「实时连接正常」；而轮询模式（`/api/dashboard/snapshot` 每次带 `workers`）完全正常 —— 两种通道行为不一致。
- **触发条件**：使用默认 WS 通道停留超过一个快照周期（2s 以上）。
- **修复方案**（二选一）：
  1. 后端在 `_timeline_loop` 中随 summary 一起下发 workers（每 2s，数据量小）：
     ```python
     hub.publish_threadsafe({"type": "workers", "workers": self.worker_rows()})
     ```
     前端增加 `socket.on("workers", (msg) => (workers.value = msg.workers || []))`；
  2. 或前端在 WS 模式下对 worker 表叠加低频（如 30s）`workerApi.table()` 轮询兜底。
- **验证方法**：WS 模式打开 Workers 页，mock 里对某 worker 执行「关闭节点」，表格应在数秒内自动更新（修复前冻结）。

### P2-3 任务结果等待超时返回 500 而非 504/408

- **位置**：`backend/app/api/routers/tasks.py:241-248`（`task_result`）、`tasks.py:189-206`（`task_apply` wait 分支）、`backend/app/services/manager.py:663-674`
- **问题描述**：`manager.task_result` / `apply_task(wait=True)` 内部 `await self._run(result.get, timeout=timeout, ...)`。已在本机用 celery 5.6.3 实测：`AsyncResult.get(timeout=...)` 超时抛的是 **`celery.exceptions.TimeoutError`**。该异常不是 `ControlError`，两个路由都只 `except ControlError`，因此「任务还在跑、等 N 秒没等到结果」直接 500 Internal Server Error；前端 `TaskDetailView.fetchResult()`（`TaskDetailView.vue:74-86`）把「还在执行」显示成红色报错。
- **触发条件**：对未完成的任务调用 `GET /api/task/result/{id}?timeout=N`，或 apply wait 模式在超时前任务未完成。
- **修复方案**：
  ```python
  from celery.exceptions import TimeoutError as CeleryTimeoutError

  @router.get("/task/result/{taskid}")
  async def task_result(taskid: str, timeout: Optional[float] = Query(None)):
      try:
          return await manager.task_result(taskid, timeout)
      except CeleryTimeoutError:
          raise HTTPException(status_code=504, detail="等待任务结果超时（任务可能仍在执行）")
      except ControlError as exc:
          raise HTTPException(exc.status_code, exc.message)
  ```
  `task_apply` 的 wait 分支同样捕获并返回 504 + 当前 state。
- **验证方法**：下发一个 long 任务后立即 `curl '.../api/task/result/<id>?timeout=2'`，应返回 504 而非 500。

### P2-4 每次 broker 查询新建 Redis 连接池且不关闭

- **位置**：`backend/app/services/manager.py:301-321`（`broker_queues`）、`backend/app/services/broker.py:22-36`（`RedisBase.__init__`）
- **问题描述**：`manager.broker_queues()` 每次调用都 `create_broker(...)` 新建 broker 对象；Redis 系 broker 在 `__init__` 里 `self.redis = self._get_redis_client()` 创建全新 `redis.Redis`（含独立 ConnectionPool）/Sentinel，用完**从不调用 close/aclose**。Broker 页每 5s 轮询一次 `/api/broker`（`BrokerView.vue:67`），外加 `/api/queues/length`，等于持续不断地创建并遗弃 Redis 连接池：连接靠 GC 回收，期间 TCP 连接与文件描述符泄漏，高频率下可耗尽 redis `maxclients`。
- **触发条件**：真实 Redis broker 模式下打开 Broker 页（5s 轮询）即可持续发生。
- **修复方案**：把 broker 客户端缓存为长生命周期单例：
  ```python
  # manager.py
  self._broker_client = None

  def _get_broker(self):
      if self.mock_mode:
          return self.mock
      if self._broker_client is None:
          self._broker_client = create_broker(
              broker_uri(include_password=True),
              transport=transport_driver(),
              broker_options=dict(get_celery_app().conf.broker_transport_options or {}),
          )
      return self._broker_client

  # shutdown 中：
  close = getattr(self._broker_client, "aclose", None) or getattr(self._broker_client, "close", None)
  if close:
      await close()
  ```
  并为 `Redis`/`RabbitMQ`/`RedisSocket` 增加 `aclose()`（`await self.redis.aclose()` / `await self.client.aclose()`）。
- **验证方法**：`lsof -p <uvicorn pid> | grep -c :6379` 在 Broker 页打开几分钟前后对比，修复前持续增长，修复后稳定。

### P2-5 搜索 DSL：以 "state" 开头的普通词被误解析为状态过滤

- **位置**：`backend/app/services/search.py:40-41`
- **问题描述**：
  ```python
  elif part.startswith("state"):
      parsed["state"].append(preprocess_search_value(part[len("state:"):]))
  ```
  判断的是 `startswith("state")` 而非 `startswith("state:")`。搜索 `stateful`（想按任务名/ID 子串匹配）会被解析成 `state=["ul"]`（`"stateful"[6:]`），命中零条；任何以 state 开头的任务名（`state_check`、`state_sync`…）都无法用普通词搜到。原 flower 实现此处为 `startswith('state:')`，属移植时引入的回归。
- **触发条件**：搜索框输入以 `state` 开头的普通词（不带冒号）。
- **修复方案**：
  ```python
  elif part.startswith("state:"):
      parsed["state"].append(preprocess_search_value(part[len("state:"):]))
  ```
- **验证方法**：存在名为 `app.tasks.state_check` 的任务时，搜索 `state_check` 应命中（修复前 0 条）。

### P2-6 「查看该调用链的全部任务」在任务列表页不生效

- **位置**：`frontend/src/views/TaskDetailView.vue:176-179`、`frontend/src/views/TasksView.vue:32-33`、`frontend/src/App.vue:60`
- **问题描述**：任务详情抽屉里的 root/parent 标签会 `router.push({ name: 'tasks', query: { root_id } })`。但 `TasksView` 只在**组件创建时**读取一次路由参数：
  ```js
  const query = reactive({
    ...
    root_id: route.query.root_id || '',
    parent_id: route.query.parent_id || ''
  })
  ```
  场景一（最常见）：用户就停留在任务列表页上打开详情抽屉（抽屉不切换路由），点「查看该调用链」时路由 path 没变、只是 query 变化，`TasksView` 不重建，`root_id` 永远保持空 —— URL 变了但列表不过滤，按钮看起来「没反应」。场景二：`TasksView` 在 `keep-alive` 名单里（`App.vue:60`），从其他页带着新 query 回来时组件被复用，同样不重读 `route.query`。
- **触发条件**：在任务列表页打开详情抽屉 → 点 root/parent 标签；或经 keep-alive 复用的 TasksView 收到带 root_id/parent_id 的导航。
- **修复方案**：
  ```js
  // TasksView.vue：监听路由变化重新同步链路过滤条件
  watch(() => route.query, (q) => {
    const rid = q.root_id || ''
    const pid = q.parent_id || ''
    if (rid !== query.root_id || pid !== query.parent_id) {
      query.root_id = rid
      query.parent_id = pid
      query.offset = 0
      load()
    }
  })
  ```
- **验证方法**：任务列表页打开一个有 root_id 的任务详情，点 root 标签，表格应只显示同链路任务并出现「调用链过滤」提示条。

### P2-7 TasksView 自动刷新与手动查询竞态

- **位置**：`frontend/src/views/TasksView.vue:60-71`（`load`）、`TasksView.vue:123`（5s 自动刷新）
- **问题描述**：`load()` 没有请求序号/取消机制，5s 自动刷新（`load(true)`）与用户点「查询」、翻页、排序触发的 `load()` 会并发飞行。`rows.value = res.data` 按**响应到达顺序**写入，慢的旧请求（旧 offset/旧过滤条件）可能后到覆盖新请求结果 —— 表现为「点了查询/翻页，表格闪回旧数据」。后端 inspect 压力大时更易复现。
- **触发条件**：响应时间接近/超过 5s，或快速连续操作时自动刷新与手动刷新重叠。
- **修复方案**：
  ```js
  let loadSeq = 0
  async function load(silent = false) {
    const seq = ++loadSeq
    if (!silent) loading.value = true
    try {
      const res = await taskApi.table(buildParams())
      if (seq !== loadSeq) return          // 丢弃过期响应
      rows.value = res.data || []
      total.value = res.total || 0
    } catch (err) {
      if (seq === loadSeq && !silent) ElMessage.error(err?.message || '加载失败')
    } finally {
      if (seq === loadSeq) loading.value = false
    }
  }
  ```
- **验证方法**：DevTools 调成 Slow 3G，在列表页快速翻页/查询，修复后表格不会回退到旧数据。

### P2-8 404 判断使用 err.status，永远不成立

- **位置**：`frontend/src/views/WorkerDetailView.vue:25`、`frontend/src/views/TaskDetailView.vue:45`
- **问题描述**：
  ```js
  } catch (err) {
    if (err?.status === 404) notFound.value = true
    else if (!silent) ElMessage.error(err?.message || '加载失败')
  }
  ```
  axios 错误对象的状态码在 `err.response.status`，`err.status` 不存在。后果：worker/任务被移除（超出任务保留上限被淘汰、worker 下线）后，详情抽屉不会显示「已不存在」的友好提示，而是停留在**过期数据**上（`info.value`/`task.value` 不被清空），非静默刷新时还反复弹「加载失败」错误条。
- **触发条件**：打开任务/worker 详情后，该对象在内存状态中被淘汰或下线。
- **修复方案**：两处均改为 `if (err?.response?.status === 404) notFound.value = true`。
- **验证方法**：mock 模式关闭某 worker 后打开其详情抽屉，应显示「Worker 已不存在」而非陈旧数据 + 错误提示。

### P2-9 Inspector 幽灵 worker 被标记为在线

- **位置**：`backend/app/services/inspector.py:29`、`backend/app/services/manager.py:211-216`
- **问题描述**：`inspector.workers` 是 `defaultdict(dict)`，只增不删。worker 一旦探测成功就永远留在缓存里；`worker_rows()` 对「只有 inspect 缓存、状态机里没有」的名字执行：
  ```python
  for name in self.inspector.workers:
      if name not in rows and name not in seen:
          rows[name] = {"name": name, "status": True}   # ← 无条件标记在线
  ```
  真实集群中 worker 异常退出（kill -9、容器崩溃）且未发出 `worker-offline` 事件时，该幽灵会**永远显示为在线**，`is_known_worker()` 还会让后续控制命令对不存在的 worker「成功」返回。配置项 `purge_offline_workers` 清理的只是 `state.workers`，管不到 inspector 缓存。
- **触发条件**：真实集群中 worker 无下线事件地消失（崩溃/断网）。
- **修复方案**：
  1. 补充行改为 `{"name": name, "status": False, "stale": True}`，或仅当 `info["timestamp"]` 在最近一个 inspect 周期内才视为在线；
  2. auto_refresh 循环里定期清理 `inspector.workers` 中「不在 state.workers 且 timestamp 超过 N 分钟」的条目。
- **验证方法**：kill -9 一个 worker，Workers 页该行应在 N 分钟后转离线/消失（修复前永远在线）。

### P2-10 state.counter 永不清理，内存缓慢增长

- **位置**：`backend/app/services/state.py:26`
- **问题描述**：`self.counter = collections.defaultdict(Counter)` 按 worker 名累计每类事件计数，从不回收。celery `State.workers` 是 `LRUCache(max_workers)` 会淘汰，`counter` 不会 —— 对 worker 名不固定（autoscale 短命 worker、`worker@host-123` 类命名）的集群，`counter` 的键无限增长，长跑数月后成为可观的内存泄漏（每个键还带一个 Counter）。
- **触发条件**：worker 生命周期短、名字多变的集群长期运行。
- **修复方案**：在 `EventsState.event()` 中对 `worker-offline` 且 `worker_name not in self.workers` 时 `self.counter.pop(worker_name, None)`；或改用有容量上限的结构。
- **验证方法**：脚本模拟大量不同 hostname 的事件后，`len(state.counter)` 应保持在活跃 worker 数量级。

### P2-11 /api/system 未鉴权

- **位置**：`backend/app/api/routers/monitor.py:14-52`
- **问题描述**：`/metrics` 与 `/healthcheck` 免鉴权是合理设计（Prometheus/K8s 抓取，文件内注释已说明），但同一 router 上的 `GET /api/system`（`monitor.py:27`）也一起免鉴权了 —— 返回 broker 连接串、result backend、运行模式、事件采集状态、平台/版本等信息。认证开启时其他所有 `/api/*` 都要登录，唯独这个系统信息面板匿名可访问，属路由装配疏漏。
- **触发条件**：`GET /api/system`（匿名）。
- **修复方案**：把 `system_info` 挪到带 `dependencies=[Depends(get_current_user)]` 的 router（如 `system.py`），或在端点加 `_user: str = Depends(get_current_user)`。
- **验证方法**：开启认证后不带 token `curl /api/system` 应返回 401。

### P2-12 登录接口无速率限制

- **位置**：`backend/app/api/routers/auth.py:36-48`
- **问题描述**：`POST /api/auth/login` 无重试限制、无锁定、无验证码，401 后仍可立即再试。凭据体系存在弱口令场景（P1-2 的默认账号），等于向公网开放在线爆破；且 `verify_basic_credentials` 逐条 `compare_digest` 命中即 break（`security.py:56-58`），不同失败路径耗时不同，附带时序侧信道。
- **触发条件**：公网暴露 + 认证开启。
- **修复方案**：最小改动：按 (IP, username) 滑动窗口计数（进程内 dict + 过期清理），连续失败 N 次后 429 临时锁定；`verify_basic_credentials` 改为对全部条目执行 `compare_digest` 后 OR，消除时序差异。更完整方案接入 `slowapi`。
- **验证方法**：脚本连续 20 次错误密码登录，修复后应收到 429。

### P2-13 _read_env_file 遗留 print，启动时打印全部配置（含凭据）

- **位置**：`backend/app/services/runtime_config.py:433`
- **问题描述**：
  ```python
  def _read_env_file() -> Dict[str, Any]:
      ...
          key, _, value = line.partition("=")
          ...
          print(key, value)      # ← 遗留调试输出
  ```
  每次进程启动（`load()`）都会把 `flowerui.runtime.env` 里**每一行原始值**（含 `basic_auth` 全部账号密码、`secret_key`、带密码的 `broker_url`）原样打印到 stdout —— manage.sh 会把它写进 `_uvicorn_*.log`。全项目唯一的 `print(`（已 grep 确认）。
- **触发条件**：每次后端启动。
- **修复方案**：删除该 `print` 行（或改 `logger.debug` 并对 secret 字段脱敏）。
- **验证方法**：启动后端后 grep 日志文件，不应出现 `basic_auth=...` 明文行。

### P2-14 后端重启在 Windows 下静默失败

- **位置**：`backend/app/services/restart.py:56-61`
- **问题描述**：`POST /api/system/restart` 通过后台线程 `subprocess.Popen(["bash", RESTART_SCRIPT, "restart"])` 执行 `manage.sh restart`。Windows 上 `bash` 不在 PATH 时抛 `FileNotFoundError`，仅打一行 `logger.error` —— 而 API 已返回 `{"ok": true, "message": "后端正在重启..."}`，前端随后 `location.reload()`（`ConfigView.vue:191`），用户看到「服务没了、页面一直转圈」，实际进程还活着且配置未生效。另外 `manage.sh restart` 走 dev 模式（`--reload`、日志落 `_uvicorn_*.log`），与 `run`（nohup 生产模式）不一致：以 `manage.sh run` 启动的服务经 Web 重启后降级为 dev 模式。
- **触发条件**：Windows 下从配置页点「重启系统」；或生产模式启动后经 Web 重启。
- **修复方案**：
  1. 探测可用 shell：Windows 优先 `pwsh -File dev-restart.ps1`（该脚本已存在且按 PID 精确停止），失败时 API 直接返回 503 说明原因；
  2. 记录启动模式（run vs dev）到 runtime env，重启时按原模式拉起；
  3. 确认子进程已启动后再返回成功（202）。
- **验证方法**：Windows 上执行重启 API，日志不应出现「重启脚本未找到」，且服务在 ~15s 内恢复（`curl /healthcheck` 验证）。

### P2-15 axios 30s 全局超时小于 apply 最大等待 120s

- **位置**：`frontend/src/api/client.js:5`、`frontend/src/views/ApplyTaskView.vue:30`（`timeout: 120` 上限）、`ApplyTaskView.vue:71-72`
- **问题描述**：axios 实例全局 `timeout: 30000`；下发任务页「同步执行」模式允许选择最长 **120s** 等待超时（input-number `max=120`）。用户设 31~120s 时，浏览器 30s 就抛 `timeout of 30000ms exceeded`，界面报「下发失败」，而后端其实还在等结果（任务可能马上完成）—— 前端承诺的 120s 等待在 30s 以上完全失效。
- **触发条件**：apply（同步执行）模式 + 等待超时 > 30s。
- **修复方案**：
  ```js
  // api/index.js：apply 请求按等待超时放大客户端超时
  apply: (taskname, payload, timeout) =>
    http.post('/api/task/apply', payload, {
      params: { wait: true, timeout },
      timeout: ((timeout || 10) + 15) * 1000   // 给网络留余量
    })
  ```
- **验证方法**：下发一个 40s 完成的任务并选「同步执行 60s」，修复后应正常等到结果而不是 30s 报错。

### P2-16 mock 与真实 RabbitMQ 的 idle_since 类型不一致

- **位置**：`backend/app/services/mock.py:447`、`frontend/src/views/BrokerView.vue:136`、`frontend/src/utils/format.js:41-44`
- **问题描述**：真实 RabbitMQ Management API 的 `idle_since` 是 **epoch 秒（数字）**；mock 返回格式化字符串：
  ```python
  "idle_since": None if depth else time.strftime("%Y-%m-%d %H:%M:%S"),
  ```
  前端统一用 `fmtFromNow(row.idle_since)`（`dayjs(ts * 1000)`）。mock 模式下字符串 × 1000 = NaN，`dayjs(NaN).fromNow()` 渲染为无效值 —— 演示模式下 Broker 页「空闲自」列全部错误。这正是「mock 与真实模式行为不一致」的典型实例（顺带：当前 mock 空闲时间恒等于当前时刻，刷新不变）。
- **触发条件**：mock 模式 + 存在空闲队列。
- **修复方案**：
  ```python
  # mock.py：与 RabbitMQ 对齐为 epoch 秒
  "idle_since": None if depth else int(time.time()) - random.randint(60, 3600),
  ```
- **验证方法**：mock 模式打开 Broker 页，「空闲自」应显示合理的「X 分钟前」且随时间推移变化。

### P2-17 url_prefix 配置完全不生效

- **位置**：`backend/app/core/config.py:30`、`backend/app/services/runtime_config.py:97`
- **问题描述**：`Settings.url_prefix`（「反向代理下的子路径」，可在配置页编辑、会落盘）在代码中**没有任何使用点**（已 grep 全后端确认：除定义与字段声明外零引用）。FastAPI 应用没有 `root_path`，路由也没有加前缀。用户在 nginx 下挂到 `/flower/` 子路径后按提示配置 `url_prefix=/flower`，保存成功、显示「已更新」，但 API/静态资源依然只在根路径可用 —— 配置项是纯装饰。
- **触发条件**：反向代理子路径部署。
- **修复方案**：
  1. 真正支持：`FastAPI(root_path=settings.url_prefix)` + uvicorn `--root-path`（字段本就 `restart=True`，与现语义一致）；
  2. 短期：把该字段标为 `todo=True`（`todo_reason="尚未实现"`），避免用户误用。
- **验证方法**：`url_prefix=/flower` + `uvicorn --root-path /flower` 后 `curl http://host:5555/flower/api/system` 应 200（方案 1）。

### P2-18 RabbitMQ Management API 关闭 TLS 证书校验

- **位置**：`backend/app/services/broker.py:52`
- **问题描述**：
  ```python
  self.client = httpx.AsyncClient(verify=False)
  ```
  访问 RabbitMQ Management HTTP(S) API（携带凭据）时禁用 TLS 证书校验 —— 若 management 走 HTTPS，中间人可窃取凭据/篡改队列数据。
- **触发条件**：management API 使用 HTTPS。
- **修复方案**：默认 `verify=True`；需要自签证书时从 `broker_transport_options` 读取 CA 路径传入 `verify=<path>` 并加注释说明。
- **验证方法**：代码评审 + 自签 HTTPS management 端点验证可配置 CA 后正常。

## P3 轻微

### P3-1 首次 inspect 的 asyncio.Task 未持有引用，可能被 GC

- **位置**：`backend/app/services/manager.py:88`
- **问题描述**：`asyncio.create_task(self._safe_inspect())` 未保存引用。事件循环只持有任务的弱引用，浮空任务可能在完成前被 GC（CPython 官方文档明确警告），导致真实模式首屏 worker 探测「时有时无」，要等 10s 的 auto_refresh 或前端手动刷新才有数据。
- **修复方案**：`self._first_inspect = asyncio.create_task(self._safe_inspect())`，并在 `shutdown()` 里一并取消。
- **验证方法**：真实集群冷启动，`GET /api/workers` 首屏成功率应稳定 100%。

### P3-2 控制命令未捕获 broker 异常，返回 500

- **位置**：`backend/app/api/routers/control.py:14-20`（`_wrap`）
- **问题描述**：`_wrap` 只捕获 `ControlError`；broker 短暂不可达时 kombu 抛的连接异常会变成 500 + traceback，而不是 502/503「broker 不可达」。所有控制端点（shutdown/pool/queue/rate-limit/timeout/revoke）同病。
- **修复方案**：在 `manager` 的控制方法里捕获 kombu 连接异常（如 `kombu.exceptions.OperationalError`）并转成 `ControlError("broker 不可达", 502)`。
- **验证方法**：停掉 broker 后调用任意控制端点，应返回 502/503 友好错误。

### P3-3 worker_shutdown 无回执，恒报成功

- **位置**：`backend/app/services/manager.py:391-393`
- **问题描述**：`shutdown` 广播不带 `reply=True`，worker 不存在/未收到指令时 API 仍返回「成功」，前端弹「操作成功」，用户以为节点已停。
- **修复方案**：`reply=True` 并校验回执，无回执时返回 202 + 「未收到回执，请确认 worker 在线」；或至少前端文案改为「指令已发送」。
- **验证方法**：对不存在的 worker 名调用 shutdown（绕过 is_known_worker 校验的场景），提示应如实反映无回执。

### P3-4 Events.on_event 吞掉事件处理异常（仅 debug 日志）

- **位置**：`backend/app/services/events.py:128-132`
- **问题描述**：`state.event` 抛异常时只 `logger.debug`，生产 INFO 级别下完全静默 —— 若某类事件载荷导致持续异常，监控数据悄悄缺失而无人知晓（应至少 WARNING 一次 + 计数）。
- **修复方案**：改为 `logger.warning("处理事件失败 %d 次: %s", count, exc)`（按类型限频）。
- **验证方法**：注入畸形事件，INFO 级别日志应可见告警。

### P3-5 inspector._lock 定义后从未使用

- **位置**：`backend/app/services/inspector.py:30`
- **问题描述**：`self._lock = asyncio.Lock()` 从未被 acquire，并发 inspect（auto_refresh + 手动刷新 + 控制后刷新）之间无保护。当前 CPython 下 dict 写是原子的，未造成数据损坏，但意图缺失会让后续维护者误以为有保护。
- **修复方案**：在 `inspect()` 中 `async with self._lock:` 串行化，或删掉该锁并加注释说明允许并发。
- **验证方法**：代码评审。

### P3-6 WS reader 任务异常永不 retrieve

- **位置**：`backend/app/api/routers/ws.py:60-76`
- **问题描述**：`reader()` 内 `receive_text()` 在客户端异常断开时抛 `WebSocketDisconnect`，reader 任务带着异常结束；主循环在 `finally` 里 `reader_task.cancel()`，但异常从未被 retrieve，asyncio 会打「Task exception was never retrieved」噪音，且主循环的 `queue.get()` 要等下一次消息/断开才知道连接已死（无超时心跳时可能挂住较久）。
- **修复方案**：`finally` 中先判断 `reader_task.done()` 再决定 cancel，并在主循环用「queue.get 与 reader 完成」二选一等待，或定期 ping 检测死连接。
- **验证方法**：客户端直接 TCP 断开，服务端日志不应出现 unretrieved exception。

### P3-7 hub 历史缓冲覆盖与「不重不漏」注释矛盾

- **位置**：`backend/app/services/hub.py:5-7`（docstring）、`hub.py:61-73`（`recent`）
- **问题描述**：docstring 承诺轮询按 cursor 增量取「不重不漏」，但历史只有 500 条（`maxlen=500`）：两个轮询间隔内事件超过 500 条时，`since` 落在历史窗口之外的条目被直接跳过，客户端 cursor 跳变，中间事件丢失且无提示。繁忙集群 + 2s 轮询下并非不可能。
- **修复方案**：`recent()` 返回 `"gaps": bool`（`since < 最旧 seq` 时为 True），前端收到 gap 时触发一次全量快照对齐；或把 history 调大并文档化上限。
- **验证方法**：mock 高速产生事件 + 慢轮询，前端事件流应出现对齐而非静默跳号。

### P3-8 WS token 通过 URL 查询串传递

- **位置**：`frontend/src/api/ws.js:33-36`
- **问题描述**：token 拼在 WS URL 查询串里，会进入浏览器历史、代理访问日志、DevTools 与中间设备日志，JWT 的暴露面扩大。
- **修复方案**：优先改用 Sec-WebSocket-Protocol 头或首帧认证（服务端先 accept 后校验首条消息，失败 close 4401）；短期至少对 token 做 URL 编码并使用更短有效期。
- **验证方法**：抓包/查看 nginx access log 中不应出现 token。

### P3-9 路由认证检查 fail-open

- **位置**：`frontend/src/router/index.js:69-80`、`frontend/src/stores/app.js:22-31`
- **问题描述**：守卫只在 `authEnabled === false`（初始值）时拉取一次认证配置；若该请求失败（网络抖动），`loadAuthConfig` 的 catch 把 `authEnabled` 置为 `false` 且 `_checked=true`，之后**整个会话按「认证未开启」处理**：后端已启用认证时，用户绕过登录页进入应用，随后所有 API 401，且因 `authed = !authEnabled || !!token` 恒为 true 而不会跳登录 —— 用户卡在白屏/报错页。
- **修复方案**：拉取失败时置 `authEnabled = true`（保守 fail-closed，宁可多弹一次登录页）或置 undefined 并在每次导航重试。
- **验证方法**：在登录页用 DevTools 阻断 `/api/auth/config` 一次，刷新后应进入登录页而非白屏卡死。

### P3-10 SPA 404 兜底为死代码（hash 路由 vs history 兜底）

- **位置**：`backend/app/main.py:114-123`、`frontend/src/router/index.js:65`（`createWebHashHistory`）
- **问题描述**：前端用 **hash** 路由，服务器永远只收到 `/`，`spa_fallback`（为 history 路由写的 404 兜底）永远不会被触发；注释「前端使用 history 路由」与实际不符。本身无害，但属于误导性死代码，日后有人依赖它排查问题会被带偏。
- **修复方案**：删掉 `spa_fallback` 与注释，或把前端切换为 `createWebHistory` 使兜底真正生效（推荐前者，hash 路由对子路径部署更稳）。
- **验证方法**：代码评审。

### P3-11 copy() 在剪贴板不可用时仍提示「已复制」

- **位置**：`frontend/src/views/TaskDetailView.vue:88-91`
- **问题描述**：`navigator.clipboard?.writeText(...)` 在非安全上下文（http + 非 localhost 部署）为 undefined，`?.` 静默跳过，但随后无条件 `ElMessage.success('已复制')`。
- **修复方案**：
  ```js
  async function copy(text) {
    try {
      await navigator.clipboard.writeText(String(text))
      ElMessage.success('已复制')
    } catch {
      ElMessage.warning('复制失败，请手动选择文本复制')
    }
  }
  ```
- **验证方法**：非 localhost 的 http 部署点 UUID 复制，提示应如实。

### P3-12 resetAll 取消确认框产生未处理的 Promise 拒绝

- **位置**：`frontend/src/views/ConfigView.vue:132-138`
- **问题描述**：`await ElMessageBox.confirm(...)` 没有 `catch`，用户点「取消」时 reject 直接抛出（console 报 Uncaught promise rejection），与同文件 `materializeConfig` 的写法（try/catch）不一致。
- **修复方案**：包一层 try/catch，取消时直接 return。
- **验证方法**：配置页点「恢复启动值」→取消，console 无未处理拒绝。

### P3-13 轮询间隔滑块 max=30000 与 POLL_MAX=120000 不一致

- **位置**：`frontend/src/views/ConfigView.vue:548`、`frontend/src/stores/settings.js:5`
- **问题描述**：滑块 `max=30000`，但 input-number 与后端校验允许到 120000（`POLL_MAX`、`runtime_config.py:150-152`）—— 同一数值两条路径的合法范围不一致，滑块拖不到 60s/120s。
- **修复方案**：统一为 `max="120000"`。
- **验证方法**：UI 上可设置 60000 并保存生效。

### P3-14 Web 重启后前端 reload 过早

- **位置**：`frontend/src/views/ConfigView.vue:184-195`、`backend/app/services/restart.py:42`
- **问题描述**：前端点「重启系统」后 `setTimeout(() => location.reload(), 2500)`，而后端重启脚本（stop → 构建检查 → start → 就绪探测最长 10s）通常需要 10~30s —— 2.5s 的 reload 落在服务已停、未起的窗口，页面直接加载失败，用户必须手动再刷一次。
- **修复方案**：改为轮询 `/healthcheck`（2s 一次，上限 60s）成功后再 `location.reload()`。
- **验证方法**：点重启后无需手动刷新即可自动恢复页面。

### P3-15 el-upload 上传成功后不清空文件列表

- **位置**：`frontend/src/views/ConfigView.vue:452-469`
- **问题描述**：上传主题成功后 `themeFile = null` 了，但 el-upload 内部文件列表仍显示已上传文件（未 `clearFiles`），`:limit=1` 导致用户再选文件会触发 exceed 警告而非替换，需要手动点叉。
- **修复方案**：保留 upload 的模板 ref，成功后 `uploadRef.value.clearFiles()`。
- **验证方法**：连续上传两个主题，第二次选择应直接替换。

### P3-16 mock 回填历史事件触发 celery 时钟漂移告警

- **位置**：`backend/app/services/mock.py`（`_bootstrap` 用过去时间戳回填 worker-online/heartbeat）
- **问题描述**：每次冷启动 mock 模式都会向日志注入多条「Substantial drift from celery@node-x may mean clocks are out of sync」告警（见 `backend/_uvicorn_err_*.log` 实测日志）。告警本身无害，但会淹没真实集群中真正重要的时钟漂移告警。
- **修复方案**：mock 回填事件改用当前时间戳（牺牲部分「历史感」），或对 mock 来源的时钟漂移告警降级/静默。
- **验证方法**：mock 冷启动后日志无 drift WARNING。

### P3-17 /docs、/openapi.json、/api/auth/config 公网暴露

- **位置**：`backend/app/main.py:80-88`（docs 常开）、`backend/app/api/routers/auth.py:24-33`
- **问题描述**：生产部署默认开着 Swagger/ReDoc 与完整 OpenAPI（全部端点 + 参数可被枚举）；`/api/auth/config` 匿名返回是否启用 basic auth、OAuth 提供方、redirect URI 等认证拓扑信息。内网工具可接受，公网部署是攻击面增量。
- **修复方案**：增加开关（如按 `debug` 联动或独立 `FLOWER_DISABLE_DOCS`），生产默认关闭 docs；`auth_config` 保留 `auth_enabled`，其余字段仅在已认证时返回。
- **验证方法**：生产配置下 `/docs` 返回 404。

### P3-18 任务列表接口无条数上限

- **位置**：`backend/app/api/routers/tasks.py:56-91`
- **问题描述**：`limit: Optional[int] = Query(None, ge=1)` —— 不传 limit 时 `iter_tasks` 返回全部（最多 100 万条/可配 500 万），序列化后是超大 JSON + 服务端高 CPU；`/api/task/info/{id}` 的 `children_tasks` 同样无 limit。
- **修复方案**：`limit: int = Query(50, ge=1, le=1000)`（count 保留）；children 加 `le=200`。
- **验证方法**：`GET /api/tasks?limit=1000000` 应 422。

### P3-19 Docker 容器以 root 运行 / compose 暴露 redis 端口

- **位置**：`Dockerfile:22-57`（无 USER）、`docker-compose.yml:19-20`
- **问题描述**：应用容器全程 root；redis 把 6379 发布到宿主机（broker 本只需容器网络互通），且 flowerui 默认无认证（basic_auth 配置行被注释），公网暴露时任何人都能读写 broker。
- **修复方案**：Dockerfile 加非 root 用户（`RUN useradd -m appuser && USER appuser`，注意目录属主与写权限）；compose 去掉 redis `ports` 或改为 `"127.0.0.1:6379:6379"`，并默认启用 FLOWER_BASIC_AUTH + FLOWER_SECRET_KEY。
- **验证方法**：`docker exec flowerui id` 非 root；外部网络连 6379 不通。

### P3-20 vite 开发代理缺少 /docs 等路径

- **位置**：`frontend/vite.config.js:23-28`
- **问题描述**：代理只有 `/api`、`/ws`、`/metrics`、`/healthcheck`，系统页里的 /docs、/redoc、/openapi.json 链接在开发模式（:5556）下 404（vite 返回自己的 404），与生产模式（:5555 直连）行为不一致。
- **修复方案**：代理表补 `/docs`、`/redoc`、`/openapi.json`。
- **验证方法**：开发模式点「Swagger UI」可打开。

### P3-21 RedisSocket 空 vhost 产生非法 socket 路径

- **位置**：`backend/app/services/broker.py:155-166`
- **问题描述**：`unix_socket_path = "/" + self.vhost`，vhost 为空时得到 `"/"`，`redis_lib.Redis(unix_socket_path="/")` 必连失败；redis socket 传输本身是小众场景，但该三目优先级写法与 P1-8 同源，容易再次踩坑。
- **修复方案**：优先从 `broker_options.get("unix_socket_path")` 读取，未配置时抛出明确错误而不是构造非法路径。
- **验证方法**：代码评审 + 单测断言空 vhost 时报错信息明确。

---

## 附录 A：验证方法与证据

以下关键结论不是纯静态推断，而是在项目 venv（Python 3.13.12 / celery 5.6.3 / redis-py 8.1.0 / fastapi 0.141.1 / starlette）中实际执行验证脚本确认（临时脚本验证后已删除）：

1. **P1-1 CORS 回显行为**：构造 allow_origins=["*"] + allow_credentials=True 的 Starlette 应用，TestClient 带 Origin: http://evil.example.com 请求，实测响应 access-control-allow-origin 回显该 Origin + access-control-allow-credentials: true，预检同样回显。
2. **P2-3 超时异常类型**：`Celery(broker="memory://").AsyncResult("nonexistent").get(timeout=0.2, propagate=False)` 实测抛 `celery.exceptions.TimeoutError`（不是 ControlError）→ 路由 500 成立。
3. **P1-8 urljoin 构造**：对 vhost=myvhost 实测 `urljoin("http://guest:guest@localhost:15672/api/myvhost", "queues/myvhost")` = `http://guest:guest@localhost:15672/api/queues/myvhost`（错误的单队列详情端点，而非 /api/myvhost/queues 列表端点）。
4. **P2-1 LRUCache 容量机制**：读 `kombu/utils/functional.py:44-83`，`LRUCache.__setitem__/update` 动态读 `self.limit`；`celery/events/state.py:413-419` 中容量在 `state.workers.limit`/`state.tasks.limit`，`max_*_in_memory` 仅记账 → 现有热更新钩子无效、修复方案（改 limit）有效。
5. **celery 5.6.3 inspect.active(safe=True) 合法**：客户端签名实测为 (safe=None)，worker 侧同步支持 —— 排除「safe 参数导致 inspect 失败」嫌疑（见附录 B）。
6. **shelve flag="n" 无害**：本机 dbm 后端为 dbm.sqlite3（Python 3.13 新增），显式 dbm.dumb.open(..., "n") 二次打开亦不报错（dumb 对 c/n 同义）—— 排除「第二次状态保存必失败」嫌疑。
7. **P0-1 路径推导**：容器内 main.py 位于 /app/app/main.py，其 parents[2] 为 /，`/frontend/dist` 不存在，且 Dockerfile 未设置 FLOWER_FRONTEND_DIST。

## 附录 B：已排查、未构成 bug 的项

以下疑点在审计过程中提出，经代码/运行证据排除，记录在此避免后续重复排查：

1. **`inspector._inspect` 的 `inspect.active(safe=True)`**：celery 5.6.3 的 inspect 客户端方法签名即为 `active(safe=None)`，worker 侧同步支持，不会产生 error 回执（已验证）。
2. **`Events.save_state` 用 `shelve.open(db, flag="n")`**：flag="n" 在本平台（dbm.sqlite3）与 dbm.dumb 下均不产生「文件已存在」错误，周期性保存可正常工作。
3. **`task_filter.iter_tasks` 的 limit/offset 逻辑**（`task_filter.py:116-120`）：逐分支推演 offset/limit 组合（0/0、2/2、offset>总数），分页数量正确。
4. **`runtime_config._read_env_file` 的值解析**：JSON/裸字符串双路径对 basic_auth（含多用户逗号分隔）、broker_url（含 user:pass@host 特殊字符）均能正确回读，与 `update()` 的写入格式自洽。
5. **`manage.sh` 的就绪探测用 `/api/config`**：认证开启时该端点返回 401，但 curl 收到任何 HTTP 响应即退出码 0，探测逻辑不受影响。
6. **`ws_events` 未 accept 先 close(4401)**：Starlette/uvicorn 会以失败握手结束连接，客户端 WS 触发 onerror→onclose→重连，行为可接受（重连相关细节归入 P3-6/P3-8 讨论）。
7. **`Events.run()` 的退避时序**：try_interval 翻倍后封顶 30s，成功重置为 1s（下次连接成功后生效），语义正确。
8. **`main.py` SPA 404 兜底对 API 前缀的排除**：前缀判断覆盖全部 API 路由（含 /api/system），无漏网（与 P3-10 的死代码问题不冲突）。
9. **`CredentialsEditor` 的双向同步**：外部 modelValue 变化时按 JSON 串比较决定是否重置本地行，避免输入被覆盖，逻辑正确。
10. **`useChart` 资源清理**：onBeforeUnmount 正确 dispose + 移除 resize 监听，ECharts 实例无泄漏（定时器泄漏问题集中在 P1-6 的业务 setInterval）。

（全文完）
