"""FlowerUI 的 Celery 子命令：``celery -A celery_app flowerui [OPTIONS]``。

本模块通过 ``celery.commands`` entry point 被 Celery 5.x（click 插件机制）
发现，因此**模块顶层只依赖标准库与 click**：Celery 在构建 ``--help`` 时就会
导入所有插件，此时工作目录、项目配置都未必就绪，任何项目内导入都可能把整条
CLI 拖垮（click_plugins 会把加载失败的插件显示成 BrokenCommand）。

职责：
1. 把命令行参数解析成「配置覆盖项」；
2. 以**最高优先级**应用到 Settings / runtime_config；
3. 用 uvicorn 启动 ``app.main:app``。

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

# 本文件位于 backend/，也是 app 包与 flowerui.runtime.toml 的所在目录
BACKEND_DIR = Path(__file__).resolve().parent

# 供 uvicorn 子进程 / reload 子进程复用 CLI 覆盖项
CLI_OVERRIDES_ENV = "FLOWERUI_CLI_OVERRIDES"


def _prepare_runtime() -> None:
    """保证能 import 项目模块，并把 cwd 固定到 backend/。

    ``runtime_config.RUNTIME_FILE`` 按当前工作目录解析，若不 chdir，
    在别处执行 ``celery ... flowerui`` 会读到一份错误的运行时配置。
    """
    path = str(BACKEND_DIR)
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
    """按 app.main 的同一套规则定位前端构建产物。"""
    configured = os.environ.get("FLOWER_FRONTEND_DIST")
    root = Path(configured) if configured else BACKEND_DIR / "app" / "static"
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


def _mask(key: str, value: Any) -> str:
    """dry-run 输出用的简易脱敏，避免把密码打进终端/日志。"""
    if key in ("secret_key", "oauth2_secret"):
        return "******"
    if key == "basic_auth":
        return ", ".join("%s:******" % str(x).split(":", 1)[0] for x in (value or []))
    text = str(value)
    if key in ("broker_url", "result_backend", "broker_api"):
        try:
            from app.core.celery_app import mask_url_password
            return mask_url_password(text)
        except Exception:  # pragma: no cover - dry-run 不依赖项目可用性
            pass
    return text


_EPILOG = """\b
示例：
  celery -A celery_app flowerui
  celery -A celery_app flowerui --port 5555 --broker-url redis://127.0.0.1:6379/0
  celery -A celery_app flowerui --mock --set debug=true --set max_tasks=200
  celery -A celery_app flowerui --port 6001 mock=true ui_transport=polling
  celery -A celery_app flowerui --port 5555 --dry-run

注意：-A/-b 等 Celery 全局选项必须写在子命令 flowerui 之前。
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
@click.option("--broker-url", default=None,
              help="Celery broker URL；未给时沿用 Celery 全局 -b/--broker")
@click.option("--result-backend", default=None,
              help="结果后端 URL")
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

    from app.services import runtime_config  # 项目导入延迟到此处

    if list_keys:
        click.echo("可用配置键（--set KEY=VALUE / 位置参数 KEY=VALUE）：")
        for field in runtime_config.FIELDS:
            click.echo("  %-28s %-8s %s" % (field.key, field.type, field.label))
        return

    if reload and workers and workers > 1:
        raise click.UsageError("--reload 与 --workers > 1 不能同时使用")

    # 1) 组装覆盖项：显式 option 优先，--set / 位置参数随后
    overrides: Dict[str, Any] = {}
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

    from app.core.config import settings

    if dry_run:
        # 回放运行时 TOML，让预览反映真正启动后的生效配置；CLI 覆盖项会被
        # load() 跳过，因此这一步同时验证了「命令行 > TOML」的优先级。
        replayed = False
        if runtime_config.RUNTIME_FILE.exists():
            runtime_config.load()
            replayed = True
        click.echo("FlowerUI 启动参数（dry-run，未启动服务）")
        click.echo("  工作目录:   %s" % BACKEND_DIR)
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
        click.echo("  broker:     %s" % _mask("broker_url", settings.broker_url))
        click.echo("  演示模式:   %s" % settings.mock)
        return

    # 4) 启动 uvicorn（用字符串形式，reload/workers 才能正常工作）
    import uvicorn

    page_url = _public_url(settings.host, settings.port, getattr(settings, "url_prefix", ""))
    click.echo("FlowerUI 启动中")
    click.echo("  页面地址:   %s   <- 浏览器打开这个地址" % page_url)
    click.echo("  监听绑定:   %s:%s" % (settings.host, settings.port))
    click.echo("  配置覆盖:   %d 项（命令行参数优先级最高）" % len(applied))
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
        "app.main:app",
        host=settings.host,
        port=int(settings.port),
        log_level=log_level.lower(),
        reload=reload,
        workers=workers or None,
    )


if __name__ == "__main__":  # 便于直接 python flowerui_cli.py --help 调试
    flowerui()
