"""SQLite 用户与 RBAC 权限存储服务。"""
from __future__ import annotations

import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.config import resolve_db_path, settings

logger = logging.getLogger(__name__)

# 默认角色
DEFAULT_ROLES = {
    "admin": "系统管理员，拥有所有权限",
    "operator": "操作员，可执行任务管理和查看",
    "viewer": "观察者，仅可查看任务",
}

# 默认权限
DEFAULT_PERMISSIONS = {
    "task.view": "查看任务列表和详情",
    "task.apply": "提交/申请任务",
    "worker.manage": "管理 Worker（重启、扩缩容）",
    "config.manage": "管理系统配置",
    "user.manage": "管理用户和角色",
}

# 角色-权限映射
ROLE_PERMISSION_MAP = {
    "admin": list(DEFAULT_PERMISSIONS.keys()),
    "operator": ["task.view", "task.apply", "worker.manage"],
    "viewer": ["task.view"],
}


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


def init_db() -> None:
    """初始化数据库表结构和默认数据。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        
        # 创建用户表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'viewer',
                email TEXT DEFAULT '',
                created_at REAL NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            )
        """)
        
        # 创建角色表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT ''
            )
        """)
        
        # 创建权限表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT ''
            )
        """)
        
        # 创建角色权限关联表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS role_permissions (
                role_id INTEGER NOT NULL,
                permission_id INTEGER NOT NULL,
                PRIMARY KEY (role_id, permission_id),
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
                FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE
            )
        """)
        
        # 创建用户角色关联表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_roles (
                user_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, role_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
            )
        """)
        
        # 插入默认角色
        for name, desc in DEFAULT_ROLES.items():
            cursor.execute("INSERT OR IGNORE INTO roles (name, description) VALUES (?, ?)", (name, desc))
        
        # 插入默认权限
        for name, desc in DEFAULT_PERMISSIONS.items():
            cursor.execute("INSERT OR IGNORE INTO permissions (name, description) VALUES (?, ?)", (name, desc))
        
        # 插入角色-权限关联
        for role_name, perms in ROLE_PERMISSION_MAP.items():
            cursor.execute("SELECT id FROM roles WHERE name = ?", (role_name,))
            role_row = cursor.fetchone()
            if role_row:
                role_id = role_row["id"]
                for perm_name in perms:
                    cursor.execute("SELECT id FROM permissions WHERE name = ?", (perm_name,))
                    perm_row = cursor.fetchone()
                    if perm_row:
                        cursor.execute(
                            "INSERT OR IGNORE INTO role_permissions (role_id, permission_id) VALUES (?, ?)",
                            (role_id, perm_row["id"])
                        )
        
        # 创建默认 admin 用户（密码: admin123）
        import hashlib
        password_hash = hashlib.sha256("admin123".encode()).hexdigest()
        cursor.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, role, created_at, is_active) VALUES (?, ?, ?, ?, ?)",
            ("admin", password_hash, "admin", time.time(), 1)
        )
        # 关联默认 admin 的角色（user_roles）——缺了这行，has_permission 的
        # 角色→权限联表查不到 admin 的任何权限，用户管理等功能会 403。
        cursor.execute("SELECT id FROM users WHERE username = ?", ("admin",))
        admin_row = cursor.fetchone()
        cursor.execute("SELECT id FROM roles WHERE name = ?", ("admin",))
        role_row = cursor.fetchone()
        if admin_row and role_row:
            cursor.execute(
                "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
                (admin_row["id"], role_row["id"]),
            )

        logger.info("用户数据库初始化完成")


def verify_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """验证用户密码，返回用户信息或 None。"""
    import hashlib
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, role, email, created_at, is_active FROM users WHERE username = ? AND password_hash = ? AND is_active = 1",
            (username, password_hash)
        )
        row = cursor.fetchone()
        if row:
            result = _row_to_dict(row)
            # 获取用户角色
            cursor.execute("""
                SELECT r.name, r.description 
                FROM roles r 
                JOIN user_roles ur ON r.id = ur.role_id 
                WHERE ur.user_id = ?
            """, (row["id"],))
            result["roles"] = [_row_to_dict(r) for r in cursor.fetchall()]
            # 获取用户权限
            cursor.execute("""
                SELECT p.name, p.description 
                FROM permissions p 
                JOIN role_permissions rp ON p.id = rp.permission_id 
                JOIN user_roles ur ON rp.role_id = ur.role_id 
                WHERE ur.user_id = ?
            """, (row["id"],))
            result["permissions"] = [_row_to_dict(p) for p in cursor.fetchall()]
            return result
    return None


def get_user(username: str) -> Optional[Dict[str, Any]]:
    """获取用户信息。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if not row:
            return None
        result = _row_to_dict(row)
        # 获取用户角色
        cursor.execute("""
            SELECT r.id, r.name, r.description 
            FROM roles r 
            JOIN user_roles ur ON r.id = ur.role_id 
            WHERE ur.user_id = ?
        """, (row["id"],))
        result["roles"] = [_row_to_dict(r) for r in cursor.fetchall()]
        return result


def list_users() -> List[Dict[str, Any]]:
    """获取用户列表。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, role, email, created_at, is_active FROM users ORDER BY id")
        return [_row_to_dict(r) for r in cursor.fetchall()]


def create_user(
    username: str,
    password: str,
    role: str = "viewer",
    email: str = "",
) -> Dict[str, Any]:
    """创建新用户。"""
    import hashlib
    
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, password_hash, role, email, created_at, is_active) VALUES (?, ?, ?, ?, ?, ?)",
            (username, password_hash, role, email, time.time(), 1)
        )
        user_id = cursor.lastrowid
        # 关联角色
        cursor.execute("SELECT id FROM roles WHERE name = ?", (role,))
        role_row = cursor.fetchone()
        if role_row:
            cursor.execute(
                "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
                (user_id, role_row["id"])
            )
        return get_user(username)


def update_user(username: str, **kwargs) -> Optional[Dict[str, Any]]:
    """更新用户信息。"""
    allowed_fields = {"role", "email", "is_active"}
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
    if not updates:
        return get_user(username)
    
    with _get_conn() as conn:
        cursor = conn.cursor()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [username]
        cursor.execute(f"UPDATE users SET {set_clause} WHERE username = ?", values)
        
        # 如果更新了角色，同步 user_roles 表
        if "role" in updates:
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            user_row = cursor.fetchone()
            if user_row:
                cursor.execute("DELETE FROM user_roles WHERE user_id = ?", (user_row["id"],))
                cursor.execute("SELECT id FROM roles WHERE name = ?", (updates["role"],))
                role_row = cursor.fetchone()
                if role_row:
                    cursor.execute(
                        "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
                        (user_row["id"], role_row["id"])
                    )
        
        return get_user(username)


def delete_user(username: str) -> bool:
    """删除用户。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE username = ?", (username,))
        return cursor.rowcount > 0


def change_password(username: str, new_password: str) -> bool:
    """修改用户密码。"""
    import hashlib
    
    password_hash = hashlib.sha256(new_password.encode()).hexdigest()
    
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (password_hash, username)
        )
        return cursor.rowcount > 0


def list_roles() -> List[Dict[str, Any]]:
    """获取角色列表。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM roles ORDER BY id")
        roles = [_row_to_dict(r) for r in cursor.fetchall()]
        # 获取每个角色的权限
        for role in roles:
            cursor.execute("""
                SELECT p.name, p.description 
                FROM permissions p 
                JOIN role_permissions rp ON p.id = rp.permission_id 
                WHERE rp.role_id = ?
            """, (role["id"],))
            role["permissions"] = [_row_to_dict(p) for p in cursor.fetchall()]
        return roles


def create_role(name: str, description: str = "") -> Dict[str, Any]:
    """创建新角色。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO roles (name, description) VALUES (?, ?)",
            (name, description)
        )
        cursor.execute("SELECT * FROM roles WHERE name = ?", (name,))
        return _row_to_dict(cursor.fetchone())


def update_role(name: str, description: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """更新角色信息。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        if description is not None:
            cursor.execute("UPDATE roles SET description = ? WHERE name = ?", (description, name))
        cursor.execute("SELECT * FROM roles WHERE name = ?", (name,))
        role = _row_to_dict(cursor.fetchone())
        if role:
            cursor.execute("""
                SELECT p.name, p.description 
                FROM permissions p 
                JOIN role_permissions rp ON p.id = rp.permission_id 
                WHERE rp.role_id = ?
            """, (role["id"],))
            role["permissions"] = [_row_to_dict(p) for p in cursor.fetchall()]
        return role


def delete_role(name: str) -> bool:
    """删除角色。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM roles WHERE name = ?", (name,))
        return cursor.rowcount > 0


def get_user_roles(username: str) -> List[Dict[str, Any]]:
    """获取用户的角色列表。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        user_row = cursor.fetchone()
        if not user_row:
            return []
        cursor.execute("""
            SELECT r.id, r.name, r.description 
            FROM roles r 
            JOIN user_roles ur ON r.id = ur.role_id 
            WHERE ur.user_id = ?
        """, (user_row["id"],))
        return [_row_to_dict(r) for r in cursor.fetchall()]


def assign_role(username: str, role_name: str) -> bool:
    """为用户分配角色。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        user_row = cursor.fetchone()
        if not user_row:
            return False
        cursor.execute("SELECT id FROM roles WHERE name = ?", (role_name,))
        role_row = cursor.fetchone()
        if not role_row:
            return False
        cursor.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (user_row["id"], role_row["id"])
        )
        return True


def remove_role(username: str, role_name: str) -> bool:
    """移除用户角色。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        user_row = cursor.fetchone()
        if not user_row:
            return False
        cursor.execute("SELECT id FROM roles WHERE name = ?", (role_name,))
        role_row = cursor.fetchone()
        if not role_row:
            return False
        cursor.execute(
            "DELETE FROM user_roles WHERE user_id = ? AND role_id = ?",
            (user_row["id"], role_row["id"])
        )
        return cursor.rowcount > 0


def create_permission(name: str, description: str = "") -> Dict[str, Any]:
    """创建新权限。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO permissions (name, description) VALUES (?, ?)",
            (name, description),
        )
        cursor.execute("SELECT * FROM permissions WHERE name = ?", (name,))
        return _row_to_dict(cursor.fetchone())


def assign_role_to_permissions(role_name: str, perm_names: List[str]) -> bool:
    """为角色批量授权（幂等）。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM roles WHERE name = ?", (role_name,))
        role_row = cursor.fetchone()
        if not role_row:
            return False
        for perm_name in perm_names:
            cursor.execute("SELECT id FROM permissions WHERE name = ?", (perm_name,))
            perm_row = cursor.fetchone()
            if perm_row:
                cursor.execute(
                    "INSERT OR IGNORE INTO role_permissions (role_id, permission_id) VALUES (?, ?)",
                    (role_row["id"], perm_row["id"]),
                )
        return True


def list_permissions() -> List[Dict[str, Any]]:
    """获取权限列表。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM permissions ORDER BY id")
        return [_row_to_dict(p) for p in cursor.fetchall()]


def has_permission(username: str, permission_name: str) -> bool:
    """检查用户是否拥有指定权限。"""
    with _get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ? AND is_active = 1", (username,))
        user_row = cursor.fetchone()
        if not user_row:
            return False
        cursor.execute("""
            SELECT COUNT(*) as cnt 
            FROM permissions p 
            JOIN role_permissions rp ON p.id = rp.permission_id 
            JOIN user_roles ur ON rp.role_id = ur.role_id 
            WHERE ur.user_id = ? AND p.name = ?
        """, (user_row["id"], permission_name))
        row = cursor.fetchone()
        return row["cnt"] > 0 if row else False
