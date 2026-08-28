"""探索类工具：list_dir / grep / glob / find_symbols —— 代码库阅读理解。"""

import ast
import os
import re
from pathlib import Path

from ..sandbox import get_workspace, safe_join, truncate
from .base import Tool

# 搜索时跳过的目录（隐藏/依赖/缓存）
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".pytest_cache", "dist", "build"}

MAX_GREP_RESULTS = 50
MAX_GLOB_RESULTS = 100


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


class GrepTool(Tool):
    name = "grep"
    description = (
        "在工作区文件中搜索文本/正则，返回 文件:行号:匹配行。"
        "用于定位关键字（如函数调用处、报错信息、TODO）。"
        "pattern 为 Python 正则；path 可为文件或目录（限定搜索范围）；"
        "file_glob 可限定文件类型（如 *.py）。自动跳过 .git/缓存/依赖目录。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "要搜索的正则表达式，如 def add|TODO"},
            "path": {"type": "string", "description": "要搜索的文件或目录（相对工作区，可选）"},
            "file_glob": {"type": "string", "description": "限定文件类型（如 *.py、*.md，可选；仅目录搜索时生效）"},
        },
        "required": ["pattern"],
    }

    def execute(self, args: dict) -> dict:
        try:
            pattern = str(args["pattern"])
            base = safe_join(str(args.get("path") or "."))
            file_glob = str(args.get("file_glob") or "*")

            try:
                regex = re.compile(pattern)
            except re.error as e:
                return {"ok": False, "output": f"正则表达式无效：{e}"}

            results = []
            if base.is_file():
                # path 是文件：直接搜索该文件
                self._search_file(base, regex, results)
            elif base.is_dir():
                for p in base.rglob(file_glob):
                    if not p.is_file() or any(part in _SKIP_DIRS for part in p.parts):
                        continue
                    self._search_file(p, regex, results)
                    if len(results) >= MAX_GREP_RESULTS:
                        break
            else:
                return {"ok": False, "output": f"路径不存在：{args.get('path')}"}

            if not results:
                return {"ok": True, "output": f"未找到匹配「{pattern}」的内容。"}
            return {"ok": True, "output": truncate(f"找到 {len(results)} 处匹配：\n" + "\n".join(results))}
        except Exception as e:
            return {"ok": False, "output": f"搜索失败：{e}"}

    @staticmethod
    def _search_file(path: Path, regex: "re.Pattern", results: list) -> None:
        """在单个文件中搜索并追加匹配行。"""
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return
        for lineno, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                rel = path.relative_to(get_workspace()).as_posix()
                results.append(f"{rel}:{lineno}: {line.strip()[:120]}")
                if len(results) >= MAX_GREP_RESULTS:
                    break


class GlobTool(Tool):
    name = "glob"
    description = (
        "按文件名模式查找文件路径（支持 ** 递归，如 **/*.py、test_*.py、src/*.md）。"
        "用于了解项目文件分布、找所有测试文件等。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "文件模式，如 **/*.py"},
        },
        "required": ["pattern"],
    }

    def execute(self, args: dict) -> dict:
        try:
            pattern = str(args["pattern"])
            if pattern.startswith("/") or ".." in pattern:
                return {"ok": False, "output": "pattern 必须为相对工作区的模式"}
            matches = []
            for p in sorted(get_workspace().glob(pattern)):
                if any(part in _SKIP_DIRS for part in p.parts):
                    continue
                matches.append(p.relative_to(get_workspace()).as_posix())
                if len(matches) >= MAX_GLOB_RESULTS:
                    break
            if not matches:
                return {"ok": True, "output": f"没有匹配「{pattern}」的文件。"}
            return {"ok": True, "output": truncate(f"匹配到 {len(matches)} 个文件：\n" + "\n".join(matches))}
        except Exception as e:
            return {"ok": False, "output": f"查找失败：{e}"}


class FindSymbolsTool(Tool):
    name = "find_symbols"
    description = (
        "用 Python AST 解析指定文件，返回函数/类定义位置（文件名:行号 + 签名），零误报。"
        "用于定位要修改的函数/类；name 可过滤（子串匹配）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要解析的 Python 文件（相对工作区）"},
            "name": {"type": "string", "description": "按名称过滤（子串匹配，可选）"},
        },
        "required": ["path"],
    }

    def execute(self, args: dict) -> dict:
        try:
            path = safe_join(str(args["path"]))
            if not path.is_file():
                return {"ok": False, "output": f"文件不存在：{args['path']}"}
            rel = path.relative_to(get_workspace()).as_posix()
            name_filter = str(args.get("name") or "")

            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            results = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    kind = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                    signature = _format_signature(node)
                    results.append(f"{kind} {node.name} @ {rel}:{node.lineno}  {signature}")
                elif isinstance(node, ast.ClassDef):
                    results.append(f"class {node.name} @ {rel}:{node.lineno}")

            if name_filter:
                results = [r for r in results if name_filter in r]
            if not results:
                hint = f"（含「{name_filter}」）" if name_filter else ""
                return {"ok": True, "output": f"未在 {rel} 中找到符号{hint}。"}
            return {"ok": True, "output": truncate(f"{rel} 中的符号（{len(results)} 个）：\n" + "\n".join(results))}
        except SyntaxError as e:
            return {"ok": False, "output": f"文件存在语法错误，无法解析：{e}"}
        except Exception as e:
            return {"ok": False, "output": f"解析失败：{e}"}


def _format_signature(node) -> str:
    """从 AST 节点构造简化的函数签名。"""
    parts = []
    for a in node.args.args:
        parts.append(a.arg)
    if node.args.vararg:
        parts.append(f"*{node.args.vararg.arg}")
    if node.args.kwarg:
        parts.append(f"**{node.args.kwarg.arg}")
    return f"({', '.join(parts)})"
