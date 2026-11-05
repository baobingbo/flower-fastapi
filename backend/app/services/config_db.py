"""SQLite 运行时配置存储服务。

设计要点
--------
1. 与 users_db 共用同一 SQLite 数据库，便于统一管理和事务控制。
2. 表结构采用扁平化 key-value 存储，支持 secret 标记和分组。
3. 记录变更历史，便于审计和回滚。
4. 提供迁移功能，从旧版 .env 文件自动导入数据。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.config import resolve_db_path, settings

logger = logging.getLogger(__name__)

# 表名常量
CONFIG_KEYS_TABLE = "config_keys"
CONFIG_HISTORY_TABLE = "config_history"


@contextmanager
def _get_conn(db_path: Optional[str] = None):
    """获取 SQLite 连接上下文管理器（相对路径锚定 backend 目录）。"""
    path = db_path or str(resolve_db_path(settings.db_path))
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """将 sqlite3.Row 转换为字典。"""
    if row is None:
        return None
    return dict(row)


def init_config_tables() -> None:
    """初始化配置相关的数据库表。"""
    with _get_conn() as conn:
        cursor = conn.cursor()

        # 创建配置键值表
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {CONFIG_KEYS_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL DEFAULT '',
                secret INTEGER NOT NULL DEFAULT 0,
                "group" TEXT NOT NULL DEFAULT 'default',
                editable INTEGER NOT NULL DEFAULT 1,
                restart_required INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)

        # 创建配置历史表
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {CONFIG_HISTORY_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                changed_by TEXT DEFAULT 'system',
                changed_at REAL NOT NULL
            )
        """)

        # 创建索引以提高查询性能
        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_config_keys_key 
            ON {CONFIG_KEYS_TABLE}(key)
        """)
        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_config_keys_group 
            ON {CONFIG_KEYS_TABLE}("group")
        """)
        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_config_history_key 
            ON {CONFIG_HISTORY_TABLE}(key)
        """)
        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_config_history_changed_at 
            ON {CONFIG_HISTORY_TABLE}(changed_at)
        """)

        logger.info("配置数据库表初始化完成")


def migrate_from_env(env_file: Optional[Path] = None) -> int:
    """从旧的 .env 文件迁移配置到 SQLite。

    Args:
        env_file: .env 文件路径，默认为 flowerui.runtime.env

    Returns:
        迁移的配置项数量
    """
    if env_file is None:
        env_file = Path(settings.db_path).parent / "flowerui.runtime.env"

    if not env_file.exists():
        logger.info("未找到旧版 .env 文件，跳过迁移")
        return 0

    logger.info(f"开始从 {env_file} 迁移配置到 SQLite")

    count = 0
    with _get_conn() as conn:
        cursor = conn.cursor()

        # 读取 .env 文件
        try:
            lines = env_file.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            logger.error(f"读取 .env 文件失败: {e}")
            return 0

        now = time.time()

        for line in lines:
            line = line.strip()
            # 跳过空行和注释
            if not line or line.startswith("#"):
                continue

            # 解析 KEY=VALUE 格式
            if "=" not in line:
                continue

            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()

            # 移除引号
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1]

            # 判断是否为 secret
            secret = 1 if key in ("secret_key", "oauth2_client_secret", "oauth2_secret") else 0

            # 判断是否需要重启
            restart_required = 1 if key in ("host", "port", "url_prefix", "broker_url") else 0

            # 尝试推断分组
            group = "default"
            if key in ("host", "port", "url_prefix", "cors_origins"):
                group = "service"
            elif key in ("broker_url", "result_backend", "inspect_timeout"):
                group = "celery"
            elif key in ("max_workers", "max_tasks"):
                group = "capacity"

            # 插入或更新
            cursor.execute(f"""
                INSERT OR REPLACE INTO {CONFIG_KEYS_TABLE}
                (key, value, secret, "group", editable, restart_required, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?, ?)
            """, (key, value, secret, group, restart_required, now, now))

            # 记录历史
            cursor.execute(f"""
                INSERT INTO {CONFIG_HISTORY_TABLE}
                (key, old_value, new_value, changed_by, changed_at)
                VALUES (?, NULL, ?, 'migration', ?)
            """, (key, value, now))

            count += 1

        logger.info(f"迁移完成: {count} 项配置已从 .env 导入到 SQLite")

    return count


def get_config(key: str) -> Optional[Dict[str, Any]]:
    """获取单个配置项。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT key, value, secret, "group", editable, restart_required
            FROM {CONFIG_KEYS_TABLE}
            WHERE key = ?
        """, (key,))
        row = cursor.fetchone()
        if row:
            return _row_to_dict(row)
    return None


def get_all_configs(group: Optional[str] = None) -> List[Dict[str, Any]]:
    """获取所有配置项，可按分组过滤。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        if group:
            cursor.execute(f"""
                SELECT key, value, secret, "group", editable, restart_required
                FROM {CONFIG_KEYS_TABLE}
                WHERE "group" = ?
                ORDER BY key
            """, (group,))
        else:
            cursor.execute(f"""
                SELECT key, value, secret, "group", editable, restart_required
                FROM {CONFIG_KEYS_TABLE}
                ORDER BY "group", key
            """)
        return [_row_to_dict(r) for r in cursor.fetchall()]


def set_config(
    key: str,
    value: str,
    secret: bool = False,
    group: str = "default",
    editable: bool = True,
    restart_required: bool = False,
    changed_by: str = "system"
) -> Dict[str, Any]:
    """设置或更新配置项。"""
    now = time.time()

    with _get_conn() as conn:
        cursor = conn.cursor()

        # 获取旧值用于历史记录
        cursor.execute(f"""
            SELECT value FROM {CONFIG_KEYS_TABLE} WHERE key = ?
        """, (key,))
        old_row = cursor.fetchone()
        old_value = old_row[0] if old_row else None

        # 插入或更新
        cursor.execute(f"""
            INSERT INTO {CONFIG_KEYS_TABLE}
            (key, value, secret, "group", editable, restart_required, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                secret = excluded.secret,
                "group" = excluded."group",
                editable = excluded.editable,
                restart_required = excluded.restart_required,
                updated_at = excluded.updated_at
        """, (
            key,
            value,
            1 if secret else 0,
            group,
            1 if editable else 0,
            1 if restart_required else 0,
            now,
            now
        ))

        # 记录历史
        if old_value != value:
            cursor.execute(f"""
                INSERT INTO {CONFIG_HISTORY_TABLE}
                (key, old_value, new_value, changed_by, changed_at)
                VALUES (?, ?, ?, ?, ?)
            """, (key, old_value, value, changed_by, now))

        logger.info(f"配置已更新: {key}")

    return get_config(key)


def delete_config(key: str) -> bool:
    """删除配置项。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            DELETE FROM {CONFIG_KEYS_TABLE} WHERE key = ?
        """, (key,))
        deleted = cursor.rowcount > 0

        if deleted:
            cursor.execute(f"""
                INSERT INTO {CONFIG_HISTORY_TABLE}
                (key, old_value, new_value, changed_by, changed_at)
                VALUES (?, NULL, NULL, 'delete', ?)
            """, (key, time.time()))
            logger.info(f"配置已删除: {key}")

    return deleted


def get_history(key: str, limit: int = 50) -> List[Dict[str, Any]]:
    """获取配置项的变更历史。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT key, old_value, new_value, changed_by, changed_at
            FROM {CONFIG_HISTORY_TABLE}
            WHERE key = ?
            ORDER BY changed_at DESC
            LIMIT ?
        """, (key, limit))
        return [_row_to_dict(r) for r in cursor.fetchall()]


def get_all_history(limit: int = 100) -> List[Dict[str, Any]]:
    """获取最近的配置变更历史。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT key, old_value, new_value, changed_by, changed_at
            FROM {CONFIG_HISTORY_TABLE}
            ORDER BY changed_at DESC
            LIMIT ?
        """, (limit,))
        return [_row_to_dict(r) for r in cursor.fetchall()]


def reset_all_configs() -> int:
    """重置所有配置为默认值。

    Returns:
        删除的配置项数量
    """
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM {CONFIG_KEYS_TABLE}")
        deleted = cursor.rowcount

        now = time.time()
        cursor.execute(f"""
            INSERT INTO {CONFIG_HISTORY_TABLE}
            (key, old_value, new_value, changed_by, changed_at)
            VALUES ('__all__', NULL, NULL, 'reset', ?)
        """, (now,))

        logger.info(f"配置已重置，删除了 {deleted} 项")

    return deleted
