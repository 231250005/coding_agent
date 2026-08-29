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


# 搜索结果上限
MAX_RESOLVE_MATCHES = 10


@router.get("/resolve")
def resolve_dir(name: str | None = None):
    """按文件夹名搜索绝对路径候选（前端原生文件夹选择器配套）。

    浏览器原生对话框只能拿到文件夹名（拿不到绝对路径），
    选完后前端把名字传给本接口，后端在本机搜索同名文件夹返回候选。
    搜索范围：所有盘符根目录 + 一级子目录 + 用户主目录。
    找不到返回空数组（不报错），前端降级提示。
    """
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="缺少 name 参数")
    name = name.strip()
    matches: list[str] = []
    seen: set[str] = set()

    def _scan(base: Path, depth: int) -> None:
        """扫描 base 下 depth 层内的目录，收集同名匹配（不区分大小写）。"""
        if len(matches) >= MAX_RESOLVE_MATCHES:
            return
        try:
            for child in sorted(base.iterdir(), key=lambda x: x.name.lower()):
                if len(matches) >= MAX_RESOLVE_MATCHES:
                    return
                if not child.is_dir():
                    continue
                if child.name.startswith(".") or child.name.endswith("$"):
                    continue
                if child.name.lower() == name.lower():
                    p = child.as_posix()
                    if p not in seen:
                        seen.add(p)
                        matches.append(p)
                if depth > 0:
                    _scan(child, depth - 1)
        except (PermissionError, OSError):
            pass  # 无权限目录跳过

    if os.name == "nt":
        # Windows：所有盘符的根 + 一级子目录
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:/")
            if drive.exists():
                _scan(drive, depth=1)
    else:
        _scan(Path("/"), depth=1)

    # 用户主目录（Windows: C:/Users/<name>）
    home = Path.home()
    if home.exists():
        _scan(home, depth=1)

    matches.sort()
    return {
        "code": 0,
        "message": "ok",
        "data": {"name": name, "matches": matches[:MAX_RESOLVE_MATCHES]},
    }
