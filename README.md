# FlowerUI

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
| HTTP Basic 认证 | ✅ | ✅ JWT Bearer（默认）+ Basic（过渡期） |
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

### 方式一：演示模式（零依赖，推荐先跑这个）

无需 Redis / RabbitMQ，后端会启动内置模拟集群，生成 4 个 worker 与持续的任务事件流，
所有控制指令均可真实操作。

```bash
# 一键启动
./manage.sh demo

# 或手动启动
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements.txt  # Linux/macOS: .venv/bin/pip
cd backend && FLOWER_MOCK=true FLOWER_MOCK_WORKERS=4 FLOWER_MOCK_SEED_TASKS=260 \
  python -m uvicorn app.main:app --host 0.0.0.0 --port 5555
```

打开 <http://127.0.0.1:5555> 即可。

### 方式二：连接真实 Celery 集群

```bash
# 启动 Redis（任选其一）
docker compose up -d redis          # 使用项目自带的 compose
# 或本地已安装：redis-server

# 启动后端（构建前端 + 单端口 5555 托管，访问 http://127.0.0.1:5555）
./manage.sh run

# 启动 Worker（另一个终端）
./start_worker.sh
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

---

## 目录结构

```
flowerui-fastapi/
├── backend/
│   ├── app/
│   │   ├── main.py                 # 应用装配、静态托管、生命周期
│   │   ├── core/
│   │   │   ├── config.py           # pydantic-settings，字段对齐 flower CLI
│   │   │   ├── celery_app.py       # Celery 实例与 broker 探测
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
│   │   │   └── runtime_config.py   # 运行时配置管理
│   │   └── api/routers/
│   │       ├── auth.py workers.py control.py tasks.py
│   │       ├── broker.py dashboard.py monitor.py ws.py config.py system.py
│   │       └── themes.py           # 主题上传/删除 API
│   ├── tests/
│   ├── requirements.txt
│   └── flowerui.runtime.env        # 运行时配置（自动生成）
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
│   └── dist/                       # 构建产物
├── examples/
│   ├── tasks.py                    # 示例任务定义
│   └── seed_tasks.py              # 种子任务脚本
├── themes/                         # 用户自定义主题
│   ├── base.css                    # 主题基础变量
│   ├── dark.css / light.css        # 内置主题
│   └── *.css                       # 用户上传主题
├── Dockerfile
├── docker-compose.yml
├── manage.sh                      # 服务管理脚本（dev/restart/run/build/stop/demo）
├── start_worker.sh / start_worker.bat        # 启动真实 Celery worker
├── .env.example                    # 环境变量示例
└── README.md
```

---

## 配置说明

### 环境变量

所有配置项通过环境变量（前缀 `FLOWER_`）提供，完整清单见 [`.env.example`](.env.example)。

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FLOWER_BROKER_URL` | `redis://localhost:6379/0` | Broker 地址 |
| `FLOWER_RESULT_BACKEND` | 空 | 结果后端，用于查询任务结果 |
| `FLOWER_BROKER_API` | 空 | RabbitMQ Management API，查询队列长度用 |
| `FLOWER_MAX_TASKS` | `100000` | 内存保留任务上限 |
| `FLOWER_MAX_WORKERS` | `5000` | 内存保留 worker 数上限 |
| `FLOWER_INSPECT_TIMEOUT` | `3000` | Inspect 超时（毫秒） |
| `FLOWER_PERSISTENT` | `false` | 事件状态持久化 |
| `FLOWER_BASIC_AUTH` | 空 | `["user:pass"]`，留空不鉴权 |
| `FLOWER_SECRET_KEY` | 随机 | JWT 签名密钥，生产必改 |
| `FLOWER_MOCK` | `false` | 强制演示模式 |
| `legacy_basic_auth_enabled` | `false` | 过渡期兼容模式，保留Basic Auth 2周 |

开启鉴权示例：

登录示例：

```bash
# 登录获取 JWT token
curl -X POST http://127.0.0.1:5555/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your-password"}'
```

使用 token 访问 API：

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:5555/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your-password"}' | jq -r '.access_token')

curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:5555/api/workers
```

```bash
FLOWER_BASIC_AUTH='["admin:admin123", "user:password"]' \
FLOWER_SECRET_KEY=your-secret-key \
python -m uvicorn app.main:app --port 5555
```


### 运行时配置

FlowerUI 支持通过界面修改运行时配置，改动自动落盘到 `flowerui.runtime.env` 文件。

配置文件位置：项目根目录 `flowerui.runtime.env`（可用 `FLOWER_RUNTIME_CONFIG_FILE` 环境变量覆盖）

**配置类型标记**

| 标记 | 含义 |
|------|------|
| 🔒 敏感 | 密码/密钥，界面脱敏显示 |
| 🔄 需重启 | 修改后需点「重启系统」生效 |
| ⚠️ 待完善 | 功能未完全实现，仅供参考 |

---

## API 参考

启动后访问 <http://127.0.0.1:5555/docs> 查看交互式 Swagger 文档。

```
POST /api/auth/login                    登录获取JWT token
GET  /api/auth/config                   认证配置（是否启用JWT/Basic）
GET  /api/auth/lockout/status           查询登录限流状态
POST /api/auth/logout                   注销（返回消息）
POST /api/auth/password/change          修改密码（需Bearer token）
GET  /api/auth/sessions                 查看当前会话
DELETE /api/auth/sessions/{jti}          撤销指定会话
GET  /api/auth/login-logs               查看登录日志
```
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
python -m uvicorn app.main:app --reload --port 5555
```

### 一键开发

```bash
./manage.sh dev
# 后端: http://127.0.0.1:5555（API）
# 前端: http://127.0.0.1:5556（Vite HMR）
```

---

## 测试

### 后端功能测试（pytest，离线自动运行）

`backend/tests/` 为 pytest 套件，基于内置演示集群（`FLOWER_MOCK=true`）**无需 Redis / Celery worker**。
全部状态文件重定向到临时目录、重启脚本替换为无害 dummy 脚本，可安全重复运行：

```bash
cd backend
.venv/Scripts/pip install -r requirements-dev.txt   # 含 pytest
.venv/Scripts/python -m pytest                      # 62 个用例，秒级完成
```

| 模块 | 覆盖范围 |
|------|---------|
| `test_01_boot.py` | 健康检查、系统信息、OpenAPI/文档、静态资源、Prometheus 指标 |
| `test_02_auth_users.py` | 登录/JWT/登录日志、用户与角色 CRUD、RBAC 权限边界（admin/operator/viewer） |
| `test_03_config.py` | 配置查看/修改/校验、secret 脱敏、备份回滚、materialize、审计联动 |
| `test_04_control.py` | Worker 列表/详情、进程池扩缩容/自动伸缩/重启、队列消费、Broker |
| `test_05_tasks.py` | 任务下发（同步/异步/按名/重试/撤销/中止）、过滤/排序/搜索/分页 |
| `test_06_ws.py` | WebSocket 鉴权、首屏快照、心跳（双协议兼容） |
| `test_07_system_misc.py` | 重启状态机（pending/in_progress/failed/success/timeout）、仪表盘、主题、告警、Beat、初始化 |

### 真实服务端到端自测（可选）

`backend/tests/live/live_e2e.py` 对**已启动的服务**发起真实 HTTP / WebSocket 请求，覆盖与界面一致的全部核心链路
（solo 池自动跳过弹性伸缩、未配置 result backend 时自动跳过同步 apply）：

```bash
# 1) 启动服务（演示模式，零依赖）
./manage.sh demo
#   或：FLOWER_MOCK=true .venv/Scripts/python -m uvicorn app.main:app --port 5555

# 2) 另开终端运行（默认 admin/admin123，可用 --user/--password 覆盖）
cd backend
.venv/Scripts/python tests/live/live_e2e.py http://127.0.0.1:5555
```

`tests/live/` 下另有面向真实集群的诊断脚本：`diag_redis_connection.py`（Redis 连接/线程池）、
`diag_events_flow.py`（Celery 事件流），仅在接入真实 broker 时按需运行。

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
