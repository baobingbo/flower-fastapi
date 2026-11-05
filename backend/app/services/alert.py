"""告警系统：阈值规则 + 通道插件。

设计
----
- AlertRule   一条阈值规则，evaluate(current_value) -> bool
- AlertChannel 抽象通道基类
- WebhookChannel / ConsoleChannel 具体通道实现
- AlertEngine  引擎：持有规则+通道列表，批量评估并推送
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# 数据模型
# --------------------------------------------------------------------------
@dataclass
class AlertRule:
    """阈值告警规则。"""

    id: str
    name: str
    task_name: str
    metric: str          # 要监测的指标名，如 "runtime", "state"
    op: str = ">"         # 比较操作: >, <, ==, !=, >=, <=, */(匹配状态)
    threshold: Any = 0.0  # 阈值
    duration: float = 0.0  # 持续触发时长（秒），0 表示立即触发
    enabled: bool = True

    # 内部：记录首次触发时间
    _triggered_at: float = field(default=0.0, repr=False)

    def evaluate(self, current_value: Any) -> bool:
        """判断当前值是否触发告警。"""
        if not self.enabled:
            return False

        try:
            if self.op == "*":
                # 匹配状态名（如 state=="FAILURE"）
                return str(current_value) == str(self.threshold)
            if self.op == "==":
                return current_value == self.threshold
            if self.op == "!=":
                return current_value != self.threshold
            if self.op == ">=":
                return float(current_value) >= float(self.threshold)
            if self.op == "<=":
                return float(current_value) <= float(self.threshold)
            if self.op == ">":
                return float(current_value) > float(self.threshold)
            if self.op == "<":
                return float(current_value) < float(self.threshold)
        except (TypeError, ValueError):
            return False
        return False

    def check_duration(self, current_value: Any, now: Optional[float] = None) -> bool:
        """考虑 duration 条件的完整评估。"""
        now = now or time.time()
        triggered = self.evaluate(current_value)
        if triggered:
            if self._triggered_at == 0.0:
                self._triggered_at = now
            elif (now - self._triggered_at) >= self.duration:
                return True
        else:
            # 恢复未触发状态
            self._triggered_at = 0.0
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "task_name": self.task_name,
            "metric": self.metric,
            "op": self.op,
            "threshold": self.threshold,
            "duration": self.duration,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AlertRule":
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            task_name=data.get("task_name", ""),
            metric=data.get("metric", "state"),
            op=data.get("op", ">"),
            threshold=data.get("threshold", 0),
            duration=data.get("duration", 0.0),
            enabled=data.get("enabled", True),
        )


@dataclass
class AlertNotification:
    """一次告警通知的内容。"""

    rule_id: str
    rule_name: str
    task_name: str
    metric: str
    op: str
    threshold: Any
    current_value: Any
    triggered_at: float
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "task_name": self.task_name,
            "metric": self.metric,
            "op": self.op,
            "threshold": self.threshold,
            "current_value": self.current_value,
            "triggered_at": self.triggered_at,
            "message": self.message,
        }


# --------------------------------------------------------------------------
# 通道基类与实现
# --------------------------------------------------------------------------
class AlertChannel:
    """告警通道基类。"""

    name: str = "base"

    def send(self, alert: AlertNotification) -> None:
        raise NotImplementedError


class ConsoleChannel(AlertChannel):
    """控制台输出通道（默认启用）。"""

    name = "console"

    def send(self, alert: AlertNotification) -> None:
        logger.warning(
            "[ALERT] %s | rule=%s task=%s metric=%s %s %s => %s",
            alert.message or alert.rule_name,
            alert.rule_id,
            alert.task_name,
            alert.metric,
            alert.op,
            alert.threshold,
            alert.current_value,
        )


class WebhookChannel(AlertChannel):
    """Webhook HTTP POST 通道。"""

    name = "webhook"

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None):
        self.url = url
        self.headers = headers or {"Content-Type": "application/json"}

    def send(self, alert: AlertNotification) -> None:
        payload = alert.to_dict()
        try:
            import asyncio
            asyncio.get_event_loop()
        except RuntimeError:
            # 非异步上下文，用同步请求
            try:
                resp = httpx.post(
                    self.url,
                    json=payload,
                    headers=self.headers,
                    timeout=5.0,
                )
                resp.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                logger.error("Webhook 发送失败 %s: %s", self.url, exc)
            return

        # 异步上下文：通过线程执行同步 httpx
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                lambda: httpx.post(
                    self.url,
                    json=payload,
                    headers=self.headers,
                    timeout=5.0,
                )
            )
            try:
                resp = future.result(timeout=6)
                resp.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                logger.error("Webhook 发送失败 %s: %s", self.url, exc)


# --------------------------------------------------------------------------
# 告警引擎
# --------------------------------------------------------------------------
class AlertEngine:
    """告警引擎：管理规则与通道，执行批量评估。"""

    def __init__(self) -> None:
        self.rules: List[AlertRule] = []
        self.channels: List[AlertChannel] = [ConsoleChannel()]

    def add_rule(self, rule: AlertRule) -> None:
        self.rules.append(rule)
        logger.info("告警规则已添加: %s (id=%s)", rule.name, rule.id)

    def remove_rule(self, rule_id: str) -> bool:
        before = len(self.rules)
        self.rules = [r for r in self.rules if r.id != rule_id]
        return len(self.rules) < before

    def evaluate_all(
        self, tasks_stats: Dict[str, Any]
    ) -> List[AlertNotification]:
        """评估所有规则，返回触发的告警列表。

        tasks_stats: {task_name: {metric_name: value, ...}}
        例如: {"my_task": {"runtime": 120.5, "state": "FAILURE"}}
        """
        fired: List[AlertNotification] = []
        now = time.time()
        for rule in self.rules:
            if not rule.enabled:
                continue
            task_stats = tasks_stats.get(rule.task_name, {})
            current_value = task_stats.get(rule.metric)
            if current_value is None:
                continue
            if rule.check_duration(current_value, now):
                msg = (
                    f"[{rule.name}] {rule.task_name} 的 {rule.metric} "
                    f"{rule.op} {rule.threshold} => {current_value}"
                )
                alert = AlertNotification(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    task_name=rule.task_name,
                    metric=rule.metric,
                    op=rule.op,
                    threshold=rule.threshold,
                    current_value=current_value,
                    triggered_at=now,
                    message=msg,
                )
                fired.append(alert)
        return fired

    def notify(self, alert: AlertNotification) -> None:
        """将告警发送到所有通道。"""
        for channel in self.channels:
            try:
                channel.send(alert)
            except Exception as exc:  # noqa: BLE001
                logger.error("通道 %s 发送告警失败: %s", channel.name, exc)

    def notify_all(self, alerts: List[AlertNotification]) -> None:
        for alert in alerts:
            self.notify(alert)

    def test_all(self) -> Dict[str, Any]:
        """测试所有通道，返回结果。"""
        results = {}
        test_alert = AlertNotification(
            rule_id="__test__",
            rule_name="测试告警",
            task_name="__test__",
            metric="state",
            op="*",
            threshold="test",
            current_value="test",
            triggered_at=time.time(),
            message="[测试] 这是一条测试告警",
        )
        for channel in self.channels:
            try:
                channel.send(test_alert)
                results[channel.name] = "ok"
            except Exception as exc:  # noqa: BLE001
                results[channel.name] = f"error: {exc}"
        return results

    def get_rules(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self.rules]

    def add_rules_from_config(self, rules_json: str) -> int:
        """从 JSON 字符串加载规则列表。"""
        try:
            raw = json.loads(rules_json)
            if not isinstance(raw, list):
                raw = [raw]
            count = 0
            for item in raw:
                rule = AlertRule.from_dict(item)
                self.add_rule(rule)
                count += 1
            return count
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error("告警规则 JSON 解析失败: %s", exc)
            return 0


# 全局引擎实例
_engine: Optional[AlertEngine] = None


def get_engine() -> AlertEngine:
    global _engine
    if _engine is None:
        _engine = AlertEngine()
    return _engine


def reset_engine() -> None:
    global _engine
    _engine = None
