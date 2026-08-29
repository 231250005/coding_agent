"""文件系统浏览接口：前端「选择工作目录」的目录树。

- GET /api/fs/dirs?path=... ：返回指定绝对路径下的子目录列表
- path 缺省：返回根（Windows 盘符列表 / Linux 根）
- 仅目录、按名称排序、正斜杠路径、隐藏目录省略
"""

import os
import string
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/fs", tags=["fs"])


def _list_roots() -> list[dict]:
    """可选根：Windows 返回存在的盘符，Linux/macOS 返回 /。"""
    if os.name == "nt":
        roots = []
        for letter in string.ascii_uppercase:
            drive = f"{letter}:/"
            if os.path.exists(drive):
                roots.append({"name": f"{letter}:", "path": drive})
        return roots
    return [{"name": "/", "path": "/"}]


@router.get("/dirs")
def list_dirs(path: str | None = None):
    """浏览目录：返回子目录列表 + 上级目录（供「返回上级」按钮）。"""
    # 根请求（path 缺省）：返回可选根
    if not path or not path.strip():
        return {"code": 0, "message": "ok", "data": {"path": "", "parent": "", "dirs": _list_roots()}}

    p = Path(path)
    if not p.is_dir():
        raise HTTPException(status_code=400, detail=f"目录不存在或无法访问: {path}")
    try:
        dirs = []
        for child in sorted(p.iterdir(), key=lambda x: x.name.lower()):
            if not child.is_dir():
                continue
            name = child.name
            if name.startswith(".") or name.endswith("$"):  # 隐藏目录省略
                continue
            dirs.append({"name": name, "path": child.as_posix()})
    except PermissionError:
        raise HTTPException(status_code=400, detail=f"目录不存在或无法访问: {path}")

    current = p.as_posix()
    parent = p.parent.as_posix()
    if parent == current:  # 已在根（如 D:/ 的上级仍是 D:/）
        parent = ""
    return {"code": 0, "message": "ok", "data": {"path": current, "parent": parent, "dirs": dirs}}
