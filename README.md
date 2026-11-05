# FlowerUI

> 基于 **FastAPI + Vue 3 + Element Plus** 的 Celery 实时监控与管理平台
> —— [mher/flower](https://github.com/mher/flower) 2.0.1 的前后端分离重构版，功能全量对齐。

原版 Flower 是 Tornado 单体应用，模板渲染 + jQuery + DataTables。本项目将其拆解为纯 JSON API 的
FastAPI 后端与独立的 Vue 3 单页应用，保留全部能力的同时补充了 WebSocket 实时推送、
趋势图表与内置演示模式。

---

## 特性一览

| 能力 | Flower 2.0.1 | FlowerUI |
| --- | --- | --- |
| Worker 实时监控 | ✅ 轮询刷新 | ✅ WebSocket 推送 + 轮询兜底 |
| Worker 详情（Pool / 队列 / Config / Rusage） | ✅ | ✅ 全部字段 + 可视化 |
| 进程池控制（restart / grow / shrink / autoscale） | ✅ | ✅ |
| 队列消费控制（add / cancel consumer） | ✅ | ✅ |
| 任务列表（搜索 / 过滤 / 分页 / 排序） | ✅ DataTables | ✅ 服务端分页 + 搜索 DSL |
| 任务详情（args / result / traceback / 调用链） | ✅ | ✅ + 子任务表与时间线 |
| 任务控制（revoke / terminate / rate-limit / timeout） | ✅ | ✅ |
| 任务下发（apply / async-apply / send-task） | ✅ 仅 API | ✅ API + 可视化表单 |
| 任务结果与中止（result / abort） | ✅ | ✅ |
| Broker 队列长度 | ✅ | ✅ + 积压水位图 |
| Prometheus 指标 | ✅ | ✅ 指标名与标签完全一致 |
| 健康检查 | ✅ | ✅ |
| HTTP Basic 认证 | ✅ | ✅ Basic + JWT |
| 事件持久化 | ✅ | ✅ |
| 趋势图表 | ❌ | ✅ 吞吐 / 并发 / 耗时排行 |
| 实时事件流 | ❌ | ✅ |
| 演示模式（无 broker 可跑） | ❌ | ✅ 内置模拟集群 |
| 交互式 API 文档 | ❌ | ✅ Swagger / ReDoc |
| 运行时配置界面 | ❌ | ✅ 可编辑 + 自动落盘 |
| 多用户登录管理 | ❌ | ✅ 卡片式编辑器 |
| 内置主题系统 | ❌ | ✅ 暗色/亮色/自定义主题 |

---

## 快速开始

**先看访问地址**（最容易踩的坑）：

| 启动方式 | 浏览器打开 | 说明 |
| --- | --- | --- |
| `./manage.sh run` / `demo`、Docker、`celery -A celery_app flowerui` | **<http://127.0.0.1:5555/>** | 后端单端口同时托管 API 与构建好的前端，**不需要**另起前端 |
| `./manage.sh dev`（前后端分离热更新） | **<http://127.0.0.1:5556/>** | Vite 开发服务器；API 仍在 5555，由 Vite 代理转发 |

`0.0.0.0` 是**网卡绑定值**，不是访问地址，贴进浏览器会报 `ERR_ADDRESS_INVALID`；
`5556` 只有 dev 模式才有服务，其它方式访问 5556 会白屏 / 连接失败。
`--port` 改成多少，就访问 `http://127.0.0.1:<端口>/`。

### 方式一：演示模式（零依赖，推荐先跑这个）

无需 Redis / RabbitMQ，后端会启动内置模拟集群，生成 4 个 worker 与持续的任务事件流，
所有控制指令均可真实操作。

```bash
# 一键启动
./manage.sh demo

# 或手动启动（后端依赖统一用 uv sync，见 backend/README.md 第 3 节）
cd backend
uv sync                      # 首次 / 重装；升级用 uv sync --upgrade
FLOWER_MOCK=true FLOWER_MOCK_WORKERS=4 FLOWER_MOCK_SEED_TASKS=260 \
  .venv/Scripts/python -m uvicorn flowerui.main:app --host 0.0.0.0 --port 5555
```

打开 <http://127.0.0.1:5555> 即可。

### 方式二：连接真实 Celery 集群

```bash
# 启动 Redis（任选其一）
docker compose up -d redis          # 使用项目自带的 compose
# 或本地已安装：redis-server

# 启动后端（构建前端 + 单端口 5555 托管，访问 http://127.0.0.1:5555）
./manage.sh run

# 启动 Worker（另一个终端，前台监控，Ctrl+C 停止）
cd backend && ./manage.sh workers        # 或：python backend/start_workers.py start
```

> Worker 需要开启事件上报：`celery -A proj worker -E`
> 若 broker 不可达，服务会自动降级为演示模式并在页面顶部提示。

### 方式三：Docker Compose

```bash
# 一键启动（含 Redis）
docker compose up -d --build

# 查看日志
docker compose logs -f flowerui

# 停止
docker compose down
```

### 方式四：开发模式（前后端分离热更新）

```bash
./manage.sh dev
# 后端 API:   http://127.0.0.1:5555
# 前端页面:   http://127.0.0.1:5556（Vite 代理 /api 与 /ws 到后端）
```

### 方式五：用 Celery 命令启动（`flowerui` 子命令）

把 FlowerUI 注册成 Celery 子命令后，可以像原版 Flower 那样启动，并直接在命令行覆盖任意配置：

```bash
cd backend
uv sync                                              # 首次 / 重装依赖
.venv/Scripts/python.exe register_celery_command.py  # 一次性注册（幂等，可重复执行）
source .venv/Scripts/activate                       # Git Bash；让 celery 进入 PATH

celery -A celery_app flowerui --help
celery -A celery_app flowerui                       # 沿用 TOML / 环境变量配置
celery -A celery_app flowerui --port 5555 --broker-url redis://127.0.0.1:6379/0
celery -A celery_app flowerui --port 5555 --mock    # 演示模式：打开即有模拟数据
celery -A celery_app flowerui --mock --set max_tasks=200 debug=true
```

**启动后打开 <http://127.0.0.1:5555/>**（`--port` 改成 6001 就访问 6001）。
启动日志的 `页面地址` 行会给出可直接复制的 URL，`监听绑定` 行的 `0.0.0.0` 只是网卡绑定值，
不是访问地址，别把它贴进浏览器。此方式**只启动后端**，构建好的前端已由后端单端口托管，
无需另起 Vite；`5556` 仅在 `./manage.sh dev` 时才有服务，单独用本命令启动却访问 5556 会白屏。

> `celery -A celery_app flowerui --port 5555` 本身就是一条**完整可用**的启动命令（5555 是默认端口，
> 显式写出与不写等价），与 `./manage.sh` 并存、无需替换。若页面空白，先查浏览器地址，
> 不要怀疑命令：服务端可用 `curl -I http://127.0.0.1:5555/` 与 `/docs` 自检。

要点：

- **注册原理**：Celery 5.x 通过 `celery.commands` entry point 发现子命令。通过 wheel 安装时由 `[project.entry-points."celery.commands"]` 自动注册；从源码开发（未 `pip install -e .`）时，`register_celery_command.py` 往当前 venv 写最小 `.dist-info` + `.pth`，等价于一次 editable install，不联网、不改 `pyproject.toml` / `uv.lock`。**重建 venv 后需再执行一次注册**（可用 `--check` 检查、`--uninstall` 撤销）。
- **Git Bash 专用 shim**：uv 0.12.3 在 Windows + Python 3.7 下生成的 `celery.exe` 会把自身当 Python 源码执行（报 `SyntaxError: Non-UTF-8 code`）。注册脚本会在 `.venv/Scripts/` 放一个无扩展名 `celery` 包装脚本绕过它；PowerShell / CMD 请改用 `.venv/Scripts/python.exe -m celery ...`。
- **参数优先级**：命令行显式参数 > 用户 `celery_app.conf` 继承项 > `flowerui.runtime.toml` 回放 > `FLOWER_*` 环境变量 > `flowerui-settings.toml` > 代码默认值。命令行参数只对本次进程生效，不落盘。
- **任意配置项**：`--set KEY=VALUE`（可重复）或直接写位置参数 `KEY=VALUE`；键名用 `--list-keys` 查看。常用项另有专用参数：`--host` / `--port` / `--broker-url` / `--result-backend` / `--broker-transport-options` / `--mock` / `--debug` / `--basic-auth` / `--url-prefix` / `--runtime-config` / `--reload` / `--workers` / `--log-level`。
- **预览不启动**：`--dry-run` 会回放运行时配置后打印生效值，用于确认参数优先级；全局 `-A` / `-b` 等 Celery 选项必须写在子命令 `flowerui` **之前**（`-b` 的值会自动作为 broker URL）。
- **自动复用用户 app.conf**：`celery -A their_project.celery:app flowerui` 会自动从加载到的 app 继承 `broker_url` / `result_backend` / `broker_transport_options` / `task_default_queue` / `task_routes`（仅取显式设置项，不会用 Celery 默认值去盖掉你用 `--broker-url`、TOML 或环境变量配的值）；dry-run 会打印 `复用 app.conf` 行确认。独立命令用 `flowerui -A their_project.celery:app` 同样生效。
- 这种方式与 `./manage.sh` 完全并存，适合在已有 Celery 工作流中直接用 `celery -A <app> flowerui` 拉起监控面板。

### 页面空白 / 打不开？按这个顺序排查

| 现象 | 原因 / 处理 |
| --- | --- |
| 打开 `http://0.0.0.0:5555` 白屏或 `ERR_ADDRESS_INVALID` | `0.0.0.0` 只是绑定值；改用 **<http://127.0.0.1:5555/>**。启动日志的 `页面地址` 行给的是可直接复制的 URL，`监听绑定` 行不是 |
| 打开 `http://127.0.0.1:5556` 白屏 / 连接失败 | 5556 只在 `./manage.sh dev` 时由 Vite 提供；其余启动方式一律访问 5555 |
| 侧边栏在，但 Worker / 任务全是 0、图表空 | 连的是真实 broker 但没有 Worker 与任务，属**正常空数据**；用 `./manage.sh demo` 或加 `--mock` 查看演示集群 |
| 打开后只有一段 JSON（`前端未构建`） | `backend/flowerui/static/` 没有产物；执行 `./manage.sh build` 构建并同步 |
| 仍是纯白屏 | `Ctrl+F5` 强刷或开无痕窗口排除旧缓存；再看 F12 Console 的报错。浏览器扩展 / 系统代理也可能拦截静态资源 |

服务端自检（两条都应为 `200`，`/docs` 能打开也说明后端健康）：

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5555/
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5555/api/config
```

> 注意：系统代理环境下 `curl http://0.0.0.0:5555/` 可能返回 `502`，这不代表服务异常，
> 只说明该地址不该被当成访问目标。

### 方式六：pip 安装到已有 Celery 项目（发布形态）

`backend/` 已按 PyPI 分发名 **`flowerui`** 打包，`requires-python = ">=3.7"`；前端产物与内置主题
随 wheel 分发，用户机器不需要 Node.js。

```bash
# 构建（项目根执行；产物写到自定义目录，避免污染仓库）
uv build --project backend --out-dir D:/Temp/flowerui-dist

# 在目标项目环境安装
pip install D:/Temp/flowerui-dist/flowerui-0.1.0-py3-none-any.whl

# 三种入口任选其一（-A 写在子命令之前）
celery -A their_project.celery:app flowerui --port 5555
flowerui --port 5555
python -m flowerui --port 5555
```

访问 **<http://127.0.0.1:5555/>**。`celery --help` 能列出 `flowerui` 即说明 entry point 生效。

> **当前限制（0.1.0）**
> - 依赖仍锁 `pydantic<2`（配置层用 v1 的 `BaseSettings`），装进 pydantic v2 项目会降级对方依赖；
>   去 pydantic 化完成前建议先发 TestPyPI，不要直接发正式版。
> - **配置文件与主题已采用「项目目录优先、包内兜底」的分层模型**（见下），pip 模式下
>   界面保存的配置、上传的主题都落在你执行命令的目录（`flowerui.runtime.toml`、`themes/`），
>   不写入只读的 site-packages；项目目录没有同名配置/主题时，自动回退到包内置的默认值与主题。
>   仅「重启系统」按钮在 pip 模式下没有等效实现（它依赖运行目录的 `manage.sh`，源码模式才有）。
> - 已实测：干净 **Python 3.7.9** venv 安装并启动成功，页面、接口与静态资源全部 200，
>   无头浏览器渲染正常；Python 3.9+ 与 pydantic v2 环境尚未验证。
> - **已支持**：`celery -A their_project.celery:app flowerui` 自动从用户 app.conf 继承
>   broker / result backend / transport options / 默认队列 / 路由，无需重复配置连接信息。

完整改造方案、文件级清单与发布流程见 [`docs/pypi-release-plan.md`](docs/pypi-release-plan.md)。

---

## 后端依赖管理（uv）

**约定：升级 / 重装后端依赖统一使用 `uv sync`，不要手动改版本号或 `pip install`。**

```bash
cd backend
uv sync                          # 首次安装 / 按 uv.lock 精确还原
uv sync --upgrade                # 升级全部依赖到 Python 3.7 下的最新兼容版
uv sync --upgrade-package celery # 只升级某一个包
uv add <包名>                    # 新增依赖（自动改 pyproject.toml + uv.lock）
```

| 文件 | 角色 |
|---|---|
| `backend/pyproject.toml` | **依赖声明源**：不锁版本，只保留 `pydantic<2`、`importlib-metadata<5` 两个必要上界 |
| `backend/uv.lock` | **版本锁定**：由 uv 生成，必须随代码提交 |
| `backend/.python-version` | 钉死 **3.7**，防止 `uv sync` 误挑更高版本重建 `.venv` |
| `backend/requirements.txt` | 仅用于无 uv 的环境 / Docker 构建，非权威来源 |

也可以统一走管理脚本（命令更短，且会先做环境体检）：

```bash
./manage.sh deps                        # = cd backend && uv sync
./manage.sh upgrade                     # = uv sync --upgrade
./manage.sh deps --upgrade-package celery
./manage.sh deps --add <包名>            # = uv add <包名>
./manage.sh deps --check                 # 只读体检：版本清单 + 两个必要上界
```

环境为 `backend/.venv`（Python 3.7.9）。项目根目录的 `.venv` 是早期的 Python 3.9 环境，**不要使用**；
依赖相关操作请一律在 `backend/` 下执行。
详细版本约束的理由见 [`backend/README.md` 第 3 节](backend/README.md)。

---

## 服务管理（manage.sh）

项目采用**三层**管理脚本，职责清晰、互不越界：

- **根 `./manage.sh`（编排层）**：只做调度，不含具体启停逻辑。
  - `dev` / `restart` → 同时拉起后端（`backend/manage.sh dev`）与前端（`frontend/manage.sh dev`）
  - `run` / `demo` → 先 `frontend/manage.sh build` 同步前端产物，再 `backend/manage.sh run|demo` 单端口托管
  - `build` → 仅 `frontend/manage.sh build`
  - `stop` → 先后端、再前端 `stop`
  - `clean` → 清理 `backend/logs`、`frontend/logs` 下全部历史日志（前后端 + worker，保留 PID）
  - `status` → 前后端状态 + 后端环境 / 配置摘要
  - `workers [N=4]` → 转发到 `backend/manage.sh workers`（前台监控，Ctrl+C 停止）
  - `deps` / `upgrade` / `config` → 转发到 `backend/manage.sh`（依赖同步 / 配置体检）
  - `pack <项目路径> [输出]` → 按目标项目下的 `.gitignore` 排除后打包（见下）
- **`backend/manage.sh`**：仅管后端（5555），含 `deps` / `upgrade` / `config` / `workers`，详见 [`backend/README.md`](backend/README.md)。
- **`frontend/manage.sh`**：仅管前端（5556 与构建同步），详见 [`frontend/README.md`](frontend/README.md)。

> **唯一入口**：根目录曾有的 `dev-restart.ps1`、`start_worker.bat`、`start_worker.sh`、`run.py` 已删除，
> 启停、依赖、worker 管理、配置体检全部通过三份 `manage.sh`；旧 `.env` 配置也已迁到 TOML。

### 打包项目（pack）

按指定项目下的 `.gitignore` 排除无关文件，打包为 `.tar.gz`，便于分发或部署：

```bash
# 打包后端（自动排除 .venv / __pycache__ / 运行时产物等）
./manage.sh pack ./backend

# 自定义输出路径
./manage.sh pack ./frontend out/frontend.tar.gz
```

要点：

- **排除规则来源**：优先用 git 精确解析项目内 `.gitignore`（`git ls-files --ignored --exclude-standard --others --directory`），含通配符 / 注释 / 取反规则；项目不在 git 仓库内时回退为直接读取 `.gitignore`；始终排除 `.git`。
- **输出位置**：默认放在「项目父目录 / 项目名.tar.gz」，避免压缩包落入被打包目录造成自包含。
- **典型体积**：`backend` 约 940K（排除 `.venv` 等）、`frontend` 约 920K（排除 `node_modules`/`dist` 等）。

> 注意：Windows 下请用 Git Bash 运行（如 `bash manage.sh pack ./backend`）。

---

## 目录结构

```
flowerui-fastapi/
├── backend/
│   ├── flowerui/
│   │   ├── main.py                 # 应用装配、静态托管、生命周期
│   │   ├── cli.py                  # celery flowerui 子命令 / 独立命令入口
│   │   ├── __main__.py             # python -m flowerui
│   │   ├── core/
│   │   │   ├── config.py           # pydantic v1 BaseSettings + TOML 加载
│   │   │   ├── celery_app.py       # Celery 实例与 broker 探测（哨兵感知）
│   │   │   └── security.py         # Basic / JWT 鉴权
│   │   ├── services/
│   │   │   ├── manager.py          # ServiceManager 聚合入口
│   │   │   ├── state.py            # EventsState 内存状态机
│   │   │   ├── events.py           # 事件采集线程
│   │   │   ├── inspector.py        # Inspect 探针
│   │   │   ├── broker.py           # Redis / RabbitMQ / Sentinel 队列查询
│   │   │   ├── search.py           # 任务搜索 DSL
│   │   │   ├── task_filter.py      # 过滤 / 排序 / 序列化
│   │   │   ├── metrics.py          # Prometheus 指标
│   │   │   ├── hub.py              # WebSocket 扇出
│   │   │   ├── mock.py             # 演示模式模拟集群
│   │   │   ├── restart.py          # 系统重启（调用 manage.sh）
│   │   │   └── runtime_config.py   # 运行时配置管理
│   │   ├── api/routers/
│   │   │   ├── auth.py workers.py control.py tasks.py
│   │   │   ├── broker.py dashboard.py monitor.py ws.py config.py system.py
│   │   │   └── themes.py           # 主题上传/删除 API
│   │   ├── static/                 # 前端构建产物（由 frontend/manage.sh build 同步）
│   │   └── themes/                 # 主题 CSS（目录即真理，上传落此；build 只补齐内置主题）
│   ├── tests/                      # 功能 / E2E / 冒烟自测
│   ├── docs/                       # 后端文档用 SVG 图
│   ├── manage.sh                  # 后端脚本（dev/run/demo/stop/status/workers/deps/upgrade/config）
│   ├── start_workers.py           # Worker 批量启动 + 前台监控
│   ├── send_tasks.py              # 随机发送测试任务
│   ├── _broker_env.py             # 解析运行时配置（TOML 优先，兼容旧 .env）
│   ├── requirements.txt
│   ├── pyproject.toml             # 依赖清单（含 uv 镜像源）
│   ├── flowerui-settings.toml     # 静态默认配置（扁平 TOML，可提交）
│   ├── flowerui.runtime.toml      # 运行时覆盖配置（界面改 → 落盘，自动生成）
│   ├── uv.lock                    # 依赖版本锁定（uv sync 按此还原）
│   └── .python-version            # 钉死 Python 3.7
├── frontend/
│   ├── src/
│   │   ├── api/                    # axios 封装 + WebSocket 客户端
│   │   ├── stores/                 # Pinia 状态管理
│   │   ├── composables/            # 组合式函数
│   │   ├── layouts/AppLayout.vue   # 主布局
│   │   ├── components/             # 通用组件
│   │   ├── views/                  # 10 个页面
│   │   ├── styles/                 # 全局样式
│   │   └── theme/                  # 主题变量
│   ├── vite.config.js
│   ├── package.json
│   ├── dist/                       # 构建产物（已 gitignore）
│   └── README.md                   # 前端专属说明（见 frontend/README.md）
├── examples/
│   ├── tasks.py                    # 示例任务定义
│   └── seed_tasks.py              # 种子任务脚本
├── themes/                         # 内置主题素材（非运行时真理源）
│   ├── base.css                    # 共享变量，其它主题 @import
│   ├── _template.css               # 新主题模板
│   └── *.css                       # 各内置主题；界面上传的落 backend/flowerui/themes/
├── Dockerfile
├── docker-compose.yml
├── manage.sh                      # 统一入口（编排层）：dev/restart/run/demo/build/stop/clean/status/workers/deps/upgrade/config/pack
└── README.md
```

---

## 配置说明

### 配置文件（TOML）与环境变量

配置项以 **TOML 文件**为主，环境变量（前缀 `FLOWER_`）只作临时覆盖：

| 文件 | 作用 |
|---|---|
| `backend/flowerui-settings.toml` | 静态默认配置，扁平 `KEY = VALUE`（**不要分节**），随代码提交 |
| `backend/flowerui.runtime.toml` | 界面修改后自动落盘，**重启后端生效**；`result_backend` 非必须，未启用时保持注释 |

优先级：**TOML 文件 → `FLOWER_*` 环境变量 → 代码默认值**。`result_backend` 不配时只写注释行，
不要写 `= ""`（Celery 会当成「已配置但为空」并抛 `NotImplementedError: No result backend is configured`）。

排查配置用 `./manage.sh config`（体检两个 TOML、分节误用、环境变量覆盖与生效值）；
服务运行时用 `./manage.sh status` 读 `/api/system` 查看真正生效值。
完整字段清单见 `backend/flowerui-settings.toml` 与界面「配置」页。

常用环境变量：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FLOWER_BROKER_URL` | `redis://127.0.0.1:6379/0` | Broker 地址，支持 `redis://` / `rediss://` / `redis+socket://` / `sentinel://` |
| `FLOWER_BROKER_TRANSPORT_OPTIONS` | `{}` | Broker 传输选项（JSON）。**哨兵模式必填** `master_name`，见下方专节 |
| `FLOWER_RESULT_BACKEND` | 空 | 结果后端，用于查询任务结果 |
| `FLOWER_BROKER_API` | 空 | RabbitMQ Management API，查询队列长度用 |
| `FLOWER_MAX_TASKS` | `100000` | 内存保留任务上限 |
| `FLOWER_MAX_WORKERS` | `5000` | 内存保留 worker 数上限 |
| `FLOWER_INSPECT_TIMEOUT` | `3000` | Inspect 超时（毫秒） |
| `FLOWER_PERSISTENT` | `false` | 事件状态持久化 |
| `FLOWER_BASIC_AUTH` | 空 | `["user:pass"]`，留空不鉴权 |
| `FLOWER_SECRET_KEY` | 随机 | JWT 签名密钥，生产必改 |
| `FLOWER_MOCK` | `false` | 强制演示模式 |

开启鉴权示例：

```bash
FLOWER_BASIC_AUTH='["admin:admin123", "user:password"]' \
FLOWER_SECRET_KEY=your-secret-key \
python -m uvicorn flowerui.main:app --port 5555
```

### 运行时配置

FlowerUI 支持通过界面修改运行时配置，改动自动落盘到 `flowerui.runtime.toml` 文件（TOML 格式）。

配置文件位置：`backend/flowerui.runtime.toml`（可用 `FLOWER_RUNTIME_CONFIG_FILE` 环境变量覆盖）

**配置类型标记**

| 标记 | 含义 |
|------|------|
| 🔒 敏感 | 密码/密钥，界面脱敏显示 |
| 🔄 需重启 | 修改后需点「重启系统」生效 |
| ⚠️ 待完善 | 功能未完全实现，仅供参考 |

### Redis 哨兵（Sentinel）模式

FlowerUI 完整支持 Redis 哨兵高可用集群，**监控端与 worker 端都必须配置**（仅配一端会启动失败或无法监控）。

> 下列地址、端口、密码与 `master_name` **均为示例占位**，请按实际环境替换；切勿把真实连接信息写进文档或提交到仓库。

```bash
# 1) Broker URL：多个哨兵节点用 ; 分隔，每个节点都要带 sentinel:// scheme
#    db 写在任意一段的路径上（如下单的 /0）；master 密码写在用户信息段
FLOWER_BROKER_URL="sentinel://:YOUR_PASSWORD@sentinel1.example.com:26379;sentinel://sentinel2.example.com:26379;sentinel://sentinel3.example.com:26379/0"

# 2) 传输选项：master_name 必填，缺失时启动会显式报错并拒绝静默降级演示模式
FLOWER_BROKER_TRANSPORT_OPTIONS='{"master_name": "mymaster"}'

# 3) 结果后端若同样走哨兵，URL 形态相同，db 建议与 broker 区分（如 /1）
FLOWER_RESULT_BACKEND="sentinel://sentinel1.example.com:26379;sentinel://sentinel2.example.com:26379;sentinel://sentinel3.example.com:26379/1"
```

哨兵节点自身需要密码时：`FLOWER_BROKER_TRANSPORT_OPTIONS='{"master_name": "mymaster", "sentinel_kwargs": {"password": "YOUR_PASSWORD"}}'`

**Worker 端**（`examples/tasks.py`（项目根）已内置同样读取逻辑）：启动 worker 时导出同样的三个环境变量即可，例如

```bash
FLOWER_BROKER_URL='sentinel://:YOUR_PASSWORD@127.0.0.1:26379;sentinel://127.0.0.1:26380;sentinel://127.0.0.1:26381/0' \
FLOWER_RESULT_BACKEND='sentinel://:YOUR_PASSWORD@127.0.0.1:26379;sentinel://127.0.0.1:26380;sentinel://127.0.0.1:26381/1' \
FLOWER_BROKER_TRANSPORT_OPTIONS='{"master_name": "mymaster"}' \
python backend/start_workers.py start 4
```

**切回单机模式**：把 `FLOWER_BROKER_URL` 改回 `redis://:YOUR_PASSWORD@127.0.0.1:6379/0`、删掉 `FLOWER_BROKER_TRANSPORT_OPTIONS` 即可，其余不变。两种模式可在 `flowerui.runtime.toml` 中随时切换（重启生效）。

---

## API 参考

启动后访问 <http://127.0.0.1:5555/docs> 查看交互式 Swagger 文档。

### 查询接口

```
GET  /api/workers                       全部 worker 快照
GET  /api/workers/table                 表格聚合数据
GET  /api/worker/{name}                 worker 详情
GET  /api/tasks                         任务映射（对齐 flower）
GET  /api/tasks/table                   分页 + 搜索
GET  /api/task/info/{id}                任务详情 + 子任务
GET  /api/task/types                    任务类型
GET  /api/task/registered               已注册任务
GET  /api/queues/length                 队列长度
GET  /api/broker                        Broker 概览
GET  /api/dashboard/summary|timeline|filters|task-distribution
GET  /api/system                        运行环境
GET  /api/config/ui                     UI 默认值（免鉴权）
GET  /api/config                        全量配置
GET  /api/themes                        主题列表
```

### 控制接口

```
POST /api/worker/shutdown/{name}
POST /api/worker/pool/restart|grow|shrink|autoscale/{name}
POST /api/worker/queue/add-consumer|cancel-consumer/{name}?queue=
POST /api/task/revoke/{id}?terminate=&signal=
POST /api/task/abort/{id}
POST /api/task/rate-limit/{taskname}?workername=&ratelimit=
POST /api/task/timeout/{taskname}?workername=&soft=&hard=
POST /api/task/apply|async-apply|send-task/{taskname}
GET  /api/task/result/{id}?timeout=
```

### 配置接口

```
PUT  /api/config                        更新配置
POST /api/config/reset                  恢复启动值
POST /api/config/materialize            生成完整 .env 模板
POST /api/system/restart                重启后端进程
```

### 主题接口

```
POST /api/themes                        上传主题（multipart）
DELETE /api/themes/{id}                 删除主题
GET  /api/themes/files/{id}.css         下载主题文件
```

### 运维接口

```
GET  /metrics          Prometheus 指标
GET  /healthcheck      健康检查
WS   /ws/events        实时推送（snapshot / summary / timeline / event）
```

### 任务搜索 DSL

任务列表的搜索框支持与 flower 一致的语法：

```
result:success              结果内容包含 success
args:user_id                位置参数包含 user_id
kwargs:template=welcome     关键字参数匹配
state:FAILURE               状态匹配
任意文本                     匹配任务 ID 或任务名
```

多个条件用空格分隔，取交集。

---

## Prometheus 指标

指标名称、标签与 flower 2.0.1 保持一致，可直接复用既有的 Grafana 面板：

```
flower_events_total{worker,type,task}
flower_task_runtime_seconds{worker,task}                 # Histogram
flower_task_prefetch_time_seconds{worker,task}
flower_worker_prefetched_tasks{worker,task}
flower_worker_online{worker}
flower_worker_number_of_currently_executing_tasks{worker}
```

耗时分桶可通过 `FLOWER_TASK_RUNTIME_METRIC_BUCKETS` 环境变量调整。

---

## 演示模式说明

当 `FLOWER_MOCK=true` 或 broker 探测失败时启用。`MockCluster` 会：

- 创建 4 个 worker（可配置 `FLOWER_MOCK_WORKERS`）
- 预热历史任务数据与队列水位
- 持续产生 8 类任务的完整事件流，包含成功、失败（带 traceback）、重试、撤销
- 真实响应所有控制指令：扩缩容会改变 `max-concurrency`，
  添加队列会出现在 `active_queues`，撤销任务会改变任务状态

因此演示模式下看到的每一个数字、每一次操作都走完整的生产代码路径，不是静态假数据。

---

## 与原版的行为差异

| 差异点 | Flower 2.0.1 | FlowerUI |
|--------|--------------|----------|
| 实时性 | 前端定时轮询 | WebSocket 主动推送 + 5 秒轮询兜底 |
| 分页 | DataTables 前端分页 | 服务端分页，支持大数据量 |
| 鉴权 | HTTP Basic + OAuth2 | Basic + JWT，支持多用户管理 |
| 部署 | 单体 Tornado 应用 | 前后端分离，支持反向代理 |
| 配置 | 命令行参数 | 环境变量 + 运行时界面配置 |
| 主题 | 固定样式 | 暗色/亮色/自定义主题系统 |
| 演示 | 无 | 内置模拟集群，零依赖运行 |

---

## 开发指南

### 前端开发

```bash
cd frontend
npm install
npm run dev
# 访问 http://127.0.0.1:5556
```

### 后端开发

```bash
cd backend
python -m uvicorn flowerui.main:app --reload --port 5555
```

### 一键开发

```bash
./manage.sh dev
# 后端: http://127.0.0.1:5555（API）
# 前端: http://127.0.0.1:5556（Vite HMR）
```

---

## 测试

### 后端功能自测

`backend/tests/functional_check.py` 覆盖界面上每个可点击动作背后的接口，针对运行中的服务做端到端校验。

```bash
# 1) 启动服务（演示模式，零依赖）
./manage.sh demo
#   或：FLOWER_MOCK=true .venv/Scripts/python -m uvicorn flowerui.main:app --port 5555

# 2) 另开终端运行测试
cd backend
.venv/Scripts/python tests/functional_check.py http://127.0.0.1:5555
```

测试项包含：系统/认证、仪表盘、Worker 列表与详情、任务下发与查询、任务控制
（revoke / terminate / rate-limit / timeout）、Worker 池与队列控制、Broker / 队列长度、
运行时配置接口、主题接口、系统重启接口等，全部通过即代表核心链路健康。

> 已知约定：
> - 认证**未启用**时，`/api/auth/login` 对任意凭据均返回 200（生成匿名 token），
>   测试会将其标记为预期失败，属正常行为。
> - `POST /api/system/restart` 会调用 `manage.sh restart`（先停后起，开发模式）。
>   测试脚本在重启后重连原地址，故该用例需在默认端口 5555 上运行才能验证服务恢复。

### 前端构建校验

```bash
cd frontend
npm install
npm run build        # 产物输出到 frontend/dist
```

---

## 许可证

MIT License

---

## 致谢

- [mher/flower](https://github.com/mher/flower) - 原版 Flower 项目
- [FastAPI](https://fastapi.tiangolo.com/) - 现代 Web 框架
- [Vue 3](https://vuejs.org/) - 渐进式前端框架
- [Element Plus](https://element-plus.org/) - Vue 3 UI 组件库
