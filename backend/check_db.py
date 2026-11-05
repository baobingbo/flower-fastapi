import sqlite3
import os

db_path = 'flowerui.db'
if os.exists(db_path):
    print(f'数据库文件存在: {db_path}')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 检查表
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print('表:', [t[0] for t in tables])
    
    # 检查用户
    try:
        cursor.execute('SELECT username, role FROM users')
        users = cursor.fetchall()
        print('用户:', users)
    except:
        print('用户表不存在或为空')
    
    conn.close()
else:
    print(f'数据库文件不存在: {db_path}')
    print('下次启动时会自动创建')
