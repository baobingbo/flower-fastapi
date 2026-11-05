"""DAG 可视化接口：任务依赖关系图。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from ...core.config import settings
from ...core.security import get_current_user
from ...services.manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dag", tags=["dag"], dependencies=[Depends(get_current_user)])


def _build_dag_from_tasks() -> Dict[str, Any]:
    """从 registered_tasks_detail 构建有向图。

    由于本项目没有显式的任务依赖声明，这里采用启发式规则：
    - 每个任务作为独立节点
    - 根据任务名中包含 common prefix 或 suffix 的关系推断潜在依赖
    - 同时展示所有已注册任务，便于用户理解任务集合
    """
    tasks_detail = manager.registered_tasks_detail()
    
    nodes: List[Dict[str, str]] = []
    edges: List[Dict[str, str]] = []
    
    for task in tasks_detail:
        name = task.get("name", "")
        node_id = name.replace(".", "_")
        nodes.append({"id": node_id, "name": name, "queue": task.get("queue", "celery")})
    
    # 启发式构建边：相同前缀的任务可能有依赖关系
    # 例如 tasks.send_email 和 tasks.process_email 可能有关联
    task_names = [t["name"] for t in tasks_detail]
    
    # 按点号分割，找共同父级
    from collections import defaultdict
    parents = defaultdict(list)
    
    for name in task_names:
        parts = name.split(".")
        if len(parts) > 1:
            parent_key = ".".join(parts[:-1])
            parents[parent_key].append(name)
    
    # 为有共同父级的任务创建边（表示它们属于同一模块）
    for parent, children in parents.items():
        if len(children) > 1:
            # 创建一个虚拟父节点
            parent_id = parent.replace(".", "_")
            # 确保父节点存在
            if not any(n["id"] == parent_id for n in nodes):
                nodes.append({"id": parent_id, "name": parent, "queue": "system"})
            
            for child in children:
                child_id = child.replace(".", "_")
                edges.append({"source": parent_id, "target": child_id})
    
    # 如果没有边，说明是扁平结构，返回节点即可
    return {"nodes": nodes, "edges": edges}


@router.get("/tasks")
async def get_dag_tasks():
    """获取任务依赖关系图数据。"""
    try:
        dag_data = _build_dag_from_tasks()
        return dag_data
    except Exception as exc:
        logger.error("构建 DAG 失败: %s", exc)
        return {"nodes": [], "edges": []}
