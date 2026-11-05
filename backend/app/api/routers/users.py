"""用户与 RBAC 权限管理接口。"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ...core.security import CurrentUser, get_current_user, require_permission, validate_password
from ...services.users_db import (
    assign_role,
    change_password,
    create_role,
    create_user,
    delete_role,
    delete_user,
    get_user,
    get_user_roles,
    has_permission,
    list_permissions,
    list_roles,
    list_users,
    remove_role,
    update_role,
    update_user,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "viewer"
    email: str = ""


class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None


class ResetPasswordRequest(BaseModel):
    password: str


class AssignRoleRequest(BaseModel):
    role: str


class CreateRoleRequest(BaseModel):
    name: str
    description: str = ""


class UpdateRoleRequest(BaseModel):
    description: str



@router.get("")
async def get_users(
    current_user: str = Depends(get_current_user)
):
    """获取用户列表。"""
    if current_user == "anonymous":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要认证")
    return list_users()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user_endpoint(
    payload: CreateUserRequest,
    _: str = Depends(require_permission("user.manage"))
):
    """创建新用户。"""
    err = validate_password(payload.password)
    if err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    user = get_user(payload.username)
    if user:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户已存在")
    return create_user(payload.username, payload.password, payload.role, payload.email)


@router.get("/{username}")
async def get_user_endpoint(
    username: str,
    current_user: str = Depends(get_current_user)
):
    """获取单个用户信息。"""
    if current_user == "anonymous":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要认证")
    user = get_user(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return user


@router.put("/{username}")
async def update_user_endpoint(
    username: str,
    payload: UpdateUserRequest,
    _: str = Depends(require_permission("user.manage"))
):
    """更新用户信息。"""
    user = get_user(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        return user
    return update_user(username, **updates)


@router.delete("/{username}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_endpoint(
    username: str,
    _: str = Depends(require_permission("user.manage"))
):
    """删除用户。"""
    if not delete_user(username):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")


@router.post("/{username}/password")
async def change_password_endpoint(
    username: str,
    payload: ResetPasswordRequest,
    _: str = Depends(require_permission("user.manage"))
):
    """修改用户密码。"""
    err = validate_password(payload.password)
    if err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    if not change_password(username, payload.password):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return {"message": "密码已修改"}


@router.get("/{username}/roles")
async def get_user_roles_endpoint(
    username: str,
    current_user: str = Depends(get_current_user)
):
    """获取用户角色列表。"""
    if current_user == "anonymous":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要认证")
    user = get_user(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return get_user_roles(username)


@router.post("/{username}/roles")
async def assign_role_endpoint(
    username: str,
    payload: AssignRoleRequest,
    _: str = Depends(require_permission("user.manage"))
):
    """为用户分配角色。"""
    user = get_user(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if not assign_role(username, payload.role):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="角色不存在")
    return {"message": "角色已分配"}


@router.delete("/{username}/roles/{role}")
async def remove_role_endpoint(
    username: str,
    role: str,
    _: str = Depends(require_permission("user.manage"))
):
    """移除用户角色。"""
    user = get_user(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if not remove_role(username, role):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="角色不存在或用户无此角色")
    return {"message": "角色已移除"}


# 角色管理路由
roles_router = APIRouter(prefix="/api/roles", tags=["roles"])


@roles_router.get("")
async def get_roles(
    current_user: str = Depends(get_current_user)
):
    """获取角色列表。"""
    if current_user == "anonymous":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要认证")
    return list_roles()


@roles_router.post("", status_code=status.HTTP_201_CREATED)
async def create_role_endpoint(
    payload: CreateRoleRequest,
    _: str = Depends(require_permission("user.manage"))
):
    """创建新角色。"""
    role = list_roles()
    if any(r["name"] == payload.name for r in role):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="角色已存在")
    return create_role(payload.name, payload.description)


@roles_router.put("/{name}")
async def update_role_endpoint(
    name: str,
    payload: UpdateRoleRequest,
    _: str = Depends(require_permission("user.manage"))
):
    """更新角色信息。"""
    role = list_roles()
    if not any(r["name"] == name for r in role):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="角色不存在")
    return update_role(name, payload.description)


@roles_router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role_endpoint(
    name: str,
    _: str = Depends(require_permission("user.manage"))
):
    """删除角色。"""
    role = list_roles()
    if not any(r["name"] == name for r in role):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="角色不存在")
    if not delete_role(name):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="角色不存在")


# 权限管理路由
permissions_router = APIRouter(prefix="/api/permissions", tags=["permissions"])


@permissions_router.get("")
async def get_permissions(
    current_user: str = Depends(get_current_user)
):
    """获取权限列表。"""
    if current_user == "anonymous":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要认证")
    return list_permissions()
