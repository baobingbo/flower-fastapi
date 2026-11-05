# FlowerUI 功能差距分析报告

> 分析对象：flowerui-fastapi（FastAPI + Vue 3 + Element Plus 的 Celery 实时监控与管理平台）
> 分析视角：对照 Celery 监控平台完整能力集 + 原版 Flower 2.0.1（`.reference/flower-2.0.1`）+ README 声明能力，逐项核实代码实现
> 分析日期：2026-08-22 · 分析人：feature-analyst

---

## 目录

- [一、分析方法与已核实能力清单](#一分析方法与已核实能力清单)
- [二、功能差距总览表](#二功能差距总览表)
- [三、差距项详细分析](#三差距项详细分析)
  - [P0-1 告警与通知系统（缺失）](#p0-1-告警与通知系统缺失)
  - [P0-2 数据保留、长期趋势与历史查询（部分）](#p0-2-数据保留长期趋势与历史查询部分)
  - [P0-3 角色权限（RBAC）与操作审计日志（缺失）](#p0-3-角色权限rbac与操作审计日志缺失)
  - [P0-4 任务一键重试/重发（缺失）](#p0-4-任务一键重试重发缺失)
  - [P0-5 任务列表/数据导出 CSV·JSON（缺失）](#p0-5-任务列表数据导出-csvjson缺失)
  - [P1-1 国际化 i18n（缺失）](#p1-1-国际化-i18n缺失)
  - [P1-2 任务依赖 DAG 可视化（部分）](#p1-2-任务依赖-dag-可视化部分)
  - [P1-3 定时任务（Beat/Crontab）管理（缺失）](#p1-3-定时任务beatcrontab管理缺失)
  - [P1-4 OAuth2 单点登录（缺失，相对 Flower 2.0.1 的回退）](#p1-4-oauth2-单点登录缺失相对-flower-201-的回退)
  - [P1-5 多 Broker/多集群集中监控（缺失）](#p1-5-多-brokermulti集群集中监控缺失)
  - [P1-6 外部系统集成：入站 Webhook 与 API Key（缺失）](#p1-6-外部系统集成入站-webhook-与-api-key缺失)
  - [P2-1 浏览器通知与移动端适配/PWA（缺失）](#p2-1-浏览器通知与移动端适配pwa缺失)
  - [P2-2 健康检查深度（部分）](#p2-2-健康检查深度部分)
  - [P2-3 result_backend 等关键连接项不可在界面配置（部分）](#p2-3-result_backend-等关键连接项不可在界面配置部分)
  - [P2-4 测试体系与 CI（部分）](#p2-4-测试体系与-ci部分)
  - [P2-5 收藏/书签（缺失）](#p2-5-收藏书签缺失)
- [四、建议路线图](#四建议路线图)
- [五、工作量汇总](#五工作量汇总)

---

## 一、分析方法与已核实能力清单

### 1.1 分析方法

1. 通读 `README.md` 的功能对照表与 API 参考；
2. 逐文件审阅后端全部 11 个路由（`backend/app/api/routers/`）、14 个服务（`backend/app/services/`）、3 个核心模块（`backend/app/core/`），以及前端全部 11 个视图、API 层、Pinia store；
3. 对照 `.reference/flower-2.0.1`（原版 flower 源码）的 `options.py` / `urls.py` / `views/` 核实"功能全量对齐"声明；
4. 检查 `backend/tests/`、`package.json`、样式与组件代码，核实 i18n、通知、导出、移动端等横切能力。

### 1.2 已核实为"真实实现"的能力（README 声明与代码一致）

| 能力 | 证据 |
| --- | --- |
| Worker 实时监控（WS + 轮询双通道） | `ws.py` 双端点；`stores/app.js` 双实现可切换；`dashboard/snapshot` 带事件游标 |
| Worker 详情（Pool/队列/Config/Rusage） | `workers.py get_worker` 聚合 8 类 inspect 数据；`WorkerDetailView.vue` |
| 进程池控制 restart/grow/shrink/autoscale | `control.py` + `manager.py`（含 solo 池无回执的 inspect 复核兜底） |
| 队列消费 add/cancel consumer | `control.py` + `manager._confirm_consumer` |
| 任务列表：服务端分页 + 搜索 DSL + 排序 + 时间范围过滤 | `tasks.py` + `search.py`（result:/args:/kwargs:/state: 语法与 flower 一致） |
| 任务详情：args/result/traceback/调用链/子任务/时间线 | `tasks.py task_info` 附带 `children_tasks`；`TaskDetailView.vue` |
| 任务控制：revoke/terminate/rate-limit/timeout/abort | `control.py` + `tasks.py task_abort` |
| 任务下发：apply / async-apply / send-task + 可视化表单 + 任务↔队列预填 | `tasks.py` ApplyPayload；`ApplyTaskView.vue`；`task_routes` 路由表 |
| 任务结果查询（依赖 result backend） | `tasks.py task_result`；未配置时显式 503 并在系统页暴露原因 |
| Broker 队列长度（Redis/Rediss/Sentinel/Socket/RabbitMQ） | `services/broker.py` 5 种驱动 |
| Prometheus 指标（指标名/标签与 flower 一致） | `services/metrics.py` 7 个指标；`/metrics` 免鉴权 |
| 健康检查端点 | `monitor.py healthcheck`（实现浅，见 P2-2） |
| Basic + JWT 鉴权、多账号凭据编辑 | `core/security.py`；`CredentialsEditor.vue`；登录页 |
| 事件状态持久化（shelve） | `events.py save_state/_load_state`（默认关闭） |
| 趋势图表（吞吐/并发/耗时排行） | `MonitorView.vue`、`DashboardView.vue`（仅内存 24 分钟窗口，见 P0-2） |
| 实时事件流 | `state.py event()` → `hub.py` 广播 + 500 条环形历史 |
| 演示模式（模拟集群全链路可操作） | `services/mock.py`（582 行）；所有控制指令走生产代码路径 |
| 交互式 API 文档（Swagger/ReDoc/OpenAPI） | `main.py` 默认开启 |
| 运行时配置界面（热更新 + 落盘 + 重启） | `runtime_config.py`（631 行）；`ConfigView.vue`（1114 行） |
| 主题系统（内置 + 上传 + 目录监控 + WS 广播） | `theme_manager.py`；`ThemeSwitcher.vue` |

**结论**：FlowerUI 对 Flower 2.0.1 的"功能全量对齐"声明基本属实（flower 全部 API 端点均有对应实现，且 WS 推送、服务端分页、演示模式、主题系统等为增强项）。真正的功能缺口集中在 **告警、历史数据、权限体系、运维便捷操作、集成能力** 这五类"生产化监控平台"的必备能力上——这些原版 flower 也没有，但作为"监控平台"定位，它们是当前产品化程度最大的短板。

---

## 二、功能差距总览表

按优先级排序。价值：高=生产环境刚需/高频；中=明显提升体验或覆盖常见场景；低=锦上添花。

| # | 优先级 | 功能项 | 现状 | 业务价值 | 实现复杂度 | 工作量(人天) |
| --- | --- | --- | --- | --- | --- | --- |
| P0-1 | P0 | 告警与通知系统 | 缺失 | 高 | 中 | 4~6 |
| P0-2 | P0 | 数据保留/长期趋势/历史查询 | 部分（内存 24 分钟） | 高 | 高 | 8~12 |
| P0-3 | P0 | RBAC 角色权限 + 操作审计日志 | 缺失 | 高 | 中 | 3~5 |
| P0-4 | P0 | 任务一键重试/重发 | 缺失 | 高 | 低 | 1~2 |
| P0-5 | P0 | 任务列表/数据导出（CSV/JSON） | 缺失 | 中 | 低 | 1~2 |
| P1-1 | P1 | 国际化 i18n（中/英） | 缺失 | 中 | 中 | 3~4 |
| P1-2 | P1 | 任务依赖 DAG 可视化 | 部分（线性调用链） | 中 | 中 | 2~3 |
| P1-3 | P1 | 定时任务（Beat/Crontab）管理 | 缺失（仅只读展示） | 中 | 中 | 3~5 |
| P1-4 | P1 | OAuth2 单点登录 | 缺失（配置项存在但标记 todo） | 中 | 中 | 2~3 |
| P1-5 | P1 | 多 Broker/多集群集中监控 | 缺失（单 broker） | 中 | 高 | 5~8 |
| P1-6 | P1 | 外部系统集成（入站 Webhook + API Key） | 缺失 | 中 | 中 | 2~3 |
| P2-1 | P2 | 浏览器通知 + 移动端适配/PWA | 缺失 | 低 | 低 | 1~2 |
| P2-2 | P2 | 深度健康检查（依赖状态） | 部分（仅恒 OK） | 低 | 低 | 0.5~1 |
| P2-3 | P2 | result_backend/broker_api 界面可配 | 部分（已从界面字段表移除） | 低 | 低 | 0.5~1 |
| P2-4 | P2 | 单元测试体系 + CI | 部分（仅手工 e2e 脚本） | 中 | 中 | 3~5 |
| P2-5 | P2 | 收藏/书签 | 缺失 | 低 | 低 | 0.5~1 |
| | | **合计** | | | | **约 40~65 人天** |

---

## 三、差距项详细分析

### P0-1 告警与通知系统（缺失）

**现状**：全代码库无任何告警规则、阈值判断、通知渠道的实现（后端无 `alert`/`notify`/`webhook` 相关服务；前端无通知入口）。当前"监控"完全是被动的：worker 掉线、队列积压、任务失败率飙升，只有人盯着页面才能发现。唯一的"外发"通道是 Prometheus `/metrics`（需自行接 Alertmanager，对非 Prometheus 用户不友好）。

**缺口描述**：缺少阈值告警（积压水位、worker 离线、任务失败率/耗时、事件流中断）与多渠道通知（Webhook/邮件/钉钉/企微/飞书）、告警去重与静默、告警历史。这是监控平台从"看板"升级为"值守"的分水岭。

**解决方案**：

- 数据模型（新文件 `backend/app/services/alerts.py`，规则配置落 `flowerui.alerts.json`）：
  ```
  AlertRule: { id, name, scope: worker|task|queue|global, target,
               metric: queue_backlog|worker_offline|failure_rate|task_runtime|event_gap,
               op: ">"|"=="|"<", threshold, duration_s（持续时长防抖）,
               severity: warning|critical, channels: ["webhook","email","dingtalk",...],
               channel_config: {url|smtp...}, enabled, silence_until }
  AlertEvent: { id, rule_id, fired_at, payload, resolved_at, notified_via }
  ```
- 后端：新增 asyncio 评估协程（每 10s 扫一次，数据源复用 `manager.state`/`manager.broker_queues()`，零侵入）；`channels.py` 抽象渠道（httpx 调 Webhook/钉钉自定义机器人/飞书群机器人，smtplib 发邮件）；触发时 `hub.publish_threadsafe({"type": "alert", ...})` 推送前端，页面顶部红条提示。
- API：`GET/POST /api/alerts/rules`、`PUT/DELETE /api/alerts/rules/{id}`、`GET /api/alerts/events?limit=`、`POST /api/alerts/test`（发测试通知验证渠道连通性）。
- UI：侧边栏新增「告警」页（规则表格 + 启停开关 + 事件历史 + 新建规则表单）；头部增加铃铛 badge 显示未读告警数。

**工作量**：4~6 人天（规则引擎+评估 1.5、渠道 1.5、API/UI 2、联调 0.5~1）。**价值：高 · 复杂度：中 · 优先级 P0**

---

### P0-2 数据保留、长期趋势与历史查询（部分）

**现状**（全部为内存态，进程重启即失）：
- 任务记录：`EventsState.tasks` 上限 `max_tasks` 默认 100000 条（`state.py`/config.py），超出按 LRU 淘汰；
- 趋势时间线：`state.timeline` 为 `deque(maxlen=720)`、每 2s 采样一个点（`manager._timeline_loop`）→ **仅保留最近约 24 分钟**；
- 事件流：`hub.py` 环形历史仅 500 条，前端 `eventFeed` 仅 200 条；
- shelve 持久化（`FLOWER_PERSISTENT`）默认关闭，且只保存原始 state、无聚合、无保留策略；
- 无按小时/天的聚合，无法回答"昨天失败率多少""过去 7 天哪个任务最慢"。

**缺口描述**：监控平台核心价值之一是历史回溯与报表。当前只能看"此刻"，无法做同比环比、故障复盘、容量规划。

**解决方案**：

- 存储：引入 SQLite（Python stdlib，零新依赖，单文件 `.flowerui/history.db`）；表：
  ```
  timeline_agg(ts, worker, task, received, started, succeeded, failed, retried,
               revoked, active, queue_backlog)          -- 每分钟一行
  task_archive(id, name, worker, state, received, started, runtime,
               exception, root_id, parent_id)           -- 任务终态归档
  worker_daily(worker, date, succeeded, failed, min_online, max_concurrency, ...)
  ```
- 后端：新 `services/history.py`：
  1. 归档任务（每 1min 把 `state` 中新增终态任务写入 task_archive，每分钟把 timeline 采样点 rollup 进 timeline_agg）；
  2. 保留策略（`history_retention_days` 默认 90，可配置，启动时 prune）；
  3. 查询 API：`GET /api/history/summary?from&to&granularity=1m|1h|1d`（聚合曲线）、`GET /api/history/tasks?from&to&state&taskname&offset&limit`（历史任务分页查询）、`GET /api/history/compare?days=7`（同比，可选）。
- UI：「实时图表」页顶部增加时间范围选择器（实时 / 24h / 7d / 自定义），按范围切换数据源与粒度；任务列表页增加"含历史归档"过滤模式；与 P0-5 导出联动。

**工作量**：8~12 人天（schema+归档 2、rollup/保留策略 2、查询 API 2、前端时间范围切换与图表适配 2~3、联调+演示模式数据生成 1~2）。**价值：高 · 复杂度：高 · 优先级 P0**

---

### P0-3 角色权限（RBAC）与操作审计日志（缺失）

**现状**：
- `core/security.py get_current_user` 只返回用户名字符串，**无任何角色概念**——所有能登录的用户权限完全相同，包括关闭 worker、终止任务、改配置、删主题、重启整个后端；
- `CredentialsEditor.vue` 允许用户编辑所有账号的凭据（无"只能改自己"限制）；
- 全部控制/配置类接口（`/api/worker/*`、`/api/task/revoke|abort|apply|rate-limit|timeout`、`PUT /api/config`、`POST /api/system/restart`、`POST/DELETE /api/themes`）无任何操作审计记录，出问题无法追溯"谁在什么时候对哪个 worker 做了什么"。

**缺口描述**：生产环境多人共用监控平台时，"谁能看、谁能操作、操作可追溯"是安全基线。当前"多用户管理"（README 特性表）仅等于"多组密码"。

**解决方案**：

- 数据模型（`flowerui.users.json`，与 basic_auth 凭据机制兼容）：
  ```
  User: { username, role: admin|operator|readonly, created_at }
  ```
  - `admin`：全部权限（用户/告警/配置管理、重启系统）；
  - `operator`：查看 + 任务下发/撤销/终止 + worker 池/队列控制 + 告警规则；
  - `readonly`：仅查看与导出。
- 后端：JWT payload 增加 `role` 字段；新依赖 `require_role("operator")` 挂到对应路由（control.py 全部、tasks.py 下发/控制端点、config 写操作、themes 写操作、system/restart）；凭据编辑接口只允许 admin 改他人、任意登录用户改自己。
- 审计日志：`services/audit.py` 提供 FastAPI 依赖 `audit_action`，将（时间、用户、IP、方法、路径、目标对象、结果码）追加写 `audit.jsonl`（带轮转，保留 30 天）；`GET /api/audit?limit=&user=&offset=` 查询（仅 admin）。
- UI：「系统信息」页新增「审计日志」Tab（admin 可见）；凭据编辑器增加角色列；403 时前端统一提示"权限不足"。

**工作量**：3~5 人天（角色模型+JWT 改造 1、路由鉴权挂接 1、审计中间件+API 1、UI 1、回归 0.5~1）。**价值：高 · 复杂度：中 · 优先级 P0**

---

### P0-4 任务一键重试/重发（缺失）

**现状**：`TaskDetailView.vue` 操作区只有 获取结果/刷新/撤销/终止/中止；任务列表行操作只有 详情/撤销/终止。**没有任何"重跑这个任务"的入口**。失败任务要重发，用户必须：切到「下发任务」页 → 手填任务名 → 手工把 args/kwargs 复制成 JSON 文本 → 再下发。参数含中文/嵌套时极易填错。

**缺口描述**：重试是 Celery 运维最高频操作之一（失败修复后重跑、数据补数、定时任务漏跑补偿）。当前交互路径长且易错。

**解决方案**：

- 后端：`POST /api/task/retry/{taskid}?wait=&timeout=`（`tasks.py`）：从 `manager.state.tasks[taskid]` 取 `name/args/kwargs` 及原路由信息，复用 `manager.apply_task(name, args, kwargs, options, require_registered=False)` 重新投递，返回 `{"task-id": <新id>}`；mock 模式走 `mock.send_task` 同样可用。原任务已被内存淘汰时 404 并提示"超出保留上限，请手动下发"。
- 前端：任务详情头部增加「重试」按钮（终态任务可用，SUCCESS 重试需二次确认）；任务列表操作列增加「重试」文字按钮；点击后自动打开新任务详情抽屉（`detail.openTask(newId)`），形成"重跑→跟踪"闭环。

**工作量**：1~2 人天（API+mock 支持 0.5、UI 1、测试 0.5）。**价值：高 · 复杂度：低 · 优先级 P0**

---

### P0-5 任务列表/数据导出 CSV·JSON（缺失）

**现状**：前端无任何导出入口（全局搜索 csv/export 仅命中主题模板下载与"获取结果"按钮）；后端无导出端点。要把失败任务清单、某时段的任务数据交给同事或贴进工单，只能手动截图或逐条复制。

**缺口描述**：报表输出与跨系统协作（贴 Excel、导入 Jira/飞书表格）是日常刚需，实现成本却极低。

**解决方案**：

- 后端：`GET /api/tasks/export?format=csv|json&<与 /tasks/table 相同的过滤参数>&max=10000`：复用 `task_filter.iter_tasks` 过滤逻辑，csv 走流式 `StreamingResponse`（utf-8-sig 防 Excel 中文乱码），json 直接输出数组；`GET /api/workers/export?format=csv` 同理。
- 前端：任务列表筛选栏右侧增加「导出」下拉（CSV/JSON，携带当前全部过滤条件，文件名含时间戳）；Worker 列表同样加导出按钮。
- 远期并入 P0-2：历史归档数据支持带时间范围的导出。

**工作量**：1~2 人天（两个导出端点 0.5~1、前端按钮 0.5~1）。**价值：中 · 复杂度：低 · 优先级 P0**

---

### P1-1 国际化 i18n（缺失）

**现状**：前端无 `vue-i18n` 依赖（`package.json` 确认）；Element Plus 固定 `zh-cn` locale（`main.js:4-53`）、dayjs 固定 `zh-cn`（`utils/format.js:3-6`）；全部 11 个视图的文案（约 600+ 条：菜单、按钮、表头、提示语、确认弹窗）硬编码为中文。

**缺口描述**：无法为海外/英文团队提供服务；多语言 SRE 团队（国内企业出海场景常见）无法使用。

**解决方案**：

- 引入 `vue-i18n@9`；文案抽到 `src/locales/zh-CN.json` / `en-US.json`（按页面分 key 命名空间）；`ElementPlus` 的 locale 与 dayjs 的 locale 随切换动态更新；
- 后端：API 返回的错误提示（当前为中文，如"用户名或密码错误"）增加 `Accept-Language` 或固定英文+前端翻译两层策略（建议：后端 detail 用英文 code，前端按 locale 映射展示）；
- UI：顶栏增加语言切换（存 localStorage），默认跟随浏览器。

**工作量**：3~4 人天（文案抽取与英译 1.5、i18n 接线 0.5、后端文案策略 0.5~1、回归 0.5~1）。**价值：中 · 复杂度：中 · 优先级 P1**

---

### P1-2 任务依赖 DAG 可视化（部分）

**现状**：已具备**线性**调用链能力——`task_info` 返回 `children_tasks`、`parent_id`/`root_id` 过滤参数、任务详情"调用链"区块（根/父/子表格 + "查看整条调用链的全部任务"跳转）。`TaskDetailView.vue:221-268`。但**没有 DAG 图形化**：chord/chain/group 产生的多分支子任务树只能以表格逐层点开，无法一眼看清整条工作流的拓扑与每节点状态。

**缺口描述**：Celery 链式/和弦任务（`chain`/`chord`/`group`）是生产主流编排方式，DAG 视图是排查"链上哪一步挂了"的最快路径。

**解决方案**：

- 后端：`GET /api/task/dag/{taskid}`：以该任务为根，递归（限深 3 层、限节点 200）收集 root 下全部任务，返回 `{nodes:[{id,name,state,runtime}], edges:[[parent,child]]}`（数据全部来自内存 `state.tasks` 的 `parent_id/root_id`，无新数据源）。
- 前端：任务详情"调用链"区块增加「查看 DAG」按钮，用 ECharts `graph` 渲染（项目已有 echarts 依赖，零新增包）：节点按状态着色（复用 `TASK_STATE_COLOR`），点击节点打开对应任务详情抽屉，hover 显示耗时。

**工作量**：2~3 人天（DAG 组装 API 0.5、图渲染+交互 1.5、边界处理（环/超深/跨内存淘汰）1）。**价值：中 · 复杂度：中 · 优先级 P1**

---

### P1-3 定时任务（Beat/Crontab）管理（缺失）

**现状**：`WorkerDetailView.vue` 有 "scheduled"（scheduled tasks）Tab，仅**只读展示** worker 当前保留的 eta/countdown 任务；没有 beat 调度表查看（crontab 条目、上次/下次触发时间）、没有手动触发某个 beat 条目、没有定时任务运行记录。

**缺口描述**：定时任务漏跑/重复执行是 Celery 常见事故，运维需要"beat 在跑什么、每个任务下次何时触发、手动补一次触发"的能力。原版 flower 也没有此功能（属增强项），但对生产价值明确。

**解决方案**：

- 后端：`services/beat.py`：
  1. 若 result backend 为 Redis：读取 beat 的 `celery-beat-schedule`（pickle/json 按 beat 存储格式解析）展示条目、上次运行时间；
  2. `POST /api/beat/trigger/{taskname}`：立即以该条目的默认参数 `send_task` 补触发一次（复用 apply_task 通道）；
  3. `GET /api/beat/schedule`：返回条目列表（不可用时返回 503 + 原因，如"未连到 beat 的 Redis 或 beat 未启用"）。
- UI：新「定时任务」菜单页（beat 条目表格 + 状态 + 手动触发按钮 + 触发历史），或在系统信息页加 Tab。
- 约束说明（写进 UI 提示）：beat 进程独立，FlowerUI 只能"读+补触发"，不能改 beat 的 crontab（改调度仍需在代码/配置层做）。

**工作量**：3~5 人天（schedule 读取/解析 1.5、触发+历史 1、UI 1.5、与不同 beat 存储兼容 0.5~1）。**价值：中 · 复杂度：中 · 优先级 P1**

---

### P1-4 OAuth2 单点登录（缺失，相对 Flower 2.0.1 的回退）

**现状**：
- 原版 flower 2.0.1 支持 OAuth2：`options.py` 有 `auth`（邮箱白名单正则）、`oauth2_key`、`oauth2_secret`、`oauth2_redirect_uri`、`auth_provider`，`views/auth.py LoginHandler` 实现 Google 等第三方登录流程；
- FlowerUI 的 `config.py` 保留了全部这些字段，但**没有任何 OAuth 路由与流程**——`auth.py` 只有 `/api/auth/config` 与 `/api/auth/login`（用户名密码）；
- `runtime_config.py:163-166` 已自己承认：`auth` / `auth_provider` 两个字段标 `todo=True`，reason="OAuth 登录流程尚未接入"。

**缺口描述**：这是 README"功能全量对齐 Flower 2.0.1"中**唯一实质缺失的项**（其余为增强）。企业内网用户通常需要 SSO（Google/GitHub/企业 IdP）而非手工分发密码。

**解决方案**：

- 后端：`/api/auth/oauth/{provider}/start`（302 到授权页，provider 抽象：google/github/generic OIDC）+ `/api/auth/oauth/{provider}/callback`（换 token → 匹配 `auth` 邮箱白名单正则 → 签发本项目 JWT → 重定向前端 `/login?oauth=token`）；provider 配置走现有 `auth_provider/oauth2_key/oauth2_secret/oauth2_redirect_uri` 字段，补进 `runtime_config.FIELDS` 可编辑（secret 脱敏）。
- 前端：登录页增加"使用 Google/GitHub 登录"按钮（配置了 provider 才显示）；接收 callback 参数后直接存 token 进首页。
- `/api/auth/config` 返回已配置的 provider 列表，登录页据此渲染。

**工作量**：2~3 人天（provider 抽象+两路由 1、邮箱白名单匹配与 JWT 签发 0.5、登录页 UI 0.5、联调 0.5~1）。**价值：中 · 复杂度：中 · 优先级 P1**

---

### P1-5 多 Broker/多集群集中监控（缺失）

**现状**：`FLOWER_BROKER_URL` 是单一字符串（`config.py:38`），全部服务（事件采集、inspector、broker 队列查询、任务下发）绑定这一个 broker。无法在一个 FlowerUI 实例上同时看"生产集群 + 预发集群"或"多个独立 Redis 队列"。

**缺口描述**：多环境/多业务线团队只能部署多个 FlowerUI 实例分别看，告警、报表、操作审计也被割裂。

**解决方案**：

- 数据模型：`Cluster: { id, name, broker_url, result_backend?, enabled, weight_color }`，存 `flowerui.clusters.json`；默认把当前 `broker_url` 迁移为唯一集群。
- 后端：`ServiceManager` 从"单实例"改为"集群注册表"：每个集群一套 `Events + Inspector + state`；API 增加 `cluster` 路径段或查询参数：`GET /api/clusters`、`GET /api/clusters/{id}/workers` 等（保持现有路径向后兼容，不带 cluster 参数时返回默认集群）；dashboard/summary 支持跨集群聚合视图。
- UI：顶栏增加集群切换下拉（含"全部"聚合视图），侧边栏新增「集群管理」页（增删集群、连通性测试 ping_broker）。
- 工作量较大，建议作为独立版本迭代。

**工作量**：5~8 人天（多实例化 manager/state 1.5、API 透传 cluster 1.5、集群管理页 1.5、聚合视图 1、回归 1~1.5）。**价值：中（多环境团队高）· 复杂度：高 · 优先级 P1**

---

### P1-6 外部系统集成：入站 Webhook 与 API Key（缺失）

**现状**：出站方向只有 Prometheus 抓取；入站方向没有任何 webhook 端点。外部系统（CI/CD、发布平台、告警平台、脚本）只能通过 UI 同款 JWT/Basic 接口调用，没有轻量 API Key，也没有"事件驱动"入口（例如发布系统通知 FlowerUI"新版本开始"，在界面上打时间标记/变更事件线）。

**缺口描述**：无法把 FlowerUI 嵌入更宽的 DevOps 流水线：① 外部系统无法低成本调用 API（API Key）；② 外部变更事件无法在监控时间线上留痕（变更与故障对照是排障高频需求）。

**解决方案**：

- API Key：`flowerui.apikeys.json` 存 `{name, key(随机 32B), role, expires_at, enabled}`；`get_current_user` 优先匹配 `Authorization: ApiKey xxx`；API Key 页面（admin）管理；OpenAPI 文档注明两种鉴权方式。
- 入站 Webhook：`POST /api/hooks/event`（ApiKey 鉴权）：`{type: "deployment"|"annotation", title, detail, ts}` → 追加到 `state` 的变更事件线并 WS 广播；Dashboard 时间线图上叠加变更标记线。
- 前端：Dashboard 趋势图叠加变更竖线（hover 显示标题）；设置页管理 webhook 端点地址（供外部系统配置）。

**工作量**：2~3 人天（API Key 1、webhook+时间线标记 1、UI 0.5~1）。**价值：中 · 复杂度：中 · 优先级 P1**

---

### P2-1 浏览器通知与移动端适配/PWA（缺失）

**现状**：
- 无 Web Notification API 调用（全局搜索 `new Notification` 无结果），页面不在前台时（切了 tab）worker 掉线/任务失败无任何系统级提醒；
- 无响应式布局：全部 11 个视图为桌面表格布局，全项目仅 1 处 `@media` 断点（`AppLayout.vue:352`，900px 时隐藏两个头部元素），手机端表格横向溢出、侧边栏无抽屉化；无 PWA/manifest/service worker。

**缺口描述**：值班工程师手机上看一眼"现在有没有事"是监控平台常见使用场景。

**解决方案**：

- 浏览器通知：P0-1 告警系统落地后，在告警触发处加 `new Notification()`（需用户授权，配置页加"启用浏览器通知"开关 + 授权引导）；
- 移动端：Element Plus 表格加横向滚动容器 + 关键页（Dashboard/任务列表）增加 640px 下的卡片式布局（CSS-only 方案即可）；manifest + 图标 → 可"添加到主屏"（PWA 完整化可后置）。

**工作量**：1~2 人天（浏览器通知 0.5、响应式关键页 1、PWA 基础 0.5）。**价值：低 · 复杂度：低 · 优先级 P2**

---

### P2-2 健康检查深度（部分）

**现状**：`monitor.py healthcheck` 恒返回 `{"status": "OK"}`，与 broker 连通性、事件采集线程存活（`manager.events.connected`/`last_error` 字段其实已存在）完全无关。K8s 探针/负载均衡器只能判断"进程活着"，无法判断"监控能力还在"。

**解决方案**：`GET /healthcheck?deep=1` 返回 `{status: OK|DEGRADED, events_connected, broker_reachable(缓存 10s), workers_online, uptime}`，DEGRADED 时 200 + 字段（K8s 可读），默认无参行为不变保持兼容。`/api/system` 已暴露大部分字段，聚合即可。**工作量**：0.5~1 人天。**价值：低 · 复杂度：低 · 优先级 P2**

---

### P2-3 result_backend 等关键连接项不可在界面配置（部分）

**现状**：`runtime_config.load()` 的注释（`runtime_config.py:528`）明确写着 result_backend/broker_api"已从字段表移除"——这两项只能靠环境变量设置。后果：未配 result backend 的用户在 UI 里看不到入口，下发/查结果报 503 后只能靠系统页提示去改环境变量再重启。README"运行时配置界面"宣称"可编辑 + 自动落盘"，但连接类核心项实际不可编辑。

**解决方案**：把 `result_backend`、`broker_api` 加回 `FIELDS`（`editable=True, restart=True, secret=True`，celery 分组）；改动落盘 `flowerui.runtime.env`，重启后 `get_celery_app` 读取时注意 app 已实例化的问题（在 `_apply_capacity` 同款钩子机制里重建 capp 或明确提示需重启 worker）。`/api/system` 已显示 `result_backend_configured`，联动刷新。**工作量**：0.5~1 人天。**价值：低（但消除"已声明能力"与实现的落差）· 复杂度：低 · 优先级 P2**

---

### P2-4 测试体系与 CI（部分）

**现状**（`backend/tests/` 实际内容）：
- `functional_check.py`（350 行）/ `e2e_check.py`（326 行）：手工运行的 HTTP 端到端脚本，依赖一个**已启动的服务**，非 pytest，不能无人值守；
- `smoke_control.py`、`test_events_flow.py`、`test_redis_connection.py`：诊断脚本（文件名像 pytest 但内容是 print + main，且依赖真实 Redis）；
- **核心纯逻辑模块零单测**：`search.py`（搜索 DSL）、`task_filter.py`（过滤/排序）、`state.py`（状态机）、`runtime_config.py`（配置解析/落盘）、`theme_manager.py`（元数据解析）、`mock.py`（演示集群）全部是"改坏了只能靠人点 UI 发现"；
- 无 pytest 配置、无 CI 工作流文件（无 .github/workflows 或等效物）、前端无任何测试。

**解决方案**：

- 引入 `pytest + httpx`（TestClient），优先补高价值单测：search DSL 各语法分支、task_filter 排序/时间边界、runtime_config 的 .env 解析/行级更新/迁移逻辑、theme_manager 元数据解析（含非法输入）；
- 用 `FLOWER_MOCK=true` 起 TestClient 做接口级集成测试（mock 模式正是为零依赖测试设计的，当前却没有利用）；
- 加最小 CI：后端 pytest + 前端 `npm run build` 两条 job。

**工作量**：3~5 人天（pytest 基建 0.5、单测 2~3、mock 集成测试 1、CI 0.5）。**价值：中（长期质量保障）· 复杂度：中 · 优先级 P2**

---

### P2-5 收藏/书签（缺失）

**现状**：无。高频查看的 worker、常查的任务类型/过滤组合每次都要重新筛选。

**解决方案**：纯前端方案（localStorage）：任务列表"保存当前过滤条件"→ 顶部书签 chips 一键复用；worker 列表行加星标（收藏置顶）。后端无需改动。**工作量**：0.5~1 人天。**价值：低 · 复杂度：低 · 优先级 P2**

---

## 四、建议路线图

| 阶段 | 周期 | 内容 | 目标 |
| --- | --- | --- | --- |
| **P0（立即，第 1~2 周）** | ~19 人天 | P0-1 告警通知、P0-3 RBAC+审计、P0-4 任务重试、P0-5 导出、P0-2 历史归档（可拆两期：先 SQLite 归档+保留策略，后查询/聚合 UI） | 从"看板"变成可值守的生产监控工具：出事有人收到、操作有人负责、数据可导出可重跑、历史可回溯 |
| **P1（近期，第 3~6 周）** | ~20 人天 | P1-4 OAuth2（补齐 flower 对齐缺口）、P1-1 i18n、P1-2 DAG 视图、P1-6 Webhook+API Key、P1-3 Beat 管理、P1-5 多集群（可独立排期） | 补齐"全量对齐"最后一块、打通企业 SSO 与 DevOps 集成、提升排障效率 |
| **P2（远期，按需）** | ~7 人天 | P2-4 测试+CI（建议与 P0 并行小步开始）、P2-1 移动端/通知、P2-2 健康检查、P2-3 result_backend 界面化、P2-5 收藏 | 质量与体验打磨 |

**执行建议**：
1. P0-4（重试）与 P0-5（导出）是"小投入大体验"项，建议第一周先行，快速交付价值；
2. P0-2（历史数据）是 P0 中唯一的"大项"，建议先落"SQLite 归档 + 保留策略"（2~3 天）止血数据丢失，查询/聚合 UI 放到 P0 后半程；
3. P2-4 的测试基建建议从第一个 P0 改动开始就补单测，避免越改越没底；
4. P1-5（多集群）改动面大（manager 多实例化），建议作为独立版本，不与其它 P1 混做。

---

## 五、工作量汇总

| 优先级 | 条目数 | 工作量区间 | 合计 |
| --- | --- | --- | --- |
| P0 | 5 | 4~6 / 8~12 / 3~5 / 1~2 / 1~2 | 17~27 人天 |
| P1 | 6 | 3~4 / 2~3 / 3~5 / 2~3 / 5~8 / 2~3 | 17~26 人天 |
| P2 | 5 | 1~2 / 0.5~1 / 0.5~1 / 3~5 / 0.5~1 | 5.5~10.5 人天 |
| **总计** | **16** | | **约 40~65 人天** |

---

## 附录：已核实无缺口的"对照项"（避免误报）

以下任务书提示需验证的方向，经代码核实后确认**已实现或不在本平台能力域**，不计入差距：

| 方向 | 核实结论 |
| --- | --- |
| 多队列支持 | 已实现：任意数量队列均可监控（`broker.py` 按队列名列表查询）、worker 可动态 add/cancel consumer、下发表单按队列路由 |
| 单一 broker 视图 | 单 broker 属实 → 记入 P1-5（多集群），多队列本身无缺口 |
| 告警/通知 | 缺失 → P0-1 |
| 权限/审计 | 缺失 → P0-3 |
| 数据保留/历史 | 内存态 + 默认关闭的 shelve → P0-2 |
| DAG | 线性调用链已有 → P1-2（仅缺图形化） |
| 任务重试 | 缺失 → P0-4 |
| 定时任务管理 | 仅只读展示 → P1-3 |
| i18n | 缺失 → P1-1 |
| 多集群 | 缺失 → P1-5 |
| 移动端/浏览器通知 | 缺失 → P2-1 |
| 集成 API | OpenAPI 完整（Swagger/ReDoc）；webhook 入站与 API Key 缺失 → P1-6 |
| 测试覆盖 | 仅手工 e2e/诊断脚本，核心模块无单测 → P2-4 |
| 任务结果/中止 | 已实现（依赖 result backend，未配置时显式 503 并在系统页说明） |
| 事件持久化 | 已实现（默认关闭，属配置选择） |


