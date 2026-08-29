"""对话执行接口：chat（发送任务）/ events（SSE 事件流）/ messages（对话历史）。

分工说明：
- chat：客户端 → 服务端，触发任务（普通 HTTP，立即返回）
- events：服务端 → 客户端，SSE 长连接持续推送运行过程（任务触发后实时接收）
- messages：对话历史（user 任务 + assistant 最终回答，含每轮权限）
"""

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agent_runner import create_runner, get_runner
from ..db import database
from ..tables.messages import MessageTable
from ..tables.sessions import SessionTable

router = APIRouter(prefix="/api/sessions", tags=["chat"])


class ChatBody(BaseModel):
    content: str
    permission_level: int = 3


def _get_runner(session_id: int):
    """获取会话 runner；服务重启后自动按数据库 workspace 重建。"""
    runner = get_runner(session_id)
    if runner is not None:
        return runner
    with database.get_session() as db:
        row = SessionTable.get(db, session_id)
        if row is None:
            return None
        return create_runner(session_id, database.get_session, row.workspace)


@router.post("/{session_id}/chat")
async def chat(session_id: int, body: ChatBody):
    """发送任务（每轮对话带权限）。任务触发后实时输出走 SSE events。

    async 原因：run_task 需要创建 asyncio.Task（必须在事件循环中执行）。
    """
    if not (1 <= body.permission_level <= 3):
        raise HTTPException(status_code=400, detail="permission_level 必须为 1/2/3")
    runner = _get_runner(session_id)
    if runner is None:
        raise HTTPException(status_code=404, detail=f"会话不存在：{session_id}")
    if runner.is_running():
        raise HTTPException(status_code=400, detail="任务运行中")

    # 存 user 消息（含本轮权限）
    with database.get_session() as db:
        MessageTable.add(db, session_id, "user", body.content, body.permission_level)

    runner.run_task(body.content, body.permission_level)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "session_id": session_id,
            "task_id": runner._task_seq,
            "permission_level": body.permission_level,
        },
    }


@router.get("/{session_id}/events")
def events(session_id: int):
    """SSE 事件流：任务运行过程实时推送（跨任务持续；客户端断开即停止）。"""
    runner = _get_runner(session_id)
    if runner is None:
        raise HTTPException(status_code=404, detail=f"会话不存在：{session_id}")

    async def stream():
        try:
            async for event in runner.events_stream():
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        except asyncio.CancelledError:
            pass  # 客户端断开

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/{session_id}/messages")
def messages(session_id: int):
    """对话历史（user 任务 + assistant 最终回答，含每轮权限）。"""
    with database.get_session() as db:
        rows = MessageTable.list_by_session(db, session_id)
        return {
            "code": 0,
            "message": "ok",
            "data": [
                {
                    "id": r.id,
                    "role": r.role,
                    "content": r.content,
                    "permission_level": r.permission_level,
                    "created_at": r.created_at,
                }
                for r in rows
            ],
        }
