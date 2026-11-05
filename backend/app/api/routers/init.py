"""配置初始化接口。

端点：
- GET  /api/init/status     检查初始化状态（是否已完成首次初始化）
- POST /api/init/run        执行初始化（创建默认数据）
- POST /api/init/reset      重置配置（删除所有自定义配置）
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from ...core.security import get_current_user, has_permission, require_permission
from ...services import config_db, users_db, runtime_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/init", tags=["init"])


@router.get("/status")
async def get_init_status(_user: str = Depends(get_current_user)):
    """检查系统初始化状态。"""
    # 检查是否已完成初始化（用户表有数据）
    users = users_db.list_users()
    config_count = len(config_db.get_all_configs())
    
    is_initialized = len(users) > 0
    
    return {
        "initialized": is_initialized,
        "user_count": len(users),
        "config_count": config_count,
        "database_exists": True,
        "message": "系统已完成初始化" if is_initialized else "系统尚未初始化，请先执行初始化",
    }


@router.post("/run", status_code=status.HTTP_200_OK)
async def run_init(
    _user: str = Depends(require_permission("config.manage")),
):
    """执行系统初始化，创建默认角色、权限和 admin 用户。"""
    # 检查是否已初始化
    users = users_db.list_users()
    if len(users) > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="系统已完成初始化，请勿重复执行",
        )
    
    # 初始化数据库表
    try:
        users_db.init_db()
        config_db.init_config_tables()
        logger.info("数据库表初始化完成")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"数据库初始化失败: {e}",
        )
    
    # 创建默认角色
    default_roles = {
        "admin": "系统管理员，拥有所有权限",
        "operator": "操作员，可执行任务管理和查看",
        "viewer": "观察者，仅可查看任务",
    }
    
    created_roles = []
    for role_name, description in default_roles.items():
        try:
            role = users_db.create_role(role_name, description)
            created_roles.append(role_name)
            logger.info(f"已创建角色: {role_name}")
        except Exception as e:
            logger.warning(f"创建角色 {role_name} 失败: {e}")
    
    # 创建默认权限
    default_permissions = {
        "task.view": "查看任务列表和详情",
        "task.apply": "提交/申请任务",
        "worker.manage": "管理 Worker（重启、扩缩容）",
        "config.manage": "管理系统配置",
        "user.manage": "管理用户和角色",
    }
    
    created_perms = []
    for perm_name, description in default_permissions.items():
        try:
            perm = users_db.create_permission(perm_name, description)
            created_perms.append(perm_name)
            logger.info(f"已创建权限: {perm_name}")
        except Exception as e:
            logger.warning(f"创建权限 {perm_name} 失败: {e}")
    
    # 创建默认角色-权限映射
    role_perm_map = {
        "admin": list(default_permissions.keys()),
        "operator": ["task.view", "task.apply", "worker.manage"],
        "viewer": ["task.view"],
    }
    
    for role_name, perm_list in role_perm_map.items():
        try:
            users_db.assign_role_to_permissions(role_name, perm_list)
            logger.info(f"已分配角色权限: {role_name}")
        except Exception as e:
            logger.warning(f"分配角色权限 {role_name} 失败: {e}")
    
    # 创建初始 admin 用户
    try:
        admin_user = users_db.create_user(
            username="admin",
            password="admin123",
            role="admin",
            email="admin@example.com",
        )
        logger.info("已创建初始 admin 用户")
    except Exception as e:
        logger.error(f"创建 admin 用户失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建管理员用户失败: {e}",
        )
    
    return {
        "ok": True,
        "message": "系统初始化完成",
        "created_roles": created_roles,
        "created_permissions": created_perms,
        "admin_user": "admin",
        "default_password": "admin123",
        "warning": "请在首次登录后立即修改 admin 密码",
    }


@router.post("/reset")
async def reset_init(
    _user: str = Depends(get_current_user),
):
    """重置系统配置，删除所有自定义配置（保留默认数据）。"""
    # 检查是否有权限
    if not has_permission(_user, "config.manage"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="缺少 config.manage 权限",
        )
    
    # 重置配置
    deleted_count = config_db.reset_all_configs()
    
    # 清空运行时覆盖（不重启）
    runtime_config._overrides.clear()
    runtime_config._ui_state.clear()
    
    logger.info(f"已重置 {deleted_count} 项配置")
    
    return {
        "ok": True,
        "message": f"已重置 {deleted_count} 项配置",
        "deleted_count": deleted_count,
        "warning": "配置重置后需要重启服务才能完全生效",
    }
