"""变更管理接口：变更列表（含前后对比）/ L1 确认 / L1 拒绝 / L2 撤销。

- confirm/reject：L1 流程中 agent 暂停等待确认，REST 调用后落盘（或不落盘）并继续
- revert：L2 面板撤销（用 old_content 还原文件），刷新后依然可用（数据在数据库）
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..agent_runner import get_runner
from ..db import database
from ..tables.file_changes import FileChangeTable
from ..tables.sessions import SessionTable

router = APIRouter(prefix="/api", tags=["changes"])


def _make_diff(old: str, new: str, limit: int = 20) -> str:
    """简化的前后对比（- 旧行 / + 新行）。"""
    old_lines, new_lines = (old or "").splitlines(), (new or "").splitlines()
    lines = []
    for line in old_lines[:limit]:
        lines.append(f"- {line}")
    if len(old_lines) > limit:
        lines.append(f"… (共 {len(old_lines)} 行)")
    for line in new_lines[:limit]:
        lines.append(f"+ {line}")
    if len(new_lines) > limit:
        lines.append(f"… (共 {len(new_lines)} 行)")
    return "\n".join(lines) or "（空文件）"


def _to_dict(change) -> dict:
    return {
        "id": change.id,
        "file_path": change.file_path,
        "operation": change.operation,
        "status": change.status,
        "permission_level": change.permission_level,
        "old_content": change.old_content,
        "new_content": change.new_content,
        "diff": _make_diff(change.old_content, change.new_content),
        "created_at": change.created_at,
        "confirmed_at": change.confirmed_at,
        "reverted_at": change.reverted_at,
    }


def _resolve_workspace(change) -> str:
    """由变更所属会话获取工作区绝对路径。"""
    with database.get_session() as db:
        session = SessionTable.get(db, change.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"会话不存在：{change.session_id}")
        return session.workspace


def _safe_target(workspace: str, file_path: str) -> Path:
    """拼接文件绝对路径并校验在工作区内（防路径逃逸）。"""
    target = (Path(workspace) / file_path).resolve()
    if not target.is_relative_to(Path(workspace).resolve()):
        raise HTTPException(status_code=400, detail=f"非法文件路径：{file_path}")
    return target


@router.get("/sessions/{session_id}/changes")
def list_changes(session_id: int, status: str | None = None):
    """文件变更列表（L1/L2 共用；status 过滤 pending/applied/rejected/reverted）。"""
    with database.get_session() as db:
        rows = FileChangeTable.list_by_session(db, session_id, status)
        return {"code": 0, "message": "ok", "data": [_to_dict(r) for r in rows]}


@router.post("/sessions/{session_id}/changes/confirm-all")
def confirm_all_changes(session_id: int):
    """保存全部：该会话下的所有文件变更均已确认 → 删除全部变更记录。

    前端"保存全部"按钮调用：用户认可当前全部变更（撤销能力随之放弃），
    变更面板清空。
    """
    with database.get_session() as db:
        rows = FileChangeTable.list_by_session(db, session_id)
        for row in rows:
            db.delete(row)
        db.commit()
        return {
            "code": 0,
            "message": "ok",
            "data": {"session_id": session_id, "deleted": len(rows)},
        }


@router.post("/changes/{change_id}/confirm")
def confirm_change(change_id: int):
    """L1 确认：真正落盘（new_content 写入工作区文件），agent 继续下一步。"""
    with database.get_session() as db:
        change = FileChangeTable.get(db, change_id)
        if change is None:
            raise HTTPException(status_code=404, detail=f"变更不存在：{change_id}")
        if change.status != "pending":
            raise HTTPException(status_code=400, detail=f"变更 {change_id} 当前状态为 {change.status}，无法确认")

        # 落盘（先写文件，成功才更新状态）
        workspace = _resolve_workspace(change)
        target = _safe_target(workspace, change.file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(change.new_content, encoding="utf-8")

        FileChangeTable.update_status(db, change_id, "applied", confirmed=True)

    # 通知 runner：agent 若在等待确认则继续
    runner = get_runner(change.session_id)
    if runner is not None:
        runner.resolve_confirm(change_id, "confirmed")

    return {"code": 0, "message": "ok", "data": {"change_id": change_id, "status": "applied"}}


@router.post("/changes/{change_id}/reject")
def reject_change(change_id: int):
    """L1 拒绝：不落盘，agent 跳过该修改继续；记录删除（不再展示）。"""
    with database.get_session() as db:
        change = FileChangeTable.get(db, change_id)
        if change is None:
            raise HTTPException(status_code=404, detail=f"变更不存在：{change_id}")
        if change.status != "pending":
            raise HTTPException(status_code=400, detail=f"变更 {change_id} 当前状态为 {change.status}，无法拒绝")
        FileChangeTable.delete(db, change_id)

    runner = get_runner(change.session_id)
    if runner is not None:
        runner.resolve_confirm(change_id, "rejected")

    return {"code": 0, "message": "ok", "data": {"change_id": change_id, "status": "rejected"}}


@router.post("/changes/{change_id}/revert")
def revert_change(change_id: int):
    """L2 撤销：用 old_content 还原文件。

    冲突检测：撤销前对比「文件当前内容」与「该变更的 new_content」——
    一致才允许撤销；不一致则不做任何修改，返回 409 + conflict 识别信息
    （文件可能被其他会话/人手修改过）。
    """
    with database.get_session() as db:
        change = FileChangeTable.get(db, change_id)
        if change is None:
            raise HTTPException(status_code=404, detail=f"变更不存在：{change_id}")
        if change.status != "applied":
            raise HTTPException(status_code=400, detail=f"变更 {change_id} 当前状态为 {change.status}，无法撤销")

        workspace = _resolve_workspace(change)
        target = _safe_target(workspace, change.file_path)
        current = target.read_text(encoding="utf-8") if target.exists() else ""

        # 冲突检测：当前内容与该变更应用后的内容不一致 → 不做任何修改，返回识别信息
        if current != change.new_content:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": f"文件 {change.file_path} 已被其他修改（当前内容与变更记录不一致），未执行撤销",
                    "conflict": True,
                    "current": current[:500],
                    "expected": change.new_content[:500],
                },
            )

        target.write_text(change.old_content, encoding="utf-8")
        FileChangeTable.delete(db, change_id)

    return {"code": 0, "message": "ok", "data": {"change_id": change_id, "status": "reverted"}}
