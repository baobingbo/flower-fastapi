"""Celery 应用入口，供 ``celery -A celery_app ...`` 使用。

Celery 的 ``-A`` 选项在解析阶段就会 import 这个模块并查找 ``app`` /
``celery`` 属性，所以这里必须暴露一个模块级的 Celery 实例。

FlowerUI 自身并不直接复用这个实例（服务内部通过
``app.core.celery_app.get_celery_app()`` 按配置签名动态重建），
它主要让 Celery CLI 能解析 ``-A``、``-b`` 等全局选项，以及让用户在同一个
app 上同时使用 worker / beat / flowerui 等子命令。

配置来源与其它启动方式一致：flowerui-settings.toml、FLOWER_* 环境变量、
flowerui.runtime.toml。``celery flowerui`` 的命令行参数优先级最高。
"""
from app.core.celery_app import get_celery_app

# Celery 的 find_app() 会优先取 sym.app，其次是 sym.celery
app = get_celery_app()
celery = app

__all__ = ["app", "celery"]
