"""登录限流器 — 基于内存的滑动窗口计数器。"""
from __future__ import annotations

import threading
import time
from typing import Dict, Tuple

class LoginRateLimiter:
    """滑动窗口限流器。

    键格式: f"{ip}:{username}"
    窗口大小: max_attempts (默认 5)
    锁定时长: lockout_duration (默认 300s)
    """

    def __init__(self, max_attempts: int = 5, lockout_duration: int = 300):
        self.max_attempts = max_attempts
        self.lockout_duration = lockout_duration
        # 每个键存储失败时间戳列表
        self._failures: Dict[str, list] = {}
        self._lock = threading.Lock()
        self._call_count = 0  # 每100次调用清理一次

    def _key(self, ip: str, username: str) -> str:
        return f"{ip}:{username}"

    def _cleanup_expired(self, key: str) -> None:
        """清理过期的失败记录。"""
        now = time.time()
        if key in self._failures:
            self._failures[key] = [
                t for t in self._failures[key]
                if now - t < self.lockout_duration
            ]
            if not self._failures[key]:
                del self._failures[key]

    def check_limit(self, ip: str, username: str) -> dict:
        """检查是否超过限流阈值。

        Returns:
            {allowed: bool, remaining_seconds: int}
        """
        key = self._key(ip, username)
        with self._lock:
            self._call_count += 1
            self._cleanup_expired(key)

            failures = self._failures.get(key, [])
            if len(failures) >= self.max_attempts:
                # 计算还需要等待的时间
                oldest = failures[0]
                remaining = int(self.lockout_duration - (time.time() - oldest))
                return {"allowed": False, "remaining_seconds": max(remaining, 0)}
            return {"allowed": True, "remaining_seconds": 0}

    def record_failure(self, ip: str, username: str) -> dict:
        """记录一次失败尝试。

        Returns:
            {locked: bool, remaining_seconds: int}
        """
        key = self._key(ip, username)
        with self._lock:
            self._call_count += 1
            self._cleanup_expired(key)

            if key not in self._failures:
                self._failures[key] = []
            self._failures[key].append(time.time())

            if len(self._failures[key]) >= self.max_attempts:
                oldest = self._failures[key][0]
                remaining = int(self.lockout_duration - (time.time() - oldest))
                return {"locked": True, "remaining_seconds": max(remaining, 0)}
            return {"locked": False, "remaining_seconds": 0}

    def reset(self, ip: str, username: str) -> None:
        """登录成功后重置计数器。"""
        key = self._key(ip, username)
        with self._lock:
            if key in self._failures:
                del self._failures[key]

    def cleanup(self) -> int:
        """清理所有过期条目，返回清理的条目数。每100次调用执行一次。"""
        with self._lock:
            self._call_count += 1
            if self._call_count % 100 != 0:
                return 0

            cleaned = 0
            now = time.time()
            keys_to_delete = []
            for key, timestamps in self._failures.items():
                expired = [t for t in timestamps if now - t >= self.lockout_duration]
                if len(expired) == len(timestamps):
                    keys_to_delete.append(key)
                    cleaned += 1
                else:
                    self._failures[key] = [t for t in timestamps if now - t < self.lockout_duration]
            for key in keys_to_delete:
                del self._failures[key]
            return cleaned


# 全局单例
_rate_limiter: LoginRateLimiter | None = None


def get_rate_limiter() -> LoginRateLimiter:
    """获取全局限流器单例。"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = LoginRateLimiter()
    return _rate_limiter
