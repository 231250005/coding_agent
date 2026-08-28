"""数据库连接管理：配置、建库、engine 与会话、初始化编排。

- 连接配置走环境变量（MYSQL_HOST/PORT/USER/PASSWORD），默认 localhost:3306 root 空密码
- 数据库 coding_agent 不存在时自动创建（utf8mb4）
- 表由 SQLAlchemy Model（server/tables，每表一文件）定义，
  create_all 自动生成 DDL 建表；表结构变更由 server/schema 版本化迁移
"""

import os
from pathlib import Path

import pymysql
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from . import tables  # noqa: F401  导入以注册所有 Model 到 Base.metadata
from .schema import sync_schema

DB_NAME = "coding_agent"

# 加载项目根目录的 .env（凭据统一走环境变量或未入库的 .env 文件）
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


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
        self.engine = None
        self.SessionLocal = None

    # ---------- 初始化编排 ----------

    def ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._create_database_if_missing()
        self._create_engine()
        # 表结构自动同步：以 Model 定义为准，补齐缺失的表/列/索引
        sync_schema(self.engine)
        self._initialized = True

    def _create_database_if_missing(self) -> None:
        """数据库不存在时自动创建（utf8mb4）。"""
        conn = pymysql.connect(
            host=self.host, port=self.port, user=self.user,
            password=self.password, charset="utf8mb4", autocommit=True,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self.db_name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
        finally:
            conn.close()

    def _create_engine(self) -> None:
        url = URL.create(
            "mysql+pymysql",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.db_name,
            query={"charset": "utf8mb4"},
        )
        self.engine = create_engine(url, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)

    # ---------- 会话获取 ----------

    def get_session(self):
        """获取 ORM 会话（自动确保库/表已就绪）。"""
        self.ensure_initialized()
        return self.SessionLocal()


# 模块级单例（FastAPI 生命周期里初始化一次）
database = Database()


def init_db() -> None:
    """初始化数据库（建库/建表/迁移），应用启动时调用。"""
    database.ensure_initialized()
