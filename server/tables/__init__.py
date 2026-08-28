"""数据表注册：每张表一个文件（SQLAlchemy Model）。

import 三个 Model 即完成 Base.metadata 注册；
启动时由 server/schema.sync_schema 自动比对 Model 与实际库表并补齐差异。
"""

from .file_changes import FileChangeTable
from .messages import MessageTable
from .sessions import SessionTable

__all__ = ["SessionTable", "MessageTable", "FileChangeTable"]
