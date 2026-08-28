"""sessions 表：会话（SQLAlchemy Model，自动生成建表 DDL）。

- 权限是每轮对话的属性，不放在会话层（每次 chat 消息携带 permission_level）
- 会话支持置顶（is_pinned）与重命名（title）
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class SessionTable(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), default="", server_default="")
    workspace: Mapped[str] = mapped_column(String(1024))
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # ---------- CRUD ----------

    @staticmethod
    def create(session, title: str, workspace: str) -> int:
        """创建会话，返回 session_id。"""
        row = SessionTable(title=title, workspace=workspace)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id

    @staticmethod
    def get(session, session_id: int) -> "SessionTable | None":
        return session.get(SessionTable, session_id)

    @staticmethod
    def list_all(session) -> list["SessionTable"]:
        """会话列表：置顶优先 + 最近更新。"""
        from sqlalchemy import select

        return session.execute(
            select(SessionTable)
            .order_by(SessionTable.is_pinned.desc(), SessionTable.updated_at.desc())
        ).scalars().all()

    @staticmethod
    def set_pinned(session, session_id: int, is_pinned: bool) -> bool:
        """设置置顶，返回是否成功。"""
        row = session.get(SessionTable, session_id)
        if not row:
            return False
        row.is_pinned = is_pinned
        session.commit()
        return True

    @staticmethod
    def update_title(session, session_id: int, title: str) -> bool:
        """重命名会话，返回是否成功。"""
        row = session.get(SessionTable, session_id)
        if not row:
            return False
        row.title = title
        session.commit()
        return True

    @staticmethod
    def delete(session, session_id: int) -> None:
        row = session.get(SessionTable, session_id)
        if row:
            session.delete(row)
            session.commit()
