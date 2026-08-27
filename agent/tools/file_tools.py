"""文件操作类工具：read_file / write_file。"""

from ..sandbox import MAX_READ_LINES, get_workspace, safe_join, truncate
from .base import Tool


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "新建或覆盖写入一个文件（UTF-8 编码），自动创建缺失的父目录。"
        "path 必须是相对工作区的相对路径（如 game.py、src/utils.py），不允许访问工作区之外。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "相对工作区的文件路径，如 game.py",
            },
            "content": {
                "type": "string",
                "description": "要写入的完整文件内容",
            },
        },
        "required": ["path", "content"],
    }

    def execute(self, args: dict) -> dict:
        try:
            path = safe_join(str(args["path"]))
            content = str(args.get("content", ""))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            rel = path.relative_to(get_workspace()).as_posix()
            return {
                "ok": True,
                "output": f"已写入文件 {rel}（{len(content)} 字符，{content.count(chr(10)) + 1} 行）",
            }
        except Exception as e:
            return {"ok": False, "output": f"写入失败：{e}"}


class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "读取文件内容（UTF-8），输出带行号，便于定位问题。"
        "path 必须是相对工作区的相对路径。文件过长时自动截断。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "相对工作区的文件路径，如 game.py",
            },
        },
        "required": ["path"],
    }

    def execute(self, args: dict) -> dict:
        try:
            path = safe_join(str(args["path"]))
            if not path.is_file():
                return {"ok": False, "output": f"文件不存在：{path.relative_to(get_workspace()).as_posix()}"}
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) > MAX_READ_LINES:
                lines = lines[:MAX_READ_LINES]
                lines.append(f"… (文件过长，仅显示前 {MAX_READ_LINES} 行)…")
            numbered = "\n".join(f"{i + 1:>4} | {line}" for i, line in enumerate(lines))
            return {"ok": True, "output": truncate(numbered)}
        except Exception as e:
            return {"ok": False, "output": f"读取失败：{e}"}
