"""file_changes 表：文件变更（三级权限系统的核心数据，SQLAlchemy Model）。

- L1：确认内嵌在 SSE 对话流中（pending → applied / rejected），面板只提供撤销
- L2：applied → reverted（保留 old/new 内容供对比与撤销）
- 会话级累积：同一会话先后用不同权限产生的变更都在这里，按状态分组展示
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class FileChangeTable(Base):
    __tablename__ = "file_changes"
    __table_args__ = (Index("idx_changes_session", "session_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(String(1024))
    operation: Mapped[str] = mapped_column(String(16))
    old_content: Mapped[str] = mapped_column(MEDIUMTEXT)
    new_content: Mapped[str] = mapped_column(MEDIUMTEXT)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    permission_level: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ---------- CRUD ----------

    @staticmethod
    def add(
        session,
        session_id: int,
        file_path: str,
        operation: str,
        old_content: str,
        new_content: str,
        status: str,
        permission_level: int,
    ) -> int:
        row = FileChangeTable(
            session_id=session_id,
            file_path=file_path,
            operation=operation,
            old_content=old_content,
            new_content=new_content,
            status=status,
            permission_level=permission_level,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id

    @staticmethod
    def get(session, change_id: int) -> "FileChangeTable | None":
        return session.get(FileChangeTable, change_id)

    @staticmethod
    def list_by_session(session, session_id: int, status: str | None = None) -> list["FileChangeTable"]:
        from sqlalchemy import select

        stmt = (
            select(FileChangeTable)
            .where(FileChangeTable.session_id == session_id)
            .order_by(FileChangeTable.id.asc())
        )
        if status:
            stmt = stmt.where(FileChangeTable.status == status)
        return session.execute(stmt).scalars().all()

    @staticmethod
    def update_status(
        session,
        change_id: int,
        status: str,
        confirmed: bool = False,
        reverted: bool = False,
    ) -> None:
        """更新变更状态；confirmed/reverted 同时写入对应时间戳。"""
        row = session.get(FileChangeTable, change_id)
        if not row:
            return
        row.status = status
        if confirmed:
            row.confirmed_at = datetime.now()
        if reverted:
            row.reverted_at = datetime.now()
        session.commit()
