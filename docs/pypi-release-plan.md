# FlowerUI 发布到 PyPI 改造方案（评审稿）

> **状态：两项决策已确认，P1 包重命名 + P4 打包骨架已实施，见 §10 实测记录。**
>
> | 项目 | 结论 |
> | --- | --- |
> | 基线提交 | `import/other-machine` @ `726657c`（已同步远程）；本轮改动在其之上，**尚未提交** |
> | PyPI 包名 | `flowerui` —— 2026-11-05 通过 `https://pypi.org/pypi/flowerui/json` 核验，返回 `Not Found`，**未被占用** |
> | 依赖策略 | **已确认：兼容 pydantic v1 / v2**（实现路径见 §4.2） |
> | 交付范围 | **已确认：先出方案，随后按阶段实施；本轮完成 P1 与 P4/P5（3.7）** |
> | 包结构 | **已确认并实施：方案 A 原地改造** —— `backend/app/` → `backend/flowerui/`（见 §4.1、§10） |
> | Python 版本 | **硬性约束：必须使用 3.7** —— `requires-python = ">=3.7"`，本地 venv 3.7.9，wheel 在干净 3.7.9 环境实测安装并启动（见 §4.2、§7、§10） |
>
> 术语约定：**分发名** = `pip install flowerui` 里的 `flowerui`；**导入包名** = Python 里 `import flowerui`；两者建议一致。

---

## 1. 目标与验收标准

让任意一个已有 Celery 项目，无需改代码、无需额外配置 broker，就能用两条命令之一拉起监控面板：

```bash
pip install flowerui

# 方式 A：Celery 子命令（推荐，最贴近官方 flower 的使用习惯）
celery -A their_project.celery:app flowerui --port 5555

# 方式 B：独立命令
flowerui -A their_project.celery:app --port 5555

# 方式 C：模块方式
python -m flowerui -A their_project.celery:app
```

`-A` 指向的是**用户自己的 Celery app**；FlowerUI 自动从 `app.conf` 继承 broker、result backend、
transport options、默认队列等，用户不必在 FlowerUI 里再配一遍。

> **当前进度**：三种命令形态已全部可用，**P3（从用户 `app.conf` 自动继承连接配置）已实现并实测**：
> `celery -A examples.demo_proj.celery:app flowerui --dry-run` 正确显示继承自该 app 的
> `broker_url=redis://127.0.0.1:6399/3` / `result_backend` / `broker_transport_options` /
> `task_default_queue` / `task_routes`，且显式 `--broker-url`、TOML、环境变量仍可覆盖。
> 详见 §10.6。

验收标准（全部满足才算完成）：

1. 在未安装本项目源码的全新 venv 里 `pip install flowerui-<ver>-py3-none-any.whl` 成功，不联网拉前端构建工具；
2. `celery --help` 能看到 `flowerui` 子命令；`flowerui --help` 可用；
3. 用一个**模拟的第三方 Celery 项目**（`demo_proj/celery.py` 中 app 的 broker 指向非默认地址）启动，
   FlowerUI 的 `/api/system` 显示的 broker 与该项目一致，且不需要在 FlowerUI 侧重复配置；
4. 打开 `http://127.0.0.1:5555/` 能看到完整界面（静态资源随 wheel 分发），接口全部 200；
5. 安装到 **pydantic v1** 与 **pydantic v2** 两种环境都能启动，且不改变对方已装的 pydantic 版本；
6. `twine check dist/*` 通过；wheel 内不含 `flowerui.runtime.toml`、`*.db`、`flower.state*`、日志等本地数据。

---

## 2. 现状盘点：为什么当时不能直接 `python -m build`

> 本节记录的是**改造前**基线状态；已完成项与当前实测状态见 §10。

| # | 阻塞项 | 现状 | 打包后必须 |
| --- | --- | --- | --- |
| 1 | 顶层包名 | 源码包叫 `app`，入口 `app.main:app` | 与几乎所有 Celery / Django 项目的 `app` 目录冲突；应改为 `flowerui`。**有利条件**：包内几乎全是相对导入，绝对路径引用仅约 10 处 |
| 2 | 构建元数据 | `backend/pyproject.toml` 刻意没有 `[build-system]`，是 uv virtual project | 必须加 build-system、`[project]` 元数据、两个 entry point、静态资源打包规则 |
| 3 | pydantic | 硬钉 `pydantic<2`；`config.py` 用 `BaseSettings` + `validator` / `root_validator` / `Config.extra` | 装进 pydantic v2 项目会强制降级对方依赖；见 §4.2 |
| 4 | Python 版本 | `requires-python >=3.7`，本地 venv 为 3.7.9，`uv.lock` 按 3.7 锁定 | **已定：下界保持 3.7（用户硬性要求）**。build-system 用 `python_version` markers 双轨选 setuptools / wheel，保证 3.7 与现代 Python 都能构建；产物均为 `py3-none-any` |
| 5 | 路径假设 | `flowerui_cli.py::_prepare_runtime()` 会 `os.chdir(backend)`；`RUNTIME_FILE` 按 cwd 解析；主题上传写 `app/themes/`；`restart.py` 调 `backend/manage.sh` | site-packages 通常只读且没有 manage.sh；需引入用户可写数据目录并降级脚本式重启 |
| 6 | 复用用户 app | 目前 `celery -A celery_app flowerui` 的 `-A` 指向**本项目自带**的 `celery_app.py` | 需从用户 app 的 `conf` 注入连接配置，见 §4.3 |
| 7 | 静态资源 | `backend/app/static/`（26 个文件）与 `backend/app/themes/`（15 个文件）**已入库** | 必须作为 `package_data` 进 wheel；否则安装后白屏 |
| 8 | 许可证 | 仓库无 `LICENSE` 文件，README 写的是 MIT | 开源分发必须补 `LICENSE`，并在元数据声明 |
| 9 | 运行时数据 | `flowerui.runtime.toml` 含真实 Redis 凭据（已 gitignore）、`flower.state*`、`*.db`、`logs/` | wheel / sdist 必须显式排除，且默认配置模板不能带真实地址 |

补充事实：`app/__init__.py` 存在且为空；`config.py` 的 `_sources()` **已经自行完成** TOML + `FLOWER_*` 环境变量合并，
`BaseSettings` 只负责类型转换、默认值和 4 个预处理 validator —— 这是 §4.2 能去 pydantic 化的关键。
pydantic 使用分布：`core/config.py`（BaseSettings）与 `api/routers/{auth,config,system,tasks}.py`（`BaseModel` / `Field`，v1/v2 均兼容）。

---

## 3. 目标形态

> §3~§5 是原方案设计；实际落地用的是 **setuptools**（不是当时设想的 hatchling），
> 且 `requires-python` 定为 `>=3.7`。以 §10 的实施记录为准。

### 3.1 配置优先级（新增「用户 app.conf」一层）

```
显式 CLI 参数  >  用户 celery app.conf  >  flowerui.runtime.toml 回放
             >  FLOWER_* 环境变量  >  flowerui-settings.toml  >  代码默认值
```

实现要点：`runtime_config.load()` 在 FastAPI lifespan 阶段会回放 TOML 并 `setattr(settings, ...)`，
所以「app.conf 注入项」必须与显式 CLI 覆盖一起登记进 `set_cli_overrides()`，
让 `load()` 跳过这些键（现有机制已具备，只需扩展合并顺序：先 app.conf、再显式 CLI 覆盖）。

### 3.2 目标目录结构（以「原地改造」方案为例）

```
backend/
├── pyproject.toml                 # 改造：build-system / project / entry points / setuptools 打包规则
├── LICENSE                        # 新增（或放仓库根，二者取其一）
├── flowerui/                      # 由 app/ 重命名
│   ├── __init__.py                # 新增 __version__
│   ├── main.py                    # FRONTEND_DIST / SPA fallback 改用包内资源
│   ├── cli.py                     # ✅ 已移入并加 main()；-A / app.conf 注入待 P3
│   ├── __main__.py                # ✅ 已新增：python -m flowerui
│   ├── config_compat.py           # 新增：去 pydantic 后的类型强转（或直接在 config.py 内实现）
│   ├── default_settings.toml      # 由 flowerui-settings.toml 复制为包内只读默认值
│   ├── static/                    # 前端产物（26 文件，package_data）
│   ├── themes/                    # 内置主题（15 文件，package_data，仅作播种源）
│   ├── core/ api/ services/       # 保持相对导入，基本无需改动
│   └── ...
├── flowerui-settings.toml         # 保留：本地开发可编辑的默认配置
├── celery_app.py                  # 保留：仅供源码开发时 `celery -A celery_app`
├── register_celery_command.py     # 保留但标注「仅源码开发用」；pip 安装后由 entry point 自动注册
├── manage.sh                      # 入口字符串 app.main:app → flowerui.main:app（3 处 + pkill 特征）
├── tests/                         # from app.* → from flowerui.*
└── docs/
```

---

## 4. 关键设计决策

### 4.1 包结构（**已确认：方案 A，已实施**）

| 方案 | 做法 | 优点 | 代价 |
| --- | --- | --- | --- |
| **A. 原地改造 backend（推荐）** | `backend/app/` → `backend/flowerui/`，同步改 manage.sh / 测试 / 文档 / Dockerfile 的入口字符串；给 `pyproject.toml` 加 build-system | 一套代码同时服务本地开发与 PyPI；本地与安装后行为完全一致，测试可信 | 约 15 个文件需改；现有 manage.sh 链路要回归 |
| B. 新建独立发布目录 | `packages/flowerui/` 复制一份发布用源码，现有 backend 不动 | 现有项目零风险 | 两份代码长期维护，功能必然漂移 |
| C. 只加打包映射 | 源码仍叫 `app`，用 hatchling `force-include` 把 wheel 内映射成 `flowerui` | 改动最少 | 本地 / 安装后模块名不一致，入口命令两套，验证易漏 |

**已按 A 实施**（2026-11-05）：`git mv backend/app backend/flowerui` 保留历史，19 个文件共 74 处
入口字符串 / 路径替换，另补 4 处遗漏（Dockerfile COPY、frontend 同步目录检测、两处 `from app.services import`）；
静态资源 26 文件、主题 15 文件完整未丢。当时的判断依据：包内相对导入占绝大多数
（`from .api.routers import ...`），重命名对 Python 代码几乎无影响，需要改的只是**入口字符串与脚本**：`backend/manage.sh`(3)、`backend/README.md`(1)、
`flowerui_cli.py`(1)、`tests/{smoke_control,test_events_flow,test_redis_connection,e2e_check}.py`(4)、
`celery_app.py`(1)、`Dockerfile` / `docker-compose.yml`、`send_tasks.py` / `start_workers.py` / `_broker_env.py`（需逐个核对导入）。

### 4.2 pydantic v1/v2 兼容（**已确认方向，实现路径建议如下**）

**推荐：配置层去 pydantic 化，而不是写 shim。**

- `config.py` 的 `Settings` 改为纯 Python 类：字段默认值保留为类属性，新增 `FIELD_TYPES` 元数据表；
  `_coerce(key, value)` 统一处理 `str / int / float / bool / list / dict / Optional` 与 JSON 字符串；
  把现有 `_split_csv` / `_parse_json_dicts` / `_parse_task_routes` / `_split_floats` 四个 validator 的逻辑并入其中；
  保留 `auth_enabled` / `inspect_timeout_seconds` / `task_columns_list` 等 property 不变。
- API 层的 `pydantic.BaseModel`（`LoginRequest` 等）在 v1/v2 都可用，无需改动。
- **为什么不用 `try: from pydantic_settings import BaseSettings` 的 shim**：`pydantic-settings` 2.x 强依赖
  `pydantic>=2`，若设为强制依赖会把 v1 项目强行升级，与「兼容 v1/v2」目标冲突；若设为可选依赖，
  v2 环境又可能没装它。此外 v2 的 `root_validator` / `validator` 已是弃用 API，`@classmethod` 叠加顺序也不同。
  去掉 BaseSettings 后，发布包对 pydantic **零约束**，由用户环境的 FastAPI 决定大版本，冲突面最小。
- 依赖声明（示例，具体版本在 Phase 2 用 v1/v2 双环境实测后定稿）：

  ```toml
  requires-python = ">=3.7"
  dependencies = [
    "fastapi>=0.95,<0.100; python_version < '3.8'",   # 3.7 只能装 0.103.x 及更早
    "fastapi>=0.100; python_version >= '3.8'",
    "pydantic<2; python_version < '3.8'",              # 3.7 本身只有 v1
    "uvicorn[standard]>=0.20",
    "celery>=5.2,<6", "redis>=4", "websockets>=10", "python-multipart",
    "prometheus-client", "PyJWT>=2", "httpx", "toml",
  ]
  ```

  **当前 wheel 尚未采用上表**：配置层仍用 `BaseSettings`，`>=3.8` 分支若放开 `pydantic<2` 会在 v2 环境启动失败，
  因此 0.1.0 暂时**全版本保留 `pydantic<2`**（已知限制，装进 v2 项目会降级对方依赖）。
  上表的双轨 markers 必须在 **P2 配置层去 pydantic 化完成后**才能启用。

  移除 `pydantic<2` 与 `importlib-metadata<5` 两个上界；`[tool.uv] package = false` 保留，
  让本地 `uv sync` 继续按 `uv.lock` 装 3.7 依赖、不构建项目本身。
- 回归重点：CSV 字符串 → list、JSON 字符串 → dict、`FLOWER_TASK_ROUTES` 注入、布尔值 `"false"` 解析，
  必须与现在 pydantic 的行为逐项对齐（建议先补一组配置层单元测试再改）。

### 4.3 复用用户已有的 celery_app（核心需求）

**Celery 子命令路径**（`celery -A their_project.celery:app flowerui`）：

- Celery 5.x 在解析 `-A` 时已 `find_app()` 导入用户模块，并把 app 放在 CLI context 的 `obj.app`
  （5.2.x 与 5.6.x 结构略有差异，需兼容回退到 `celery.current_app`）。
- 子命令里新增 `_app_conf_overrides(ctx)`，读取：

  ```python
  conf = user_app.conf
  keys = {
      "broker_url": conf.get("broker_url"),
      "result_backend": conf.get("result_backend"),
      "broker_transport_options": conf.get("broker_transport_options") or {},
      "task_default_queue": conf.get("task_default_queue") or "celery",
      "task_routes": conf.get("task_routes") or {},
  }
  ```

  过滤掉 `None` / 空值后，与显式 CLI 覆盖合并（`{**app_conf, **explicit_cli}`），
  再调用 `runtime_config.set_cli_overrides()`，并通过 `FLOWERUI_CLI_OVERRIDES` 传给 reload / workers 子进程。
- 未提供 `-A` 或用户 app 未配 broker 时，完全沿用现有配置，行为不变（向后兼容）。

**独立命令路径**（`flowerui -A their_project.celery:app`）：

- `[project.scripts] flowerui = "flowerui.cli:main"`，复用同一个 click command，
  额外提供 `-A/--app` option；用 `celery.app.utils.find_app()` / `symbol_by_name` 加载用户模块拿 app，
  走同一套 conf 注入逻辑。
- 文档要明确区分：Celery 全局 `-A` 写在子命令 **之前**，独立命令的 `-A` 写在 `flowerui` **之后**。
- `__main__.py` 提供 `python -m flowerui`。

### 4.4 可写数据目录与路径适配

引入 `FLOWERUI_HOME`（默认 `~/.flowerui`，遵循 `$XDG_DATA_HOME`）：

| 数据 | 源码开发（现状） | pip 安装（目标） |
| --- | --- | --- |
| 静态资源 | `app/static/`（包内） | `importlib.resources` 读 `flowerui/static`（只读） |
| 默认配置 | `backend/flowerui-settings.toml`（按 `__file__` 上溯） | 包内 `flowerui/default_settings.toml`，本地 TOML 仍可覆盖 |
| 运行时配置 | `./flowerui.runtime.toml`（按 cwd） | `FLOWER_RUNTIME_CONFIG_FILE` > `./flowerui.runtime.toml`（若存在）> `$FLOWERUI_HOME/runtime.toml` |
| 主题目录 | `app/themes/`（上传写这里） | `FLOWER_THEMES_DIR` > `$FLOWERUI_HOME/themes`，首次从包内 themes 播种 `base.css` / `_template.css` |
| SQLite / 状态文件 | cwd 下 `*.db` / `flower.state*` | `$FLOWERUI_HOME/` 下 |

**必须删除** `_prepare_runtime()` 里的 `os.chdir(BACKEND_DIR)` —— 安装版若 chdir 到 site-packages，
会改变用户项目的工作目录并把配置写进只读目录。`sys.path` 注入仅保留给「从源码目录运行」的兜底分支。

### 4.5 静态资源与主题打包

- 发布前执行 `./manage.sh build`（`frontend/npm run build` → 同步 `frontend/dist` 到 `backend/flowerui/static`），
  保证 wheel 内的前端与当前源码一致；**不要在用户机器上要求 Node.js**。
- hatchling 需**显式**声明包含规则（否则非 `.py` 文件可能被排除）。以下为示意，
  `packages` 与 `force-include` 是否重复包含同一路径，要在 P4 用 `unzip -l` 检查 wheel 后定稿：

  ```toml
  [tool.hatch.build.targets.wheel]
  packages = ["flowerui"]

  [tool.hatch.build.targets.wheel.force-include]
  "flowerui/static" = "flowerui/static"
  "flowerui/themes"  = "flowerui/themes"
  ```

- sdist 需包含 `pyproject.toml`、`LICENSE`、`README`、`flowerui/`；**显式排除**
  `flowerui.runtime.toml`、`logs/`、`*.db`、`flower.state*`、`.venv/`、`__pycache__/`。
- 当前静态产物约 2.9 MB，wheel 体积可接受；版本号变更时务必重新构建前端，避免前后端不同步。

### 4.6 入口点

```toml
[project.scripts]
flowerui = "flowerui.cli:main"

[project.entry-points."celery.commands"]
flowerui = "flowerui.cli:flowerui"
```

- `register_celery_command.py` 的价值只剩「本地源码 venv 未安装包时手动注册」；发布包不需要它，
  README 应标注清楚，避免误导用户去执行。
- 需在 **Celery 5.2.7 与 5.6.x** 两个环境各验一次 `celery --help` 是否列出 `flowerui`
  （Celery 通过 `click_plugins` + `entry_points()` 发现子命令，大版本间有过调整）。

### 4.7 「系统重启」按钮

`restart.py` 目前 `bash manage.sh restart`，pip 安装后没有该脚本：

- 启动时探测脚本存在性；不存在则 `/api/system/restart` 返回明确 JSON（如 `{"detail": "当前为 pip 安装模式，请重启进程管理器托管的服务"}`），
  前端把按钮置灰或改为提示；
- 可选 `FLOWERUI_RESTART_MODE=supervisor`：进程自行退出，交由 systemd / supervisor / Docker 重启策略拉起；
- **不要**默认在用户项目里 kill 进程或执行外部脚本。

### 4.8 许可证与包元数据

- 补 `LICENSE`（MIT，与 README 声明一致），`[project] license = {text = "MIT"}` 或 SPDX 表达式；
- `[project]`：`name = "flowerui"`、`version`、`description`、`readme`、`requires-python`、`authors`、`keywords`、
  `classifiers`（`Framework :: Celery`、`Framework :: FastAPI`、Python 3.7~3.12、MIT）、
  `[project.urls]`（Homepage / Repository / Issues）；
- 版本号与 git tag 对齐；上传后 PyPI **不允许覆盖同名版本**，只能递增。

---

## 5. 文件级改动清单

| 文件 | 改动 | 风险 / 验证 |
| --- | --- | --- |
| `backend/app/` → `backend/flowerui/` | 整目录重命名（含 26 个 static、15 个 themes） | 用 `git mv` 保留历史；确认无其它目录引用 `app.` |
| `backend/flowerui/__init__.py` | 新增 `__version__` | 低 |
| `backend/flowerui/main.py` | `FRONTEND_DIST` 改包内资源定位；SPA fallback 同步 | 白屏回归 |
| `backend/flowerui/core/config.py` | 去 `BaseSettings`，纯 Python Settings + `_coerce` | **高**：需配置层单元测试全覆盖 |
| `backend/flowerui/config_compat.py` | 新增类型强转与 validator 等价实现（可并入 config.py） | 中 |
| `backend/flowerui/core/celery_app.py` | 构造签名纳入 app.conf 注入值 | 中；避免导入期连接陈旧 broker |
| `backend/flowerui/services/runtime_config.py` | `RUNTIME_FILE` 默认路径；`load()` 跳过 app.conf 注入键 | 中 |
| `backend/flowerui/services/theme_manager.py` | `THEMES_DIR` 指向可写目录 + 首次播种 | 中 |
| `backend/flowerui/services/restart.py` | pip 模式降级，不再执行外部脚本 | 低 |
| `backend/flowerui/services/state.py` / DB 相关 | `flower.state*` / DB 落到 `FLOWERUI_HOME` | 中 |
| `backend/flowerui_cli.py` → `backend/flowerui/cli.py` | 新增 `-A`、app.conf 注入、去掉 chdir、新增 `main()` / `__main__.py` | **高**：核心需求 |
| `backend/celery_app.py`、`register_celery_command.py` | 保留，README 标注「仅源码开发用」 | 低 |
| `backend/pyproject.toml` | build-system（setuptools + 3.7 markers）、`[project]`、entry points、打包规则、`[tool.uv] package = false` | **高** |
| `backend/manage.sh` | 3 处 `app.main:app` + 1 处 `pkill -f` 特征替换 | 中；`bash -n` + 全命令回归 |
| `backend/tests/*`、`send_tasks.py`、`start_workers.py`、`_broker_env.py` | `from app.*` → `from flowerui.*` | 中；`pytest` 全量通过 |
| `backend/README.md`、根 `README.md`、`frontend/README.md` | 新增「pip 安装 / 复用已有 celery_app」章节；修正模块名 | 低 |
| `Dockerfile`、`docker-compose.yml` | 命令中的模块名 | 中 |
| `LICENSE`（新增）、`docs/pypi-release-plan.md`（本文） | 开源元数据与方案 | 低 |
| `.gitignore` | 保持忽略 `dist/`、`*.egg-info/`、`*.db`、`flower.state*`、`flowerui.runtime.toml` | 低 |

---

## 6. 分阶段实施与验证

| 阶段 | 内容 | 验证命令 / 判据 |
| --- | --- | --- |
| **P0 已完成** | 提交当前最新代码 | `726657c`，7 个文件；已同步远程 |
| **P1 已完成** | `git mv app flowerui` + 批量改入口字符串与导入 + CLI 移入包内 | 74 处替换；`bash -n` 三份 manage.sh 通过；`import flowerui.main` 成功（52 路由）；`celery -A celery_app flowerui --dry-run` 通过；`./manage.sh build` 同步到新 static 路径；脚本式检查 `test_events_flow` / `test_redis_connection` exit=0。**注意：本分支 `tests/` 全是脚本式检查、无 `test_` 函数，pytest 收集 0 用例（exit=5），历史里的 76 passed 属另一分支** |
| P2 兼容与路径 | 去 pydantic Settings、引入 `FLOWERUI_HOME`、去掉 chdir、主题目录播种 | 新增配置层单元测试；在 pydantic v1 / v2 两个 venv 各跑一次完整启动；确认不改动对方 pydantic 版本 |
| **P3 CLI 复用 app（已完成）** | `-A` 解析、app.conf 注入、优先级回归、独立命令 | 构造 `examples/demo_proj/celery.py`（broker 指向非默认地址 `6399/3`）；`celery -A examples.demo_proj.celery:app flowerui --dry-run` 显示注入值（broker/result_backend/transport_options/默认队列/路由）；`/api/system` broker 一致；显式 `--broker-url`、TOML、环境变量均能压过 app.conf；无 `-A` / 空 app 不继承、不改默认行为 |
| **P4 已完成** | pyproject（setuptools + 3.7 markers）、两个 entry point、静态资源、LICENSE、MANIFEST.in | `uv build --project backend` 成功；wheel 82 文件，含 `static/index.html` / `themes/base.css` / 两个 entry point，`Requires-Python: >=3.7`，无 runtime.toml / db / logs / `__pycache__` |
| **P5 部分完成（3.7）** | 全新 Python 3.7.9 venv 安装 wheel | `pip install` 成功（fastapi 0.103.2 / pydantic 1.10.27 / celery 5.2.7 / kombu 5.2.4 / importlib-metadata 4.13.0）；`celery --help` 列出 flowerui、`flowerui --help`、`python -m flowerui --help` 均可用；模拟第三方 app `-A demo_proj.celery:app` 启动 5561 后 8 个接口全 200、静态资源 200、无头浏览器完整渲染且控制台零错误。**pydantic v2 与 3.9+ 环境未验证（受 P2 阻塞）** |
| P6 预发布 | `twine check`、TestPyPI 上传与安装 | `pip install -i https://test.pypi.org/simple/ flowerui` 成功 |
| P7 正式发布 | PyPI 上传、打 tag、README 徽章与文档 | `https://pypi.org/project/flowerui/` 可访问；GitHub Release 与 tag 一致 |

---

## 7. 构建与发布流程（命令草案）

```bash
# 0) 同步前端产物到 flowerui/static（发布前必做）
./manage.sh build

# 1) 构建：uv 内置构建，隔离环境按 python_version markers 选择后端
#    （也可用 3.7 venv 里的 python -m build；产物均为 py3-none-any）
uv build --project backend --out-dir D:/Temp/flowerui-dist
python -m twine check D:/Temp/flowerui-dist/*

# 2) 干净 3.7 venv 安装验证（硬性目标版本）
py -3.7 -m venv D:/Temp/flowerui-verify37
D:/Temp/flowerui-verify37/Scripts/python -m pip install -i <镜像> D:/Temp/flowerui-dist/flowerui-0.1.0-py3-none-any.whl
D:/Temp/flowerui-verify37/Scripts/celery --help | grep flowerui
D:/Temp/flowerui-verify37/Scripts/flowerui --help

# 3) TestPyPI（强烈建议先走这一步）
TWINE_USERNAME=__token__ TWINE_PASSWORD=<testpypi-token> \
  python -m twine upload --repository testpypi D:/Temp/flowerui-dist/*

# 4) 正式发布
TWINE_USERNAME=__token__ TWINE_PASSWORD=<pypi-token> \
  python -m twine upload D:/Temp/flowerui-dist/*
```

- 需要 PyPI 账号 + 2FA + **API token**（`__token__` 作为用户名）；token 只放环境变量或 `~/.pypirc`（权限 600），
  **绝不进仓库**；本方案不要求也不建议把 token 交给自动化脚本硬编码。
- 上传前再核验一次 `https://pypi.org/pypi/flowerui/json` —— 包名目前空闲，但发布前仍可能被抢注。
- 可选：GitHub Actions 在打 tag 时自动 `build` + `twine upload`，token 走仓库 Secrets。

---

## 8. 风险与未决项

1. ~~包结构方案待定~~ **已解决**：方案 A 原地改造，已实施并回归。
2. ~~`requires-python >=3.9`~~ **已解决**：硬性 `>=3.7`。build-system 用 markers 双轨；
   wheel 在干净 3.7.9 venv 实测安装、启动、渲染成功。现代 Python 可用同一个 `py3-none-any` wheel，但尚未实测。
3. Celery 5.6.x 的 `celery.commands` entry point 加载方式需实测（当前只在 5.2.7 验证过手动注册）。
4. 去掉 BaseSettings 后，Settings 的强转行为必须逐项等价，否则 CSV/JSON/布尔配置会静默出错。
5. app.conf 注入与 `runtime.toml` 回放的先后顺序：必须让注入项登记为 CLI overrides，否则会被 TOML 盖回。
6. 静态资源已入库（26 文件），重命名时随 `git mv` 一起移动；每次发布前必须重新构建前端，否则前后端版本错配。
7. **安全**：`flowerui.runtime.toml` 含真实 Redis 凭据、`flower.state*` / `*.db` / `logs/` 属本地数据，
   wheel 与 sdist 都要显式排除；`default_settings.toml` 只能有占位示例。
8. 开源后 `/api/system/restart` 的行为变化要在 README 说明，避免用户以为按钮坏了。
9. ~~GitHub 推送被代理拦截~~ **已解决**：`726657c` 已同步远程；本轮新改动尚未提交。

---

## 9. 开工前验收清单

- [x] 确认 §4.1 包结构方案 → **A：原地改造 backend，已实施**
- [x] 确认 `requires-python` 下界 → **`>=3.7`（硬性），已实施并实测**
- [ ] 确认是否保留 `celery_app.py` / `register_celery_command.py` 作为源码开发辅助
- [ ] 确认「系统重启」在 pip 模式下的降级行为（推荐：返回提示，不 kill 进程）
- [ ] 准备 PyPI / TestPyPI 账号与 API token（仅 P6/P7 需要）
- [x] 恢复 GitHub 推送，把 `726657c` 同步到 `origin/import/other-machine`
- [ ] 决定是否新建发布专用分支（建议 `feat/pypi-package`），避免污染当前功能分支

---

## 10. 本轮实施记录（2026-11-05）

### 10.1 用户决策

| 决策项 | 结论 |
| --- | --- |
| 包结构 | **方案 A：原地把 `backend/app/` → `backend/flowerui/`** |
| Python 版本 | **必须使用 3.7**：`requires-python = ">=3.7"`，本地 3.7.9 与 wheel 安装环境都保持 3.7 |

### 10.2 已完成的文件改动

- `git mv backend/app backend/flowerui`（66 个文件保留 rename 历史），19 个文件共 74 处引用替换，
  另单独补齐 4 处：`Dockerfile` 的 `COPY` 路径、`frontend/manage.sh` 的目录检测、
  两处 `from app.services import ...`（空格形式未被批量规则命中）。
- **刻意未改**：`mock.py` 里的模拟任务名 `app.tasks.*`、`e2e_check.py` 里的同名断言、
  伪造 traceback 路径 `/app/celery/app/trace.py`、容器路径 `/app/examples`（都不是 Python 模块引用）。
- `git mv backend/flowerui_cli.py backend/flowerui/cli.py`：新增 `SOURCE_MODE` 判断，
  **安装模式不再 `chdir` 到 site-packages、也不注入 sys.path**；`_static_index()` 改为读包内 `static`；
  新增 `main()` 与 `__main__.py`；`register_celery_command.py` 的 entry point 同步改为 `flowerui.cli:flowerui` 并重跑注册。
- `backend/pyproject.toml`：build-system 用 `python_version` markers 双轨
  （3.7 → `setuptools>=61,<68` + `wheel<0.43`；>=3.8 → 现代版本），`[project] name=flowerui`、
  `requires-python>=3.7`、两个 entry point、显式 `packages` + `package-data`（static/themes）；
  保留 `[tool.uv] package = false`，`uv.lock` 只把根包名从 `flowerui-backend` 改为 `flowerui`，
  `uv sync --frozen --offline` 校验一致，**3.7 锁定依赖未被重新解析**。
- 新增 `LICENSE`（根 + backend 各一份）、`backend/MANIFEST.in`、`backend/flowerui/__init__.py` 的 `__version__`。
- `events.py`：旧 `flower.state` 里的 pickle 仍写着 `app.*`，反序列化会失败；
  现在给出明确的「一次性迁移」提示，状态重建后 `save_state()` 会用新模块名覆盖，属自愈。
- 清理：把历史遗留的 `backend/nul`（Windows 保留名调试文件，已 gitignore）移到 `D:/Temp/flowerui-nul-legacy.txt`，
  它曾让 Python 3.7 的 `pathlib.stat()` 抛 `WinError 1`、阻断 pytest 收集。

### 10.3 实测结果

| 项目 | 结果 |
| --- | --- |
| `uv build --project backend` | 成功：`flowerui-0.1.0-py3-none-any.whl`（979 KB）+ sdist（954 KB） |
| wheel 内容 | 82 文件；含 `flowerui/static/index.html`、15 个主题、LICENSE、两个 entry point；`Requires-Python: >=3.7`；无 `runtime.toml` / `*.db` / `logs/` / `__pycache__` |
| 干净 3.7.9 venv | `pip install` 成功，解析到 fastapi 0.103.2 / pydantic 1.10.27 / celery 5.2.7 / kombu 5.2.4 / importlib-metadata 4.13.0，与本地 uv.lock 的 3.7 分支一致 |
| 命令入口 | `celery --help` 列出 `flowerui`；`flowerui --help`；`python -m flowerui --help` 全部可用 |
| 模拟第三方项目 | `celery -A demo_proj.celery:app flowerui --port 5561 --mock` 成功启动；`/`、`/index.html`、`/api/config`、`/api/auth/config`、`/api/themes`、`/api/dashboard/summary`、`/api/workers/table`、`/healthcheck` 全 200；JS 静态资源 200 |
| 浏览器渲染 | 无头 Edge 打开 5561：标题、侧边栏、统计卡片、图表完整，`appHtmlLength=47533`，控制台 / 网络零报错 |
| 本地源码回归 | `bash -n` 三份 manage.sh 通过；`import flowerui.main` 52 路由；`celery -A celery_app flowerui --dry-run` 通过；`./manage.sh build` 同步到新 static（26 文件）；`tests/test_events_flow.py`、`tests/test_redis_connection.py` exit=0 |
| 测试口径 | 当前分支 `tests/` 全是脚本式检查（无 `test_` 函数），`pytest -q` 收集 0 用例（exit=5）；历史记录里的 76 passed 属于另一分支 |

### 10.4 仍未完成（下一阶段）

1. **P2 剩余**：配置层去 pydantic 化（去掉 `BaseSettings` 对 pydantic v1 的硬依赖）。
   注意：**用户提出的「运行时文件落在执行目录、项目目录优先包内兜底」已在 2026-11-05 晚间落地**
   （见 §10.5），当前 0.1.0 已具备：配置 TOML 分层回退、主题「项目目录覆盖 + 包兜底」、上传写项目目录、
   启动自动建目录。完成去 pydantic 化前，0.1.0 装进 pydantic v2 项目仍会降级对方依赖，建议先发 TestPyPI。
2. **P5 补测**：pydantic v2 环境、Python 3.9+ 环境、`twine check`、TestPyPI 上传。
3. **P6/P7**：正式上传 PyPI，需要账号 API token（`__token__`），不要写进仓库。

### 10.5 分层回退落地（2026-11-05 晚间）

用户决策：**所有运行时写入（配置 / 主题上传）都落在执行代码的当前目录，目录不存在就自动创建；
读取采用「项目目录下有就用项目目录的，没有就使用包中的」两层回退。** 已实施并实测。

**新增 `backend/flowerui/paths.py`**（仅依赖标准库，可被 Celery `--help` 安全导入）：
- `work_dir()`：默认 `Path.cwd()`，可用 `FLOWERUI_WORK_DIR` 覆盖。
- `runtime_file()`：界面配置存档 `flowerui.runtime.toml`，始终落在工作目录（**绝不写 site-packages**）。
- `settings_toml()`：**读取回退**——工作目录优先，没有则回退包内随源码 / wheel 分发的模板。
- `themes_dir()`：用户主题目录（覆盖层，可写），工作目录 `/themes`。
- `BUILTIN_THEMES_DIR`：包内只读内置主题；`seed_builtin_themes()` 可选地把内置主题复制到覆盖层。

**改造点**：
- `core/config.py`：`SETTINGS_TOML_PATH` 硬编码（上溯三级）改为 `paths.settings_toml()`，配置读取走分层回退。
- `services/theme_manager.py`：移除写死的包目录常量，改为 `user_themes_dir()`（覆盖层）+ `BUILTIN_THEMES_DIR`（兜底层）；
  `scan()` 合并两层（项目目录同名覆盖包内置）、`get_css()` 做兜底、`upload/delete` 只作用于项目目录、
  首次启动在覆盖层播种 `base.css` / `_template.css`；`delete()` 用 `os.remove` 以兼容 Python 3.7（避开 pathlib.unlink 的 shim 包装）。
- `api/routers/themes.py`：列表接口返回的 `dir` 改为 `user_themes_dir()`。
- `.gitignore`：新增 `backend/themes/`（覆盖层运行时目录，内置主题仍在 `backend/flowerui/themes/` 随仓库分发）。

**实测（源码 venv 3.7.9 + 干净安装 venv 3.7.9 两种模式）**：
- 内置主题（aurora / salt-ocean 等）在「工作目录无 themes」时仍通过包兜底可见，标记 `builtin=True`；
- 上传的主题落盘到**工作目录** `themes/`，`site-packages/flowerui/themes/` 未被写入（验证只读层不被污染）；
- 删除只删工作目录副本；在工作目录放 `flowerui-settings.toml` 时优先于包内模板被读取；
- runtime 配置、主题目录均落在工作目录，目录缺失自动创建。

> 建议：0.1.0 先只发 TestPyPI 做验证，等 P2/P3 完成后再正式发布 0.2.0，
> 避免把「会降级用户 pydantic」的版本推到 PyPI（PyPI 不允许覆盖同名版本）。

### 10.6 P3 实施记录（CLI 复用用户 app.conf）

用户决策：**FlowerUI 应能自动从用户已有的 Celery app（`-A` 指向的那个）继承 broker / result backend /
transport options / 默认队列 / 路由，无需在 FlowerUI 侧重复配置连接信息。**

**新增 `backend/examples/demo_proj/`**（第三方 Celery 项目示例，不进 wheel）：
- `celery.py` 中 app 的 `broker_url=redis://127.0.0.1:6399/3`、result backend `6399/4`、
  `broker_transport_options={"master_name":"mymaster"}`、`task_default_queue="demo_priority_queue"`、
  `task_routes={...}` —— 全部指向**非默认**地址，专门用来验证「配置自动继承」是否生效。

**改造 `backend/flowerui/cli.py`**：
- 新增 `_resolve_user_app(ctx, app_spec)`：两条路径取得用户 app。
  * 独立命令 `flowerui -A proj.celery:app`：`app_spec` 来自命令自身的 `-A/--app` 选项，用 `find_app()` 加载；
  * Celery 子命令 `celery -A proj.celery:app flowerui`：`-A` 被根命令消费后，加载到的 app 挂在
    `ctx.obj.app`（CLIContext）；用 `root.params['app']` 是否为 `None` 判断用户是否**显式**传了 `-A`
    （未传时 `ctx.obj.app` 只是默认 app，不应继承）。
- 新增 `_app_conf_overrides(app)`：只用 `app.conf.without_defaults()` 里出现的键提取
  `broker_url` / `result_backend` / `broker_transport_options` / `task_default_queue` / `task_routes`，
  并额外过滤掉与 **Celery 默认值**（如 `redis://127.0.0.1:6379/0`、`task_default_queue="celery"`）相等的项——
  celery CLI 在加载 app 时可能把默认值带进 `without_defaults()`，若不加这道网会用默认值去盖掉
  用户在 TOML / 环境变量里认真配的值。`None` / 空 dict / 空字符串同样跳过。
- 覆盖项合并顺序：`app.conf 继承项 < 显式 option（--broker-url/--result-backend 等） < --set/位置参数`，
  全部再经 `runtime_config.set_cli_overrides()` 登记，使运行时 TOML 回放跳过这些键；
  同时写入 `FLOWERUI_CLI_OVERRIDES` 供 `--reload` / `--workers` 子进程回放。
- dry-run 与启动横幅新增「复用 app.conf」行，打印被继承的 app 名与键名，便于确认生效。

**优先级（已落地并实测）**：
```
显式 CLI 参数  >  用户 celery app.conf  >  flowerui.runtime.toml 回放
             >  FLOWER_* 环境变量  >  flowerui-settings.toml  >  代码默认值
```

**实测**：
- `celery -A examples.demo_proj.celery:app flowerui --dry-run`：broker 显示为继承值 `redis://127.0.0.1:6399/3`
  （不再是默认 `6379/0`），`复用 app.conf: 是（third_party_demo）继承 broker_transport_options、broker_url、
  result_backend、task_default_queue、task_routes`。
- `flowerui -A examples.demo_proj.celery:app --dry-run`（独立命令）：同样正确继承。
- 显式 `--broker-url redis://127.0.0.1:7000/9` 能压过 app.conf；无 `-A` 时 `复用 app.conf: 否`，
  broker 回退到默认/配置值，行为完全不变（向后兼容）。
- 空 app（不设任何连接配置）：`复用 app.conf: 否`，不会被 Celery 默认值覆盖。
- 局部 app（只设 broker_url）：仅继承 broker_url，FlowerUI 自身的 task_default_queue 等配置保留。
- 真实启动（`--mock` 端口 5599）：日志显示 `运行时配置回放跳过命令行已覆盖的项: broker_transport_options,
  broker_url, mock, port, result_backend, task_default_queue, task_routes`，`/api/config` 与 `/api/system`
  均返回继承的 `redis://127.0.0.1:6399/3`，满足验收标准 #3（broker 与第三方项目一致、无需重复配置）。
