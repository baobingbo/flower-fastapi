"""FlowerUI 的 Celery 子命令：``celery -A <app> flowerui [OPTIONS]``。

本模块位于 ``flowerui`` 包内，通过 ``[project.entry-points."celery.commands"]``
被 Celery 5.x（click 插件机制）发现；源码开发时也可用
``register_celery_command.py`` 手动注册同一个入口点。

模块顶层**只依赖标准库与 click**：Celery 在构建 ``--help`` 时就会导入所有插件，
此时工作目录、项目配置都未必就绪，任何项目内导入都可能把整条 CLI 拖垮
（click_plugins 会把加载失败的插件显示成 BrokenCommand）。

职责：
1. 把命令行参数解析成「配置覆盖项」；
2. 以**最高优先级**应用到 Settings / runtime_config；
3. 用 uvicorn 启动 ``flowerui.main:app``。

优先级（高 → 低）：命令行参数 > flowerui.runtime.toml 回放 >
FLOWER_* 环境变量 > flowerui-settings.toml > 代码默认值。

之所以需要专门的覆盖通道：``runtime_config.load()`` 在 FastAPI lifespan 阶段
会回放运行时 TOML 并直接 ``setattr(settings, ...)``，若只在进程里改 settings，
启动后就会被 TOML 里的旧值盖回去。``set_cli_overrides()`` 会让 load() 跳过
这些键；同时把覆盖项写进环境变量，供 ``--reload`` / ``--workers`` 子进程复用。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import click

# 本文件位于 flowerui/ 包内。源码开发时其上级就是 backend/（含 manage.sh
# 与 flowerui-settings.toml）；pip 安装后位于 site-packages/flowerui/。
PACKAGE_DIR = Path(__file__).resolve().parent
SOURCE_DIR = PACKAGE_DIR.parent
SOURCE_MODE = (SOURCE_DIR / "manage.sh").is_file() or (
    SOURCE_DIR / "flowerui-settings.toml").is_file()
BACKEND_DIR = SOURCE_DIR if SOURCE_MODE else PACKAGE_DIR

# 供 uvicorn 子进程 / reload 子进程复用 CLI 覆盖项
CLI_OVERRIDES_ENV = "FLOWERUI_CLI_OVERRIDES"


def _prepare_runtime() -> None:
    """源码模式下固定 cwd 与 sys.path；安装模式下一律不改。

    ``runtime_config.RUNTIME_FILE`` 按当前工作目录解析，源码模式若不 chdir
    到 backend/，在别处执行 ``celery ... flowerui`` 会读到错误的运行时配置。
    pip 安装模式下包已在 site-packages（通常只读），既不需要注入 sys.path，
    也不能把用户项目的工作目录改掉 —— 保持用户自己的 cwd。
    """
    if not SOURCE_MODE:
        return
    path = str(SOURCE_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        os.chdir(path)
    except OSError:  # pragma: no cover - 只读文件系统等极端场景
        pass


def _public_url(host: Any, port: Any, url_prefix: Any = "") -> str:
    """生成「可以直接贴进浏览器」的页面地址。

    配置里的 ``0.0.0.0`` / ``::`` 表示"绑定所有网卡"，不是可访问的目标地址；
    把它原样打给用户，浏览器（尤其被系统代理接管时）会打开失败或显示空白页。
    另外，前端静态资源与 API 由同一端口托管，这里也要把 url_prefix 带上。
    """
    display_host = str(host or "127.0.0.1").strip()
    if display_host in ("0.0.0.0", "::", "*", ""):
        display_host = "127.0.0.1"
    if ":" in display_host and not display_host.startswith("["):  # IPv6 字面量
        display_host = "[%s]" % display_host
    prefix = str(url_prefix or "").strip().rstrip("/")
    if prefix and not prefix.startswith("/"):
        prefix = "/" + prefix
    return "http://%s:%s%s/" % (display_host, port, prefix)


def _static_index() -> Path:
    """按 flowerui.main 的同一套规则定位前端构建产物（随 wheel 分发）。"""
    configured = os.environ.get("FLOWER_FRONTEND_DIST")
    root = Path(configured) if configured else PACKAGE_DIR / "static"
    return root / "index.html"


def _parse_pairs(items: Iterable[str]) -> Dict[str, Any]:
    """解析 ``KEY=VALUE`` / ``--KEY=VALUE`` 形式的通用配置覆盖。"""
    out: Dict[str, Any] = {}
    for item in items or ():
        text = str(item).strip()
        if not text:
            continue
        if "=" not in text:
            raise click.BadParameter(
                "配置覆盖必须写成 KEY=VALUE（例如 --set debug=true 或 mock=true），"
                "收到：%s" % text
            )
        key, value = text.split("=", 1)
        key = key.strip().lstrip("-").strip()
        if not key:
            raise click.BadParameter("配置覆盖的键名不能为空：%s" % text)
        out[key] = value.strip()
    return out


def _global_broker(ctx: click.Context) -> Optional[str]:
    """读取 Celery 全局 ``-b/--broker``（写在子命令之前）的值。"""
    try:
        root = ctx.find_root()
        return (getattr(root, "params", None) or {}).get("broker") or None
    except Exception:  # pragma: no cover - 不同 celery 版本参数名可能不同
        return None


# 仅从用户 app.conf 继承的键；这些键在 FlowerUI 的 Settings 上都有对应字段。
_APP_CONF_KEYS = (
    "broker_url",
    "result_backend",
    "broker_transport_options",
    "task_default_queue",
    "task_routes",
)

# 兜底用：当 ``conf.without_defaults()`` 不可用时，跳过与 Celery 默认值相等的项，
# 避免把默认 broker 当成用户配置去盖掉 TOML / 环境变量里认真配的值。
_CELERY_DEFAULTS = {
    "broker_url": "redis://127.0.0.1:6379/0",
    "result_backend": None,
    "task_default_queue": "celery",
    "broker_transport_options": {},
    "task_routes": {},
}


def _resolve_user_app(ctx: click.Context, app_spec: Optional[str]) -> Optional[object]:
    """解析用户已有的 Celery app，供 app.conf 配置继承使用。

    两条来源路径：

    1. 独立命令 ``flowerui -A proj.celery:app``：``app_spec`` 来自 flowerui
       命令自身的 ``-A/--app`` 选项，用 ``find_app`` 加载。
    2. Celery 子命令 ``celery -A proj.celery:app flowerui``：``-A`` 是 celery
       根命令的全局选项（写在子命令之前），由根命令加载后挂在 ``ctx.obj.app``
       （CLIContext）；是否显式传了 ``-A`` 用 ``root.params['app']`` 判断
       （未传时为 ``None``，此时 ``ctx.obj.app`` 只是默认 app，不应继承）。

    返回 Celery app 实例；无法解析或未显式指定时返回 ``None``（不继承，行为不变）。
    """
    if app_spec:
        try:
            from celery.app.utils import find_app
            return find_app(app_spec)
        except Exception as exc:  # 用户填错的模块 / 属性
            raise click.BadParameter(
                "无法加载 Celery 应用 %r：%s" % (app_spec, exc)
            ) from exc
    try:
        root = ctx.find_root()
        obj = getattr(root, "obj", None)
        root_app = getattr(obj, "app", None)
        # root.params['app'] 为 None 表示用户没传 -A（此时是默认 app，不要继承）
        if root_app is not None and root.params.get("app") is not None:
            return root_app
    except Exception:  # pragma: no cover - 不同 celery 版本上下文结构不同
        return None
    return None


def _app_conf_overrides(app: Optional[object]) -> Dict[str, Any]:
    """从用户 celery app.conf 提取「显式设置」的连接配置。

    只用 ``conf.without_defaults()`` 里出现的键，并额外过滤掉与 Celery 默认值
    相等的项：celery CLI 在加载 app 时可能把 ``task_default_queue="celery"`` 之类
    的默认值带进 ``without_defaults()``，若不加这道网，会用默认值去盖掉用户在
    TOML / 环境变量里认真配的 broker / 队列。过滤掉 ``None`` / 空 dict /
    空字符串后返回 ``{key: value}``。``without_defaults()`` 不可用时退化为读
    ``conf`` 并同样跳过与 Celery 默认值相等的项。
    """
    if app is None:
        return {}
    try:
        try:
            wd = app.conf.without_defaults()
        except Exception:  # pragma: no cover - 极老 celery 版本
            wd = app.conf
        getter = wd.get if isinstance(wd, dict) else (lambda k: app.conf.get(k))
    except Exception:  # pragma: no cover - app.conf 不可用
        return {}

    out: Dict[str, Any] = {}
    for key in _APP_CONF_KEYS:
        try:
            val = getter(key)
        except Exception:  # pragma: no cover - 个别键读取异常
            continue
        if val is None:
            continue
        if isinstance(val, (dict, list)) and not val:
            continue
        if isinstance(val, str) and not val.strip():
            continue
        # 安全网：等于 Celery 默认值（且非用户真正显式配置）的项不继承，
        # 避免用默认值覆盖 TOML / 环境变量里的值。
        if val == _CELERY_DEFAULTS.get(key):
            continue
        out[key] = val
    return out


def _mask(key: str, value: Any) -> str:
    """dry-run 输出用的简易脱敏，避免把密码打进终端/日志。"""
    if key in ("secret_key", "oauth2_secret"):
        return "******"
    if key == "basic_auth":
        return ", ".join("%s:******" % str(x).split(":", 1)[0] for x in (value or []))
    text = str(value)
    if key in ("broker_url", "result_backend", "broker_api"):
        try:
            from flowerui.core.celery_app import mask_url_password
            return mask_url_password(text)
        except Exception:  # pragma: no cover - dry-run 不依赖项目可用性
            pass
    return text


_EPILOG = """\b
示例：
  celery -A celery_app flowerui
  celery -A celery_app flowerui --port 5555 --broker-url redis://127.0.0.1:6379/0
  celery -A their_project.celery:app flowerui          # 自动复用对方 app.conf 的 broker / result backend / 路由
  flowerui -A their_project.celery:app --port 5555     # 独立命令同样自动复用 app.conf
  celery -A celery_app flowerui --mock --set debug=true --set max_tasks=200
  celery -A celery_app flowerui --port 6001 mock=true ui_transport=polling
  celery -A celery_app flowerui --port 5555 --dry-run

注意：-A/-b 等 Celery 全局选项必须写在子命令 flowerui 之前。
      作为 celery 子命令时，-A 由 celery 根命令解析，flowerui 会自动从加载到的
      app.conf 继承 broker_url / result_backend / broker_transport_options /
      task_default_queue / task_routes（仅取显式设置项，不会覆盖你用 --broker-url、
      TOML 或环境变量配的值）。独立命令则用 flowerui 自身的 -A/--app 选项。
      子命令支持任意配置项覆盖（--set KEY=VALUE 或位置参数 KEY=VALUE），
      键名可用 `celery -A celery_app flowerui --list-keys` 查看。
"""


@click.command(
    name="flowerui",
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
        "help_option_names": ["-h", "--help"],
    },
    epilog=_EPILOG,
    help="启动 FlowerUI Web 监控面板（FastAPI + uvicorn）。",
)
@click.option("--host", "--address", "host", default=None,
              help="监听地址（默认取配置 host）")
@click.option("--port", "-p", type=int, default=None,
              help="监听端口（默认取配置 port）")
@click.option("-A", "--app", "app", default=None,
              help="复用已有 Celery 应用的模块路径（独立命令用，如 proj.celery:app）；"
                   "作为 celery 子命令时 -A 写在 flowerui 之前、由 celery 根命令解析，无需此选项")
@click.option("--broker-url", default=None,
              help="Celery broker URL；未给时依次沿用 全局 -b / 用户 app.conf / 配置")
@click.option("--result-backend", default=None,
              help="结果后端 URL；未给时沿用用户 app.conf / 配置")
@click.option("--broker-transport-options", default=None,
              help="broker 传输选项，JSON 字符串，如 '{\"master_name\": \"mymaster\"}'")
@click.option("--mock/--no-mock", default=None,
              help="强制演示模式 / 强制真实集群")
@click.option("--debug/--no-debug", default=None,
              help="开启 / 关闭 DEBUG 日志")
@click.option("--basic-auth", multiple=True,
              help="登录凭据 user:pass，可重复；也可写 --set basic_auth=a:1,b:2")
@click.option("--basic-auth-enabled/--no-basic-auth-enabled", default=None,
              help="开启 / 关闭登录凭证管理")
@click.option("--url-prefix", default=None,
              help="反向代理子路径前缀")
@click.option("--runtime-config", "runtime_config_path", default=None,
              type=click.Path(),
              help="指定 flowerui.runtime.toml 路径（等价于 FLOWER_RUNTIME_CONFIG_FILE）")
@click.option("--set", "set_pairs", multiple=True, metavar="KEY=VALUE",
              help="覆盖任意配置项，可重复")
@click.option("--list-keys", is_flag=True,
              help="列出所有可用配置键及说明后退出")
@click.option("--dry-run", is_flag=True,
              help="只打印生效配置，不启动服务")
@click.option("--log-level", default="info",
              type=click.Choice(["critical", "error", "warning", "info",
                                 "debug", "trace"], case_sensitive=False),
              help="uvicorn 日志级别（默认 info）")
@click.option("--reload", is_flag=True,
              help="开启 uvicorn 热更新（开发用）")
@click.option("--workers", type=int, default=None,
              help="uvicorn worker 进程数（不能与 --reload 同用）")
@click.pass_context
def flowerui(
    ctx: click.Context,
    host: Optional[str],
    port: Optional[int],
    app: Optional[str],
    broker_url: Optional[str],
    result_backend: Optional[str],
    broker_transport_options: Optional[str],
    mock: Optional[bool],
    debug: Optional[bool],
    basic_auth: Iterable[str],
    basic_auth_enabled: Optional[bool],
    url_prefix: Optional[str],
    runtime_config_path: Optional[str],
    set_pairs: Iterable[str],
    list_keys: bool,
    dry_run: bool,
    log_level: str,
    reload: bool,
    workers: Optional[int],
) -> None:
    """启动 FlowerUI；所有参数都是可选的，不传时沿用现有 TOML / 环境变量配置。"""
    _prepare_runtime()

    from flowerui.services import runtime_config  # 项目导入延迟到此处

    if list_keys:
        click.echo("可用配置键（--set KEY=VALUE / 位置参数 KEY=VALUE）：")
        for field in runtime_config.FIELDS:
            click.echo("  %-28s %-8s %s" % (field.key, field.type, field.label))
        return

    if reload and workers and workers > 1:
        raise click.UsageError("--reload 与 --workers > 1 不能同时使用")

    # 0) 复用用户已有 Celery app 的 conf：仅取「显式设置」的连接配置，
    #    优先级低于下面的显式 option 与 --set / 位置参数，但高于 TOML / 环境变量。
    #    没传 -A（或 -A 指向的 app 未配 broker 等）时返回 {}，行为完全不变。
    user_app = _resolve_user_app(ctx, app)
    app_conf = _app_conf_overrides(user_app)

    # 1) 组装覆盖项：app.conf < 显式 option < --set / 位置参数
    overrides: Dict[str, Any] = {}
    overrides.update(app_conf)  # 用户 app.conf 注入（见 §4.3）
    if host is not None:
        overrides["host"] = host
    if port is not None:
        overrides["port"] = port
    if broker_url is not None:
        overrides["broker_url"] = broker_url
    else:
        global_broker = _global_broker(ctx)
        if global_broker:
            overrides["broker_url"] = global_broker
    if result_backend is not None:
        overrides["result_backend"] = result_backend
    if broker_transport_options is not None:
        overrides["broker_transport_options"] = broker_transport_options
    if mock is not None:
        overrides["mock"] = mock
    if debug is not None:
        overrides["debug"] = debug
    if basic_auth:
        overrides["basic_auth"] = ",".join(basic_auth)
    if basic_auth_enabled is not None:
        overrides["basic_auth_enabled"] = basic_auth_enabled
    if url_prefix is not None:
        overrides["url_prefix"] = url_prefix

    pairs = dict(_parse_pairs(set_pairs))
    pairs.update(_parse_pairs(ctx.args))  # 位置参数优先级高于 --set
    overrides.update(pairs)

    # 2) 运行时配置文件路径（需在 runtime_config 读取 RUNTIME_FILE 前生效）
    if runtime_config_path:
        path = Path(runtime_config_path).expanduser().resolve()
        os.environ["FLOWER_RUNTIME_CONFIG_FILE"] = str(path)
        runtime_config.RUNTIME_FILE = path

    # 3) 环境变量先写，供 --reload / --workers 子进程自动回放；
    #    主进程再显式应用一次（此时 runtime_config 可能已被 -A 提前导入）。
    if overrides:
        os.environ[CLI_OVERRIDES_ENV] = json.dumps(overrides, ensure_ascii=False)
        try:
            applied = runtime_config.set_cli_overrides(overrides)
        except runtime_config.ConfigError as exc:
            raise click.UsageError(str(exc)) from exc
    else:
        applied = {}

    from flowerui.core.config import settings

    if dry_run:
        # 回放运行时 TOML，让预览反映真正启动后的生效配置；CLI 覆盖项会被
        # load() 跳过，因此这一步同时验证了「命令行 > TOML」的优先级。
        replayed = False
        if runtime_config.RUNTIME_FILE.exists():
            runtime_config.load()
            replayed = True
        click.echo("FlowerUI 启动参数（dry-run，未启动服务）")
        click.echo("  工作目录:   %s" % Path.cwd())
        click.echo(
            "  运行时配置: %s%s"
            % (runtime_config.RUNTIME_FILE, "（已回放）" if replayed else "（文件不存在，将生成模板）")
        )
        click.echo("  页面地址:   %s" % _public_url(
            settings.host, settings.port, getattr(settings, "url_prefix", "")))
        click.echo("  监听绑定:   %s:%s" % (settings.host, settings.port))
        click.echo("  命令行覆盖 (%d 项，优先级最高):" % len(applied))
        if applied:
            for key in sorted(applied):
                click.echo("    %-28s %s" % (key, _mask(key, applied[key])))
        else:
            click.echo("    (无，全部沿用 TOML / 环境变量)")
        # 展示 app.conf 继承情况，便于确认「复用已有 celery_app」是否生效
        if app_conf:
            app_label = getattr(user_app, "main", None) or app or "(celery -A)"
            click.echo("  复用 app.conf: 是（%s）继承 %s"
                       % (app_label, "、".join(sorted(app_conf))))
        else:
            click.echo("  复用 app.conf: 否（未指定 -A 或该 app 未显式配置连接项）")
        click.echo("  broker:     %s" % _mask("broker_url", settings.broker_url))
        click.echo("  演示模式:   %s" % settings.mock)
        return

    # 4) 启动 uvicorn（用字符串形式，reload/workers 才能正常工作）
    import uvicorn

    page_url = _public_url(settings.host, settings.port, getattr(settings, "url_prefix", ""))
    click.echo("FlowerUI 启动中")
    click.echo("  页面地址:   %s   <- 浏览器打开这个地址" % page_url)
    click.echo("  监听绑定:   %s:%s" % (settings.host, settings.port))
    if app_conf:
        app_label = getattr(user_app, "main", None) or app or "(celery -A)"
        click.echo("  复用 app.conf: 是（%s），继承 %s"
                   % (app_label, "、".join(sorted(app_conf))))
    click.echo("  配置覆盖:   %d 项（命令行参数优先级最高，其次 app.conf）" % len(applied))
    if not _static_index().exists():
        click.echo(
            "  [警告] 前端未构建：%s 不存在，打开页面只会看到提示 JSON。"
            "请先执行 ./manage.sh build" % _static_index(),
            err=True,
        )
    else:
        click.echo("  说明:       前端页面与 API 同一端口；5556 仅是 Vite 开发端口，"
                   "只有 ./manage.sh dev 才会启动。")
    uvicorn.run(
        "flowerui.main:app",
        host=settings.host,
        port=int(settings.port),
        log_level=log_level.lower(),
        reload=reload,
        workers=workers or None,
    )


def main() -> None:
    """独立命令入口（``flowerui`` / ``python -m flowerui``）。

    与 Celery 子命令共用同一个 click command；Celery 全局 ``-A`` 只在
    ``celery -A <app> flowerui`` 路径下可用，独立命令请用自身的
    ``-A/--app`` 选项复用已有 Celery app 的 conf（broker / result backend /
    路由等），如 ``flowerui -A their_project.celery:app --port 5555``。
    """
    flowerui()


if __name__ == "__main__":  # 便于直接 python flowerui/cli.py --help 调试
    main()
