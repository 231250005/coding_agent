"""会话接口：创建 / 列表 / 置顶 / 重命名 / 删除。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agent_runner import create_runner, remove_runner
from ..db import database
from ..tables.sessions import SessionTable

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class SessionCreate(BaseModel):
    workspace: str
    title: str = ""


class PinBody(BaseModel):
    is_pinned: bool


class RenameBody(BaseModel):
    title: str


def _to_dict(row) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "workspace": row.workspace,
        "is_pinned": bool(row.is_pinned),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.post("")
def create_session(body: SessionCreate):
    """创建会话，并注册对应的 SessionRunner（任务运行/事件流/变更持久化）。"""
    with database.get_session() as db:
        sid = SessionTable.create(db, body.title, body.workspace)
        row = SessionTable.get(db, sid)
        create_runner(sid, database.get_session, body.workspace)
        return {"code": 0, "message": "ok", "data": _to_dict(row)}


@router.get("")
def list_sessions():
    """会话列表（置顶优先 + 最近更新）。"""
    with database.get_session() as db:
        rows = SessionTable.list_all(db)
        return {"code": 0, "message": "ok", "data": [_to_dict(r) for r in rows]}


@router.put("/{session_id}/pin")
def set_pin(session_id: int, body: PinBody):
    """切换会话置顶。"""
    with database.get_session() as db:
        ok = SessionTable.set_pinned(db, session_id, body.is_pinned)
        if not ok:
            raise HTTPException(status_code=404, detail=f"会话不存在：{session_id}")
        return {"code": 0, "message": "ok", "data": {"id": session_id, "is_pinned": body.is_pinned}}


@router.put("/{session_id}/rename")
def rename_session(session_id: int, body: RenameBody):
    """重命名会话。"""
    with database.get_session() as db:
        ok = SessionTable.update_title(db, session_id, body.title)
        if not ok:
            raise HTTPException(status_code=404, detail=f"会话不存在：{session_id}")
        return {"code": 0, "message": "ok", "data": {"id": session_id, "title": body.title}}


@router.delete("/{session_id}")
def delete_session(session_id: int):
    """删除会话（连带清理 runner）。"""
    with database.get_session() as db:
        SessionTable.delete(db, session_id)
        remove_runner(session_id)
        return {"code": 0, "message": "ok", "data": None}
