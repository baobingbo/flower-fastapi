"""运行时数据目录：上传、保存、读取配置一律落在「执行代码的当前目录」。

约定
----
1. **默认目录就是 ``Path.cwd()``**：在哪执行启动命令，运行时文件就写在哪。
   源码开发时 CLI 会先 ``chdir`` 到 ``backend/``，pip 安装时保持用户项目目录，
   两种方式都不往 ``site-packages``（通常只读）里写东西。
2. **目录不存在就自动创建**：``ensure_dir()`` / ``ensure_parent()`` 统一负责，
   调用方写文件前只需调一次，不必各处重复 ``mkdir``。
3. 随 wheel 分发的 ``static/`` 与 ``themes/`` 是**只读模板**，不是运行时目录；
   首次启动把内置主题播种到运行目录的 ``themes/``，之后上传、修改、删除
   都只作用于运行目录，用户数据与包内容互不干扰。
4. 已存在的环境变量仍可用（相对路径也按运行目录解析），便于容器/多实例部署：
   ``FLOWERUI_WORK_DIR`` / ``FLOWER_RUNTIME_CONFIG_FILE`` /
   ``FLOWER_THEMES_DIR`` / ``FLOWER_SETTINGS_FILE``。

本模块只依赖标准库，可被 ``flowerui.cli`` 在 Celery 构建 ``--help`` 时安全导入。
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Iterable, List, Optional, Union

logger = logging.getLogger("flowerui.paths")

# 随包分发的只读资源（模板），绝不写入
PACKAGE_DIR = Path(__file__).resolve().parent
BUILTIN_THEMES_DIR = PACKAGE_DIR / "themes"
BUILTIN_STATIC_DIR = PACKAGE_DIR / "static"

ENV_WORK_DIR = "FLOWERUI_WORK_DIR"
ENV_RUNTIME_FILE = "FLOWER_RUNTIME_CONFIG_FILE"
ENV_THEMES_DIR = "FLOWER_THEMES_DIR"
ENV_SETTINGS_FILE = "FLOWER_SETTINGS_FILE"

RUNTIME_FILE_NAME = "flowerui.runtime.toml"
SETTINGS_FILE_NAME = "flowerui-settings.toml"
THEMES_DIR_NAME = "themes"

PathLike = Union[str, Path]


def _absolute(path: PathLike, base: Optional[PathLike] = None) -> Path:
    """把相对路径按 base（默认运行目录）解析成绝对路径。"""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path(base) if base is not None else work_dir()
        p = p / Path(path).expanduser()
    return p.resolve()


def work_dir() -> Path:
    """运行目录（惰性求值：模块导入时 cwd 可能尚未被 CLI 固定）。"""
    configured = (os.environ.get(ENV_WORK_DIR) or "").strip()
    if configured:
        return _absolute(configured, base=Path.cwd())
    return Path.cwd().resolve()


def ensure_dir(path: PathLike) -> Path:
    """确保目录存在（含多级父目录），返回同一路径。"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def ensure_parent(path: PathLike) -> Path:
    """确保文件的父目录存在，返回原路径（不改变调用方的路径语义）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def runtime_file() -> Path:
    """界面修改的配置存档 ``flowerui.runtime.toml``。"""
    configured = (os.environ.get(ENV_RUNTIME_FILE) or "").strip()
    if configured:
        return _absolute(configured)
    return work_dir() / RUNTIME_FILE_NAME


def themes_dir() -> Path:
    """用户主题目录（上传 / 删除 / 扫描都在这里）。"""
    configured = (os.environ.get(ENV_THEMES_DIR) or "").strip()
    if configured:
        return _absolute(configured)
    return work_dir() / THEMES_DIR_NAME


def data_file(name: PathLike) -> Path:
    """运行时数据文件（``flower.state`` 等）；相对路径按运行目录解析。"""
    return _absolute(name)


def settings_toml() -> Path:
    """静态默认配置的读取位置：优先运行目录，其次随源码分发的模板。

    pip 安装模式下包旁没有这份模板（默认值写在代码里），此时返回运行目录
    下的路径；用户只要把 ``flowerui-settings.toml`` 放在执行目录就会被读取。
    这里是「读取」，因此不创建文件、也不复制模板。
    """
    configured = (os.environ.get(ENV_SETTINGS_FILE) or "").strip()
    if configured:
        return _absolute(configured)
    local = work_dir() / SETTINGS_FILE_NAME
    if local.is_file():
        return local
    bundled = PACKAGE_DIR.parent / SETTINGS_FILE_NAME  # 源码模式：backend/
    if bundled.is_file():
        return bundled
    return local


def seed_builtin_themes(
    target: PathLike,
    skip_names: Iterable[str] = (),
) -> List[str]:
    """把包内内置主题播种到运行目录，只补不覆盖，返回新复制的文件名列表。

    ``skip_names`` 用于跳过用户已经删除的内置主题，避免重启后「复活」。
    """
    dest_dir = ensure_dir(target)
    skipped = set(skip_names or ())
    copied: List[str] = []
    if not BUILTIN_THEMES_DIR.is_dir():
        logger.warning("内置主题模板目录不存在: %s", BUILTIN_THEMES_DIR)
        return copied
    for src in sorted(BUILTIN_THEMES_DIR.glob("*.css")):
        if src.name in skipped:
            continue
        dest = dest_dir / src.name
        if dest.exists():
            continue
        try:
            shutil.copyfile(str(src), str(dest))
            copied.append(src.name)
        except OSError as exc:
            logger.warning("内置主题播种失败 %s: %s", src.name, exc)
    return copied
