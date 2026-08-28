"""迁移执行器：表结构变更（ALTER）的版本化自动应用。

- 建表由 SQLAlchemy create_all 完成（Model 定义 → 自动 DDL）
- 本模块只负责"已有表的结构变更"：schema_migrations 记录已应用版本，
  每次启动按版本号顺序执行未应用的变更（每个版本只执行一次）
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .tables import MIGRATIONS

_MIGRATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INT PRIMARY KEY,
    applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def apply_migrations(engine: Engine) -> None:
    """按版本顺序应用未执行的表结构变更（幂等，可安全重复调用）。"""
    with engine.begin() as conn:
        conn.execute(text(_MIGRATIONS_TABLE_SQL))
        applied = {
            row[0]
            for row in conn.execute(text("SELECT version FROM schema_migrations"))
        }
        for mig in MIGRATIONS:
            if mig["version"] in applied:
                continue
            for sql in mig["sql"]:
                conn.execute(text(sql))
            conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": mig["version"]},
            )
