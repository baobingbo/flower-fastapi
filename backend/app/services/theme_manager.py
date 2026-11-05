"""主题目录管理：扫描、播种、读取、写入、监控。

设计
----
- 主题目录（THEMES_DIR）下的每个 ``*.css``（除 ``base.css`` 与 ``_`` 开头的文件）
  即一个用户主题。``base.css`` 是公共令牌默认值，其它主题用 ``@import './base.css'`` 复用。
- 系统内置的 4 套主题仍走前端打包（registry），这里只管理「运行时新增」的主题，
  因此扫描结果天然不会与内置主题重复。
- 后台线程每 2 秒轮询目录签名，发生变化时通过 WebSocket 广播 ``themes_updated``，
  前端据此刷新主题列表——这就是「系统监控到主题增加」的实现。
- 首次运行会在目录下播种 ``base.css`` 与 ``_template.css``，保证用户随时能拿到模板。
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .hub import hub

logger = logging.getLogger("flowerui.themes")

THEMES_DIR = Path(
    os.environ.get(
        "FLOWER_THEMES_DIR",
        # 主题目录随后端一起分发：backend/app/themes/（上传的新主题也落在这里）
        str(Path(__file__).resolve().parents[1] / "themes"),
    )
).resolve()

# 内置主题 id（走前端打包，目录扫描时跳过，避免重复）。
# 现在只保留 light/dark；tech-liquid/aurora 已迁移到主题目录（运行时发现）。
BUILTIN_IDS = {"light", "dark"}

BASE_CSS = """/**
 * base.css —— 主题公共令牌默认值（浅色基线）
 * ------------------------------------------------------------------
 * 所有自定义主题都 @import 本文件，然后只覆盖自己要改的令牌即可。
 * 新增主题无需改动任何组件样式——组件只认 --fu-* 令牌。
 *
 * 分组：surface / line / text / brand / status / effect / code /
 *       scrollbar / menu / chart
 */
:root {
  /* -- surface -- */
  --fu-bg: #f4f6fa;
  --fu-surface: #ffffff;
  --fu-surface-2: #f7f8fb;
  --fu-card: #ffffff;
  --fu-card-hover: #fafbfe;
  --fu-mask: rgba(15, 20, 34, 0.45);
  --fu-app-bg-image: none;
  --fu-aside-bg-image: none;
  --fu-card-bg-image: none;

  /* -- line -- */
  --fu-border: #e6e9f0;
  --fu-border-strong: #d3d8e4;

  /* -- text -- */
  --fu-text: #1f2430;
  --fu-text-secondary: #4d5468;
  --fu-text-muted: #7a8299;
  --fu-text-inverse: #ffffff;

  /* -- brand -- */
  --fu-brand: #3f7ef8;
  --fu-brand-hover: #5b93ff;
  --fu-brand-active: #2f68d8;
  --fu-brand-soft: rgba(63, 126, 248, 0.1);
  --fu-brand-contrast: #ffffff;

  /* -- status -- */
  --fu-success: #22a565;
  --fu-success-soft: rgba(34, 165, 101, 0.12);
  --fu-warning: #e6a23c;
  --fu-warning-soft: rgba(230, 162, 60, 0.13);
  --fu-danger: #e2564d;
  --fu-danger-soft: rgba(226, 86, 77, 0.12);
  --fu-info: #8a93a8;
  --fu-info-soft: rgba(138, 147, 168, 0.13);

  /* -- effect -- */
  --fu-shadow-sm: 0 1px 2px rgba(20, 28, 48, 0.05);
  --fu-shadow: 0 4px 16px rgba(20, 28, 48, 0.07);
  --fu-shadow-lg: 0 12px 40px rgba(20, 28, 48, 0.12);
  --fu-blur: 0px;
  --fu-glass-saturate: 100%;
  --fu-glow: none;
  --fu-card-inner-line: transparent;

  /* -- code -- */
  --fu-code-bg: #f7f8fb;
  --fu-code-text: #2c3140;

  /* -- scrollbar -- */
  --fu-scrollbar-thumb: #cdd3e0;
  --fu-scrollbar-thumb-hover: #b3bacb;

  /* -- menu -- */
  --fu-menu-text: #4d5468;
  --fu-menu-hover-bg: rgba(63, 126, 248, 0.07);
  --fu-menu-active-bg: rgba(63, 126, 248, 0.12);
  --fu-menu-active-text: #3f7ef8;

  /* -- chart -- */
  --fu-chart-1: #3f7ef8;
  --fu-chart-2: #22a565;
  --fu-chart-3: #e6a23c;
  --fu-chart-4: #e2564d;
  --fu-chart-5: #9254de;
  --fu-chart-6: #12b5cb;
  --fu-chart-axis: #9aa2b6;
  --fu-chart-split: rgba(140, 150, 175, 0.18);
}
"""

TEMPLATE_CSS = """/**
 * 主题模板 —— 复制本文件，按注释修改后改个文件名（xxx.css）上传即可。
 * 文件名（去掉 .css）就是主题 id，必须与下方 [data-theme='xxx'] 的 xxx 一致。
 *
 * 文件顶部可用注释声明元数据（均可选，缺省时系统自动推导）：
 *   name:    自定义主题        ← 切换器里显示的名字
 *   desc:    一句话描述        ← 切换器里的副标题
 *   scheme:  light | dark     ← 控制滚动条/原生控件配色（也可在下方写 color-scheme）
 *   glass:   true | false     ← 是否启用液态玻璃增强层（配合 --fu-blur 等）
 *   swatch:  #f4f6fa,#ffffff,#3f7ef8  ← 切换器上的三色预览（背景/卡片/主色）
 */
@import './base.css';   /* 公共令牌默认值，所有主题共用，请勿删除此行 */

[data-theme='my-theme'] {
  color-scheme: light;          /* 与 scheme 元数据二选一即可 */

  /* 只写要覆盖的令牌；其余全部继承 base.css。
     例如「极光晨曦」和「浅色」基本一致，就只改下面这几行。 */
  --fu-brand: #6c5ce7;
  --fu-brand-hover: #8071f5;
  --fu-brand-active: #5849c9;
  --fu-brand-soft: rgba(108, 92, 231, 0.12);
  --fu-brand-contrast: #ffffff;

  --fu-bg: #f6f5fb;
  --fu-surface: #ffffff;
  --fu-surface-2: #f3f1fa;

  /* 想要玻璃质感就打开下面几行，并把 glass 元数据设为 true */
  /* --fu-blur: 16px; */
  /* --fu-glow: 0 0 20px rgba(108, 92, 231, 0.22); */
  /* --fu-glass-saturate: 150%; */
}
"""

# 注释里的元数据行：兼容 ` * name: xxx`（标准模板）与 `name: xxx`（简写）两种写法
_HEADER_RE = re.compile(r"^\s*\*?\s*(name|desc|scheme|glass|swatch)\s*:\s*(.+?)\s*$", re.M)
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]+\.css$")
_DATA_THEME_RE = re.compile(r"\[data-theme\s*=\s*['\"]?([A-Za-z0-9_-]+)['\"]?\]")


def _seed() -> None:
    THEMES_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in (("base.css", BASE_CSS), ("_template.css", TEMPLATE_CSS)):
        dest = THEMES_DIR / name
        if not dest.exists():
            dest.write_text(content, encoding="utf-8")
            logger.info("已播种主题文件: %s", dest)


def _parse_meta(text: str, fallback_id: str) -> Dict[str, Any]:
    meta = {k: None for k in ("name", "desc", "scheme", "glass", "swatch")}
    for m in _HEADER_RE.finditer(text):
        meta[m.group(1)] = m.group(2).strip()

    scheme = meta["scheme"]
    if scheme not in ("light", "dark"):
        scheme = "dark" if re.search(r"color-scheme\s*:\s*dark", text) else "light"

    glass = meta["glass"]
    if glass is None:
        m = re.search(r"--fu-blur\s*:\s*([\d.]+)px", text)
        glass = bool(m and float(m.group(1)) > 0)
    else:
        glass = str(glass).lower() in ("1", "true", "yes", "on")

    swatch = meta["swatch"]
    if not swatch:
        def _tok(name_: str) -> str:
            # 兜底只取 hex，避免 rgba(...) 内的逗号把 swatch 切坏
            mm = re.search(rf"--{name_}\s*:\s*(#[0-9a-fA-F]{{3,8}})", text)
            return mm.group(1) if mm else "#cccccc"
        swatch = ",".join(_tok(n) for n in ("fu-bg", "fu-surface", "fu-brand"))

    name = meta["name"] or fallback_id.replace("-", " ").title()
    desc = meta["desc"] or ""

    return {
        "id": fallback_id,
        "name": name,
        "desc": desc,
        "scheme": scheme,
        "glass": bool(glass),
        "swatch": [c.strip() for c in swatch.split(",")][:3],
        "builtin": fallback_id in BUILTIN_IDS,
        "url": f"/api/themes/files/{fallback_id}.css",
    }


def scan() -> List[Dict[str, Any]]:
    """扫描目录，返回全部用户主题（已排除内置 id 与 base/_ 文件）。"""
    _seed()
    out: List[Dict[str, Any]] = []
    for p in sorted(THEMES_DIR.glob("*.css")):
        if p.name == "base.css" or p.name.startswith("_"):
            continue
        if p.stem in BUILTIN_IDS:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        meta = _parse_meta(text, p.stem)
        out.append(meta)
    return out


def get_css(filename: str) -> Optional[str]:
    if not _SAFE_NAME.match(filename):
        return None
    p = THEMES_DIR / filename
    if p.exists() and p.is_file():
        return p.read_text(encoding="utf-8", errors="ignore")
    return None


def upload(filename: str, content: str) -> Dict[str, Any]:
    """保存一个用户上传的主题，返回其元数据。"""
    name = os.path.basename(filename)
    if not _SAFE_NAME.match(name):
        raise ValueError("文件名只能包含字母、数字、下划线和连字符，且必须以 .css 结尾")
    if name == "base.css" or name.startswith("_"):
        raise ValueError("base.css 与 _ 开头的文件为系统保留，不能上传")
    theme_id = name[:-4]
    if theme_id in BUILTIN_IDS:
        raise ValueError(f"主题 id「{theme_id}」为系统内置保留名，请换一个名字")

    if not _DATA_THEME_RE.search(content):
        raise ValueError("CSS 中需要包含 [data-theme='xxx'] 选择器（xxx 与文件名一致）")

    dest = THEMES_DIR / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    _notify()
    return _parse_meta(content, theme_id)


def delete(theme_id: str) -> None:
    if theme_id in BUILTIN_IDS:
        raise ValueError(f"主题「{theme_id}」为系统内置，不可删除")
    p = THEMES_DIR / f"{theme_id}.css"
    if not p.exists():
        raise FileNotFoundError(f"主题「{theme_id}」不存在")
    p.unlink()
    _notify()


# --------------------------------------------------------------------------
# 目录监控（轮询 + WebSocket 广播）
# --------------------------------------------------------------------------
_watcher: Optional[threading.Thread] = None
_last_sig: Optional[str] = None
_lock = threading.Lock()


def _signature() -> str:
    try:
        parts = [
            f"{p.name}:{p.stat().st_mtime}:{p.stat().st_size}"
            for p in THEMES_DIR.glob("*.css")
        ]
        return "|".join(sorted(parts))
    except OSError:
        return ""


def _notify() -> None:
    try:
        hub.publish_threadsafe({"type": "themes_updated"})
    except Exception:  # noqa: BLE001
        logger.debug("主题变更广播失败（可能尚无 WebSocket 订阅者）")


def _watch() -> None:
    global _last_sig
    _last_sig = _signature()
    while True:
        time.sleep(2)
        sig = _signature()
        if sig != _last_sig:
            _last_sig = sig
            _notify()


def start_watcher() -> None:
    global _watcher
    with _lock:
        if _watcher is None or not _watcher.is_alive():
            _seed()
            _watcher = threading.Thread(target=_watch, daemon=True, name="theme-watcher")
            _watcher.start()
            logger.info("主题目录监控已启动: %s", THEMES_DIR)
