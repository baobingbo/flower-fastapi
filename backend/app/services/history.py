"""历史数据归档服务：SQLite 持久化任务执行历史。"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class HistoryStore:
    """SQLite 历史存储，记录任务执行历史供后续查询。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def init(self) -> None:
        """创建历史表（tasks, workers, events）。"""
        self.conn = sqlite3.connect(self.db_path)
        cursor = self.conn.cursor()

        # 任务执行历史表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                name TEXT,
                state TEXT,
                worker TEXT,
                received REAL,
                started REAL,
                runtime REAL,
                result TEXT,
                traceback TEXT,
                created_at REAL
            )
        """)

        # Worker 心跳历史表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS workers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_name TEXT,
                status TEXT,
                timestamp REAL,
                active INTEGER DEFAULT 0,
                processed INTEGER DEFAULT 0
            )
        """)

        # 事件历史表（保留重要事件）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT,
                worker_name TEXT,
                task_id TEXT,
                task_name TEXT,
                timestamp REAL,
                data TEXT
            )
        """)

        # 创建索引以加速查询
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_worker ON tasks(worker)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_received ON tasks(received)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_workers_timestamp ON workers(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")

        self.conn.commit()
        logger.info("历史存储初始化完成: %s", self.db_path)

    def save_task(
        self,
        task_id: str,
        name: str,
        state: str,
        worker: Optional[str],
        received: Optional[float],
        started: Optional[float],
        runtime: Optional[float],
        result: Optional[str],
    ) -> None:
        """保存任务执行记录。"""
        if not self.conn:
            return

        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO tasks
                (task_id, name, state, worker, received, started, runtime, result, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task_id,
                name,
                state,
                worker,
                received,
                started,
                runtime,
                result,
                time.time(),
            ))
            self.conn.commit()
        except Exception as exc:
            logger.debug("保存任务历史失败: %s", exc)

    def get_tasks(
        self,
        limit: int = 100,
        offset: int = 0,
        state: Optional[str] = None,
        worker: Optional[str] = None,
        task_name: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """查询历史任务列表。"""
        if not self.conn:
            return []

        try:
            cursor = self.conn.cursor()
            conditions = []
            params = []

            if state:
                conditions.append("state = ?")
                params.append(state)
            if worker:
                conditions.append("worker = ?")
                params.append(worker)
            if task_name:
                conditions.append("name = ?")
                params.append(task_name)
            if start_time:
                conditions.append("received >= ?")
                params.append(start_time)
            if end_time:
                conditions.append("received <= ?")
                params.append(end_time)

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            cursor.execute(f"""
                SELECT task_id, name, state, worker, received, started, runtime, result
                FROM tasks
                {where_clause}
                ORDER BY received DESC
                LIMIT ? OFFSET ?
            """, params + [limit, offset])

            rows = cursor.fetchall()
            return [
                {
                    "task_id": row[0],
                    "name": row[1],
                    "state": row[2],
                    "worker": row[3],
                    "received": row[4],
                    "started": row[5],
                    "runtime": row[6],
                    "result": row[7],
                }
                for row in rows
            ]
        except Exception as exc:
            logger.debug("查询历史任务失败: %s", exc)
            return []

    def get_timeline(
        self,
        task_name: Optional[str] = None,
        start: Optional[float] = None,
        end: Optional[float] = None,
        interval_seconds: int = 60,
    ) -> List[Dict[str, Any]]:
        """查询时间线数据（按时间段聚合）。"""
        if not self.conn:
            return []

        try:
            cursor = self.conn.cursor()
            conditions = []
            params = []

            if task_name:
                conditions.append("name = ?")
                params.append(task_name)
            if start:
                conditions.append("received >= ?")
                params.append(start)
            if end:
                conditions.append("received <= ?")
                params.append(end)

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            cursor.execute(f"""
                SELECT
                    CAST(received / ? * ? AS INTEGER) * (? / ?) as bucket,
                    state,
                    COUNT(*) as count
                FROM tasks
                {where_clause}
                GROUP BY bucket, state
                ORDER BY bucket
            """, params + [interval_seconds, interval_seconds, interval_seconds, interval_seconds])

            rows = cursor.fetchall()
            result = []
            for row in rows:
                result.append({
                    "timestamp": row[0],
                    "state": row[1],
                    "count": row[2],
                })
            return result
        except Exception as exc:
            logger.debug("查询时间线失败: %s", exc)
            return []

    def cleanup(self, retention_days: int = 7) -> int:
        """清理过期数据，返回删除的记录数。"""
        if not self.conn:
            return 0

        try:
            cutoff = time.time() - (retention_days * 86400)  # 秒

            cursor = self.conn.cursor()

            # 删除过期的任务
            cursor.execute("DELETE FROM tasks WHERE received < ?", (cutoff,))
            tasks_deleted = cursor.rowcount

            # 删除过期的事件
            cursor.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
            events_deleted = cursor.rowcount

            # 删除过期的 worker 记录（保留最近 30 天）
            worker_cutoff = time.time() - (30 * 86400)
            cursor.execute("DELETE FROM workers WHERE timestamp < ?", (worker_cutoff,))
            workers_deleted = cursor.rowcount

            self.conn.commit()
            total = tasks_deleted + events_deleted + workers_deleted
            logger.info("清理历史数据: 任务%d, 事件%d, worker记录%d",
                       tasks_deleted, events_deleted, workers_deleted)
            return total
        except Exception as exc:
            logger.debug("清理历史数据失败: %s", exc)
            return 0

    def close(self) -> None:
        """关闭数据库连接。"""
        if self.conn:
            self.conn.close()
            self.conn = None


# 全局单例
_history_store: Optional[HistoryStore] = None


def get_history_store(db_path: Path) -> HistoryStore:
    """获取或创建全局历史存储实例。"""
    global _history_store
    if _history_store is None:
        _history_store = HistoryStore(db_path)
        _history_store.init()
    return _history_store
