"""文件操作类工具：read_file / write_file / edit_file。

感知三级权限（见 agent/permissions.py）：
- L1：写操作进入 pending 队列等待用户确认，不落盘；read_file 读取 pending 虚拟内容
- L2：直接落盘 + 记录变更（可撤销）
- L3：同 L2 + 写改成功后自动 git commit（如有仓库）
"""

from ..permissions import PermissionLevel, PermissionManager
from ..sandbox import MAX_READ_LINES, get_workspace, safe_join, truncate, truncate_with_meta
from .base import Tool

# L3 自动提交改为任务完成时统一触发（见 Agent.finalize_commit），
# 写/改文件阶段不做单步提交。


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

    def __init__(self, permissions: PermissionManager | None = None):
        self.permissions = permissions

    def execute(self, args: dict) -> dict:
        try:
            path = safe_join(str(args["path"]))
            content = str(args.get("content", ""))
            rel = path.relative_to(get_workspace()).as_posix()

            # 权限模式：L1 软修改（等确认） / L2/L3 直接写 + 记录
            if self.permissions is not None:
                old_content = path.read_text(encoding="utf-8") if path.is_file() else ""
                change = self.permissions.add_change(rel, "write", old_content, content, path)
                if self.permissions.level == PermissionLevel.L1:
                    return {
                        "ok": True,
                        "output": (
                            f"已暂存对 {rel} 的修改（等待用户确认，change_id={change.change_id}）。"
                            f"用户确认后才真正写入。"
                        ),
                        "pending_change": change.change_id,
                        "written": False,
                    }
                self._write(path, content)
                return {"ok": True, "output": f"已写入文件 {rel}（{len(content)} 字符）"}

            # 无权限管理：直接写（原行为）
            self._write(path, content)
            return {
                "ok": True,
                "output": f"已写入文件 {rel}（{len(content)} 字符，{content.count(chr(10)) + 1} 行）",
            }
        except Exception as e:
            return {"ok": False, "output": f"写入失败：{e}"}

    @staticmethod
    def _write(path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


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

    def __init__(self, permissions: PermissionManager | None = None):
        self.permissions = permissions

    def execute(self, args: dict) -> dict:
        try:
            path = safe_join(str(args["path"]))
            rel = path.relative_to(get_workspace()).as_posix()
            # L1 权限下：若该文件有 pending 变更，读取"虚拟内容"（待确认的新内容）
            virtual = None
            if self.permissions is not None and self.permissions.level == PermissionLevel.L1:
                pending = self.permissions.latest_pending_for(rel)
                if pending is not None:
                    virtual = pending.new_content
            if not path.is_file() and virtual is None:
                return {"ok": False, "output": f"文件不存在：{rel}"}
            text = virtual if virtual is not None else path.read_text(encoding="utf-8")
            lines = text.splitlines()

            start = int(args.get("start_line") or 1)
            end = int(args.get("end_line") or len(lines))
            if start > len(lines):
                return {"ok": False, "output": f"起始行 {start} 超出文件总行数 {len(lines)}"}
            segment = lines[start - 1 : end]

            if len(segment) > MAX_READ_LINES:
                segment = segment[:MAX_READ_LINES]
                segment.append(f"… (范围过长，仅显示前 {MAX_READ_LINES} 行，可缩小 end_line 继续读取)…")
            numbered = "\n".join(f"{i + 1:>4} | {line}" for i, line in enumerate(segment, start=start))
            out, truncated, total = truncate_with_meta(numbered)
            result = {"ok": True, "output": out}
            if truncated:
                result["truncated"] = True
                result["total_chars"] = total
            return result
        except Exception as e:
            return {"ok": False, "output": f"读取失败：{e}"}


class EditFileTool(Tool):
    name = "edit_file"
    description = (
        "精确修改文件：把 old_string 替换为 new_string（可含多行）。"
        "用于局部修改，避免整文件重写。old_string 需在文件中唯一匹配；"
        "行尾空白差异会自动容错。匹配不唯一或不匹配时会返回可行动的错误提示。"
        "path 必须是相对工作区的相对路径。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "相对工作区的文件路径，如 game.py",
            },
            "old_string": {
                "type": "string",
                "description": "要替换的原文（必须与文件内容精确一致，可包含多行；需要包含足够上下文以保证唯一匹配）",
            },
            "new_string": {
                "type": "string",
                "description": "替换后的内容",
            },
            "replace_all": {
                "type": "boolean",
                "description": "true 时替换所有出现位置（默认 false，只替换唯一匹配）",
            },
        },
        "required": ["path", "old_string", "new_string"],
    }

    def __init__(self, permissions: PermissionManager | None = None):
        self.permissions = permissions

    def execute(self, args: dict) -> dict:
        try:
            path = safe_join(str(args["path"]))
            if not path.is_file():
                return {"ok": False, "output": f"文件不存在：{path.relative_to(get_workspace()).as_posix()}"}
            old_string = str(args["old_string"])
            new_string = str(args["new_string"])
            replace_all = bool(args.get("replace_all", False))

            text = path.read_text(encoding="utf-8")

            # ── 第一层：精确子串匹配（最常用）──
            count = text.count(old_string)
            if count == 1:
                return self._finalize(
                    path, text.replace(old_string, new_string),
                    *self._line_range(text, old_string), 1, replace_all=False,
                )
            if count > 1 and not replace_all:
                return self._ambiguous_error(text, count, first_pos=text.find(old_string), second_pos=text.find(old_string, text.find(old_string) + 1))
            if count > 1 and replace_all:
                return self._finalize(
                    path, text.replace(old_string, new_string),
                    *self._line_range(text, old_string), count, replace_all=True,
                )

            # ── 第二层：整行容错匹配（行尾空白 / \r\n 差异）──
            file_lines = text.split("\n")
            old_lines = old_string.split("\n")
            if len(old_lines) > len(file_lines):
                return {"ok": False, "output": f"old_string 有 {len(old_lines)} 行，超过文件总行数 {len(file_lines)}"}
            norm_file = [line.rstrip() for line in file_lines]
            norm_old = [line.rstrip() for line in old_lines]
            matches = [
                i
                for i in range(len(norm_file) - len(norm_old) + 1)
                if norm_file[i : i + len(norm_old)] == norm_old
            ]
            if not matches:
                return {
                    "ok": False,
                    "output": (
                        f"未找到匹配内容。old_string 与文件内容不一致"
                        f"（文件共 {self._line_count(file_lines)} 行）。"
                        f"建议先用 read_file 查看文件实际内容，再重试；"
                        f"或缩小/调整 old_string 使其与文件完全一致。"
                    ),
                }
            if len(matches) > 1 and not replace_all:
                return self._ambiguous_error(text, len(matches), first_pos=None, second_pos=None)
            if replace_all:
                for i in reversed(matches):
                    file_lines[i : i + len(old_lines)] = new_string.split("\n")
            else:
                i = matches[0]
                file_lines[i : i + len(old_lines)] = new_string.split("\n")
            return self._finalize(
                path, "\n".join(file_lines),
                matches[0] + 1, matches[0] + len(old_lines),
                len(matches) if replace_all else 1, replace_all,
            )
        except Exception as e:
            return {"ok": False, "output": f"修改失败：{e}"}

    # ── 写盘（感知权限） ──

    def _finalize(self, path, new_text: str, first: int, last: int, count: int, replace_all: bool) -> dict:
        """把编辑结果落盘。L1 走 pending 等待确认；L2/L3 直接写 + 记录；L3 自动 commit。"""
        rel = path.relative_to(get_workspace()).as_posix()
        count_txt = f"全部 {count} 处" if replace_all else f"{count} 处"
        base_msg = f"已修改 {rel}（{count_txt}，原内容在第 {first}-{last} 行）"

        if self.permissions is not None:
            old_content = path.read_text(encoding="utf-8")
            change = self.permissions.add_change(rel, "edit", old_content, new_text, path)
            if self.permissions.level == PermissionLevel.L1:
                return {
                    "ok": True,
                    "output": f"已暂存对 {rel} 的修改（等待用户确认，change_id={change.change_id}）。用户确认后才真正写入。",
                    "pending_change": change.change_id,
                    "written": False,
                }
            WriteFileTool._write(path, new_text)
            return {"ok": True, "output": base_msg}

        WriteFileTool._write(path, new_text)
        return {"ok": True, "output": base_msg}

    # ── 辅助 ──

    @staticmethod
    def _line_range(text: str, old: str) -> tuple[int, int]:
        """子串在文本中的起始/结束行号。"""
        idx = text.find(old)
        head = text[:idx]
        start = head.count("\n") + 1
        end = start + old.count("\n")
        return start, end

    @staticmethod
    def _line_count(file_lines: list[str]) -> int:
        """文件行数（忽略末尾空行）。"""
        n = len(file_lines)
        if n > 0 and file_lines[-1] == "":
            n -= 1
        return n

    @staticmethod
    def _ambiguous_error(text: str, count: int, first_pos, second_pos) -> dict:
        if first_pos is not None and second_pos is not None:
            first_line = text[:first_pos].count("\n") + 1
            second_line = text[:second_pos].count("\n") + 1
            detail = f"（如第 {first_line} 行、第 {second_line} 行）"
        else:
            detail = ""
        return {
            "ok": False,
            "output": (
                f"old_string 在文件中出现 {count} 处{detail}，匹配不唯一。"
                f"请扩大 old_string 范围（包含更多上下文，如前后行）使其唯一，"
                f"或设置 replace_all=true 替换全部。"
            ),
        }

    @staticmethod
    def _write_result(path, new_text: str, first: int, last: int, count, replace_all: bool) -> dict:
        path.write_text(new_text, encoding="utf-8")
        rel = path.relative_to(get_workspace()).as_posix()
        count_txt = f"全部 {count} 处" if replace_all else f"{count} 处"
        return {"ok": True, "output": f"已修改 {rel}（{count_txt}，原内容在第 {first}-{last} 行）"}
