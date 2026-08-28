"""sessions 表：会话（SQLAlchemy Model，自动生成建表 DDL）。

权限是每轮对话的属性，不放在会话层（每次 chat 消息携带 permission_level）。
"""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class SessionTable(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), default="", server_default="")
    workspace: Mapped[str] = mapped_column(String(1024))
    strategy: Mapped[str] = mapped_column(String(64), default="react", server_default="react")
    status: Mapped[str] = mapped_column(String(32), default="running", server_default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # ---------- CRUD ----------

    @staticmethod
    def create(session, title: str, workspace: str, strategy: str = "react") -> int:
        """创建会话，返回 session_id。"""
        row = SessionTable(title=title, workspace=workspace, strategy=strategy)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id

    @staticmethod
    def get(session, session_id: int) -> "SessionTable | None":
        return session.get(SessionTable, session_id)

    @staticmethod
    def list_all(session) -> list["SessionTable"]:
        from sqlalchemy import select

        return session.execute(
            select(SessionTable).order_by(SessionTable.updated_at.desc())
        ).scalars().all()

    @staticmethod
    def update_status(session, session_id: int, status: str) -> None:
        row = session.get(SessionTable, session_id)
        if row:
            row.status = status
            session.commit()

    @staticmethod
    def update_title(session, session_id: int, title: str) -> None:
        row = session.get(SessionTable, session_id)
        if row:
            row.title = title
            session.commit()

    @staticmethod
    def delete(session, session_id: int) -> None:
        row = session.get(SessionTable, session_id)
        if row:
            session.delete(row)
            session.commit()
