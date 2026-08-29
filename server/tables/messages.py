"""messages 表：对话历史（SQLAlchemy Model，自动生成建表 DDL）。

只存 user 任务 + assistant 最终回答（过程事件运行中经 SSE 实时展示，不落库）。
每轮消息记录所用权限（permission_level），前端展示"这一轮用的什么权限"。
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class MessageTable(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("idx_messages_session", "session_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(MEDIUMTEXT)
    permission_level: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # ---------- CRUD ----------

    @staticmethod
    def add(session, session_id: int, role: str, content: str, permission_level: int = 3) -> int:
        row = MessageTable(
            session_id=session_id, role=role, content=content, permission_level=permission_level
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id

    @staticmethod
    def list_by_session(session, session_id: int, limit: int = 200) -> list["MessageTable"]:
        from sqlalchemy import select

        return session.execute(
            select(MessageTable)
            .where(MessageTable.session_id == session_id)
            .order_by(MessageTable.id.asc())
            .limit(limit)
        ).scalars().all()

    @staticmethod
    def get_latest_summary(session, session_id: int) -> "MessageTable | None":
        """最新一条会话摘要（role='summary'）。"""
        from sqlalchemy import select

        return session.execute(
            select(MessageTable)
            .where(MessageTable.session_id == session_id, MessageTable.role == "summary")
            .order_by(MessageTable.id.desc())
            .limit(1)
        ).scalars().first()

    @staticmethod
    def list_after(session, session_id: int, after_id: int) -> list["MessageTable"]:
        """id 大于 after_id 的全部消息（摘要之后的轮次）。"""
        from sqlalchemy import select

        return session.execute(
            select(MessageTable)
            .where(MessageTable.session_id == session_id, MessageTable.id > after_id)
            .order_by(MessageTable.id.asc())
        ).scalars().all()
