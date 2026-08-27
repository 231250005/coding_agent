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
        "path 必须是相对工作区的相对路径。"
        "大文件可指定 start_line/end_line 分段读取（文件过长会自动截断）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "相对工作区的文件路径，如 game.py",
            },
            "start_line": {
                "type": "integer",
                "description": "起始行号（从 1 开始），仅读取该行到 end_line 之间的内容",
                "minimum": 1,
            },
            "end_line": {
                "type": "integer",
                "description": "结束行号（含），配合 start_line 分段读取大文件",
                "minimum": 1,
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

            start = int(args.get("start_line") or 1)
            end = int(args.get("end_line") or len(lines))
            if start > len(lines):
                return {"ok": False, "output": f"起始行 {start} 超出文件总行数 {len(lines)}"}
            segment = lines[start - 1 : end]

            if len(segment) > MAX_READ_LINES:
                segment = segment[:MAX_READ_LINES]
                segment.append(f"… (范围过长，仅显示前 {MAX_READ_LINES} 行，可缩小 end_line 继续读取)…")
            numbered = "\n".join(f"{i + 1:>4} | {line}" for i, line in enumerate(segment, start=start))
            return {"ok": True, "output": truncate(numbered)}
        except Exception as e:
            return {"ok": False, "output": f"读取失败：{e}"}
