"""探索类工具：list_dir —— 查看工作区目录结构。"""

import os

from ..sandbox import get_workspace, safe_join, truncate
from .base import Tool


class ListDirTool(Tool):
    name = "list_dir"
    description = (
        "列出工作区中某个目录下的条目（文件和子目录），目录名带 / 后缀。"
        "用于了解项目结构、确认文件是否已生成。path 省略时列出工作区根目录。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "相对工作区的目录路径，省略则列出根目录",
            },
        },
    }

    def execute(self, args: dict) -> dict:
        try:
            rel = str(args.get("path") or ".").strip() or "."
            base = safe_join(rel)
            if not base.is_dir():
                return {"ok": False, "output": f"目录不存在：{rel}"}
            entries = sorted(os.listdir(base))
            lines = [f"📁 {rel if rel != '.' else '.'}"]
            for entry in entries:
                full = base / entry
                suffix = "/" if full.is_dir() else ""
                marker = "dir" if full.is_dir() else "file"
                lines.append(f"  {entry}{suffix}  ({marker})")
            return {"ok": True, "output": truncate("\n".join(lines))}
        except Exception as e:
            return {"ok": False, "output": f"列出目录失败：{e}"}
