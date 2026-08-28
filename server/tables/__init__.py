"""数据表注册：每张表一个文件（SQLAlchemy Model）。

- import 三个 Model 即完成 Base.metadata 注册，create_all 自动建表
- MIGRATIONS：表结构变更（ALTER）按版本应用；新表用 create_all，改表在此追加
"""

from .file_changes import FileChangeTable
from .messages import MessageTable
from .sessions import SessionTable

__all__ = ["MIGRATIONS", "SessionTable", "MessageTable", "FileChangeTable"]

# 表结构变更迁移（ALTER），版本化自动应用：
# MIGRATIONS = [
#     {"version": 2, "sql": ["ALTER TABLE messages ADD COLUMN xxx VARCHAR(64) NULL"]},
# ]
MIGRATIONS: list[dict] = []
