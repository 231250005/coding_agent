"""迁移执行器：版本化自动迁移。

- schema_migrations 表记录已应用的版本
- 每次启动按版本号顺序执行未应用的迁移（每个版本只执行一次）
- 迁移列表定义在 server/tables/__init__.py（version 1 = 全部建表）
"""

import pymysql

from .tables import MIGRATIONS

_MIGRATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INT PRIMARY KEY,
    applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def apply_migrations(conn: pymysql.Connection) -> None:
    """按版本顺序应用未执行的迁移（幂等，可安全重复调用）。"""
    with conn.cursor() as cur:
        cur.execute(_MIGRATIONS_TABLE_SQL)
        cur.execute("SELECT version FROM schema_migrations")
        applied = {row["version"] for row in cur.fetchall()}
        for mig in MIGRATIONS:
            if mig["version"] in applied:
                continue
            for sql in mig["sql"]:
                cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)",
                (mig["version"],),
            )
