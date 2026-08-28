"""数据库连接管理：配置、建库、获取连接、初始化编排。

- 连接配置走环境变量（MYSQL_HOST/PORT/USER/PASSWORD），默认 localhost:3306 root 空密码
- 数据库 coding_agent 不存在时自动创建（utf8mb4）
- 表结构与迁移由 server/tables（每表一文件）与 server/schema（迁移执行器）负责，
  本模块只做连接与编排，不包含任何业务表 SQL
"""

import os

import pymysql

from .schema import apply_migrations

DB_NAME = "coding_agent"


def _config(key: str, default: str) -> str:
    return os.environ.get(key, default)


class Database:
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        db_name: str = DB_NAME,
    ):
        self.host = host or _config("MYSQL_HOST", "localhost")
        self.port = int(port or _config("MYSQL_PORT", "3306"))
        self.user = user or _config("MYSQL_USER", "root")
        self.password = password if password is not None else _config("MYSQL_PASSWORD", "")
        self.db_name = db_name
        self._initialized = False

    # ---------- 连接 ----------

    def _connect_server(self) -> pymysql.Connection:
        """连接 MySQL 服务器（不指定库，用于建库）。"""
        return pymysql.connect(
            host=self.host, port=self.port, user=self.user,
            password=self.password, charset="utf8mb4", autocommit=True,
        )

    def _connect_db(self) -> pymysql.Connection:
        """直连业务库（不触发初始化，供内部建表/迁移使用）。"""
        return pymysql.connect(
            host=self.host, port=self.port, user=self.user,
            password=self.password, database=self.db_name,
            charset="utf8mb4", autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
        )

    def get_connection(self) -> pymysql.Connection:
        """获取业务连接（自动确保库/表已就绪）。"""
        self.ensure_initialized()
        return self._connect_db()

    # ---------- 初始化编排 ----------

    def ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._create_database_if_missing()
        conn = self._connect_db()
        try:
            apply_migrations(conn)
        finally:
            conn.close()
        self._initialized = True

    def _create_database_if_missing(self) -> None:
        conn = self._connect_server()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self.db_name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
        finally:
            conn.close()


# 模块级单例（FastAPI 生命周期里初始化一次）
database = Database()


def init_db() -> None:
    """初始化数据库（建库/建表/迁移），应用启动时调用。"""
    database.ensure_initialized()
