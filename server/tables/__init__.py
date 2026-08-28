"""数据表注册：每张表一个文件，这里汇总注册与迁移。

- TABLES：所有表的类（提供 name / create_sql / CRUD 静态方法）
- MIGRATIONS：版本化迁移列表（version 1 = 全部建表；后续表结构变更在此追加）
"""

from .file_changes import FileChangeTable
from .messages import MessageTable
from .sessions import SessionTable

__all__ = ["TABLES", "MIGRATIONS", "SessionTable", "MessageTable", "FileChangeTable"]

TABLES = [SessionTable, MessageTable, FileChangeTable]

MIGRATIONS: list[dict] = [
    {
        "version": 1,
        "sql": [t.create_sql for t in TABLES],
    },
    # 后续表结构变更示例：
    # {"version": 2, "sql": ["ALTER TABLE messages ADD COLUMN xxx ..."]},
]
