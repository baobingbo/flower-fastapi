"""把 ``flowerui`` 注册为 Celery 子命令（零网络、零构建工具、可重复执行）。

Celery 5.2.x 用 ``click_plugins.with_plugins(entry_points().get('celery.commands'))``
发现子命令，也就是说命令必须来自一个**已安装的 distribution**。而本项目按设计
是 uv 的 virtual project（pyproject.toml 刻意没有 build-system，Python 3.7 也
不适合再引入 setuptools 构建链），所以这里直接往当前 venv 的 site-packages
写一个最小的 ``.dist-info`` + ``.pth``：

* ``flowerui_backend-0.1.0.dist-info/entry_points.txt`` → 声明 celery.commands 入口
* ``flowerui_backend.pth`` → 把 backend/ 加入 sys.path，使 celery 能 import
  ``flowerui_cli``、``celery_app`` 和 ``app`` 包

这等价于一次 editable install，但不联网、不改 pyproject.toml / uv.lock，
也不影响现有的 ``./manage.sh`` 启动链路。

用法（在 backend/ 下，用项目自己的解释器）：
    .venv/Scripts/python.exe register_celery_command.py            # 注册
    .venv/Scripts/python.exe register_celery_command.py --check    # 只检查
    .venv/Scripts/python.exe register_celery_command.py --uninstall

注意：重建/重装 venv 后需要再执行一次注册（uv sync 可能重建 site-packages）。
"""
from __future__ import annotations

import os
import sys
import sysconfig
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
DIST_NAME = "flowerui_backend"
DIST_VERSION = "0.1.0"
DIST_INFO_NAME = "%s-%s.dist-info" % (DIST_NAME, DIST_VERSION)
PTH_NAME = "%s.pth" % DIST_NAME
ENTRY_POINT_TEXT = "[celery.commands]\nflowerui = flowerui_cli:flowerui\n"

# uv 0.12.3 在 Windows + Python 3.7 下生成的 console script（celery.exe、
# uvicorn.exe）会把自身当 Python 源码执行，Git Bash / PowerShell 都报
# "SyntaxError: Non-UTF-8 code starting with '\xf6'"。Git Bash 会优先查找
# 无扩展名命令，故在 venv/Scripts 放一个 shim，直接走 python -m celery。
CELERY_SHIM_NAME = "celery"
CELERY_SHIM_TEXT = """#!/usr/bin/env bash
# FlowerUI 注册脚本生成：绕过 uv 在 Windows + Python 3.7 下损坏的 celery.exe
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$HERE/python.exe" -m celery "$@"
"""
METADATA_TEXT = (
    "Metadata-Version: 2.1\n"
    "Name: flowerui-backend\n"
    "Version: %s\n"
    "Summary: FlowerUI celery command registration\n" % DIST_VERSION
)


def _site_packages() -> Path:
    return Path(sysconfig.get_paths()["purelib"])


def register() -> Path:
    """写入 dist-info 与 .pth，返回 dist-info 目录。"""
    sp = _site_packages()
    sp.mkdir(parents=True, exist_ok=True)
    dist_info = sp / DIST_INFO_NAME
    dist_info.mkdir(parents=True, exist_ok=True)

    (dist_info / "METADATA").write_text(METADATA_TEXT, encoding="utf-8")
    (dist_info / "entry_points.txt").write_text(ENTRY_POINT_TEXT, encoding="utf-8")
    (dist_info / "INSTALLER").write_text("flowerui-register\n", encoding="utf-8")
    (sp / PTH_NAME).write_text(str(BACKEND_DIR) + "\n", encoding="utf-8")

    # Git Bash 的 celery shim（与 python.exe 同目录；bash 会优先选中无扩展名
    # 文件，从而绕开损坏的 celery.exe）。直接用 sys.executable 定位最可靠，
    # purelib 在不同平台上层级并不固定。
    scripts_dir = Path(sys.executable).resolve().parent
    shim = scripts_dir / CELERY_SHIM_NAME
    # py3.7 的 Path.write_text 没有 newline 参数；必须显式写 LF，
    # 否则 Windows 会把 shebang 写成 CRLF 导致 Git Bash 找不到解释器。
    with open(str(shim), "w", encoding="utf-8", newline="\n") as f:
        f.write(CELERY_SHIM_TEXT)
    try:
        os.chmod(str(shim), 0o755)
    except OSError:  # pragma: no cover - Windows 文件系统可能忽略权限位
        pass
    return dist_info


def check() -> bool:
    """在新进程里确认 entry point 能被 Celery 发现。"""
    try:
        try:
            from importlib.metadata import entry_points  # py3.8+
        except ImportError:
            from importlib_metadata import entry_points  # py3.7 backport
        eps = entry_points()
        # importlib_metadata 4.x 的 dict 接口已弃用，优先用 select()
        try:
            candidates = eps.select(group="celery.commands")
        except AttributeError:  # pragma: no cover - 更老的实现
            candidates = eps.get("celery.commands", [])
        found = [ep for ep in candidates if ep.name == "flowerui"]
    except Exception as exc:  # pragma: no cover - 环境缺依赖
        print("检查失败: %s" % exc)
        return False
    if not found:
        print("未发现 celery.commands/flowerui，请先执行注册")
        return False
    ep = found[0]
    print("已注册: %s -> %s" % (ep.name, ep.value))
    try:
        cmd = ep.load()
        print("命令加载成功: %s (%s)" % (cmd.name, type(cmd).__name__))
    except Exception as exc:
        print("入口点存在但加载失败: %s" % exc)
        return False
    return True


def uninstall() -> None:
    """移除注册文件（不动项目源码）。"""
    sp = _site_packages()
    dist_info = sp / DIST_INFO_NAME
    if dist_info.is_dir():
        for f in dist_info.iterdir():
            if f.is_file():
                f.unlink()
        dist_info.rmdir()
    pth = sp / PTH_NAME
    if pth.is_file():
        pth.unlink()
    shim = Path(sys.executable).resolve().parent / CELERY_SHIM_NAME
    if shim.is_file():
        shim.unlink()
    print("已移除注册: %s" % dist_info)


def main() -> int:
    args = sys.argv[1:]
    if "--uninstall" in args:
        uninstall()
        return 0
    if "--check" in args:
        return 0 if check() else 1

    dist_info = register()
    print("site-packages: %s" % _site_packages())
    print("dist-info:     %s" % dist_info)
    print("sys.path 注入: %s" % BACKEND_DIR)
    print("注册完成。现在可用：")
    print("  celery -A celery_app flowerui --help")
    return 0


if __name__ == "__main__":
    sys.exit(main())
