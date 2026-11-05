"""数据库初始化模块。"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from .users_db import init_db as _init_users_db

logger = logging.getLogger(__name__)


def init_database() -> None:
    """初始化所有数据库。"""
    # 确保数据库目录存在
    db_path = Path(__file__).parent.parent.parent.parent / "flowerui.db"
    if not db_path.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 初始化用户数据库
    _init_users_db()
    logger.info("数据库初始化完成")
