"""三级权限系统（见 PLAN §8）。

- L1（最低）：软修改 —— 写/改文件先进 pending 队列，用户确认后才真正落盘
- L2（中级）：直接修改，但记录变更（含 old/new 内容），用户可一键撤销
- L3（最高）：L2 基础上写/改文件后自动 git commit（如有仓库）

实现分层：
1. 工具可见性过滤：L1/L2 不暴露 git 工具（模型无法调用）
2. 写操作行为差异：write/edit 工具感知权限，走 pending 或直接落盘
3. L1 确认机制：ReAct 循环检测 pending → 暂停等待用户确认 → 恢复

变更记录当前为内存存储（后续由 server 层接入 SQLite file_changes 表持久化）。
"""

from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Callable, Optional

# 持久化钩子：callable(change: FileChange, action: str) -> Optional[int]
# action: add（返回数据库 id）/ confirm / reject / revert
ChangeSink = Callable[["FileChange", str], Optional[int]]

# L1/L2 权限下对模型隐藏的 git 工具
GIT_TOOLS = {"git_status", "git_diff", "git_commit", "git_log"}


class PermissionLevel(IntEnum):
    L1 = 1
    L2 = 2
    L3 = 3


CHANGE_PENDING = "pending"    # L1 待确认
CHANGE_APPLIED = "applied"    # 已应用
CHANGE_REJECTED = "rejected"  # L1 用户拒绝
CHANGE_REVERTED = "reverted"  # L2 用户撤销


@dataclass
class FileChange:
    change_id: int
    file_path: str          # 相对工作区路径
    operation: str          # write / edit
    old_content: str
    new_content: str
    status: str = CHANGE_PENDING
    absolute: Optional[Path] = None  # 绝对路径（工具已校验安全）

    @property
    def diff_preview(self) -> str:
        """简化的变更预览（给确认面板/模型看）。"""
        old_lines = self.old_content.splitlines()
        new_lines = self.new_content.splitlines()
        lines = []
        for line in old_lines[:10]:
            lines.append(f"- {line}")
        if len(old_lines) > 10:
            lines.append(f"… (共 {len(old_lines)} 行)")
        for line in new_lines[:10]:
            lines.append(f"+ {line}")
        if len(new_lines) > 10:
            lines.append(f"… (共 {len(new_lines)} 行)")
        return "\n".join(lines) or "（空文件）"


class PermissionManager:
    """管理权限级别与文件变更记录。

    change_sink：可选的持久化钩子（Web 场景由 server 注入，写 file_changes 表）；
    CLI 场景为 None（纯内存记录）。
    """

    def __init__(self, level: PermissionLevel = PermissionLevel.L3, change_sink: ChangeSink | None = None):
        self.level = level
        self.change_sink = change_sink
        self._changes: list[FileChange] = []
        self._next_id = 1

    # ---------- 变更记录 ----------

    def add_change(
        self,
        path: str,
        operation: str,
        old_content: str,
        new_content: str,
        absolute: Path,
    ) -> FileChange:
        """登记一次文件变更。L1 记为 pending（待确认），L2/L3 记为 applied。

        有 change_sink 时同步写数据库，并用数据库 id 对齐内存 id
        （前端拿到的 change_id 即数据库 id，confirm/revert 直接可用）。
        """
        status = CHANGE_PENDING if self.level == PermissionLevel.L1 else CHANGE_APPLIED
        change = FileChange(
            change_id=self._next_id,
            file_path=path,
            operation=operation,
            old_content=old_content,
            new_content=new_content,
            status=status,
            absolute=absolute,
        )
        self._next_id += 1
        if self.change_sink is not None:
            try:
                db_id = self.change_sink(change, "add")
                if db_id:
                    change.change_id = int(db_id)
            except Exception:
                pass  # 持久化失败不阻塞 agent 运行
        self._changes.append(change)
        return change

    def get(self, change_id: int) -> Optional[FileChange]:
        for c in self._changes:
            if c.change_id == change_id:
                return c
        return None

    def changes(self) -> list[FileChange]:
        return list(self._changes)

    def pending_changes(self) -> list[FileChange]:
        return [c for c in self._changes if c.status == CHANGE_PENDING]

    def latest_pending_for(self, path: str) -> Optional[FileChange]:
        """某个文件最新一条 pending 变更（L1 下 read_file 读虚拟内容用）。"""
        for c in reversed(self._changes):
            if c.file_path == path and c.status == CHANGE_PENDING:
                return c
        return None

    # ---------- L1 确认 / 拒绝 ----------

    def confirm(self, change_id: int) -> str:
        """L1：用户确认后真正写盘。"""
        change = self.get(change_id)
        if not change:
            return f"变更不存在：{change_id}"
        if change.status != CHANGE_PENDING:
            return f"变更 {change_id} 当前状态为 {change.status}，无法确认"
        self._apply(change)
        change.status = CHANGE_APPLIED
        self._notify_sink(change, "confirm")
        return f"已确认并应用变更 {change_id}（{change.file_path}）"

    def reject(self, change_id: int) -> str:
        """L1：用户拒绝，不落盘。"""
        change = self.get(change_id)
        if not change:
            return f"变更不存在：{change_id}"
        if change.status != CHANGE_PENDING:
            return f"变更 {change_id} 当前状态为 {change.status}，无法拒绝"
        change.status = CHANGE_REJECTED
        self._notify_sink(change, "reject")
        return f"已拒绝变更 {change_id}（{change.file_path}），文件未被修改"

    # ---------- L2 撤销 ----------

    def revert(self, change_id: int) -> str:
        """L2：撤销已应用的变更（用 old_content 还原文件）。"""
        change = self.get(change_id)
        if not change:
            return f"变更不存在：{change_id}"
        if change.status != CHANGE_APPLIED:
            return f"变更 {change_id} 当前状态为 {change.status}，无法撤销"
        self._apply_old(change)
        change.status = CHANGE_REVERTED
        self._notify_sink(change, "revert")
        return f"已撤销变更 {change_id}（{change.file_path}），文件已还原"

    # ---------- 持久化 ----------

    def _notify_sink(self, change: FileChange, action: str) -> None:
        if self.change_sink is None:
            return
        try:
            self.change_sink(change, action)
        except Exception:
            pass  # 持久化失败不阻塞 agent 运行

    # ---------- 内部 ----------

    @staticmethod
    def _apply(change: FileChange) -> None:
        change.absolute.parent.mkdir(parents=True, exist_ok=True)
        change.absolute.write_text(change.new_content, encoding="utf-8")

    @staticmethod
    def _apply_old(change: FileChange) -> None:
        change.absolute.write_text(change.old_content, encoding="utf-8")

    # ---------- 工具可见性 ----------

    def is_tool_allowed(self, tool_name: str) -> bool:
        """L1/L2 不暴露 git 工具。"""
        if self.level < PermissionLevel.L3 and tool_name in GIT_TOOLS:
            return False
        return True

    def filter_schemas(self, schemas: list[dict]) -> list[dict]:
        return [s for s in schemas if self.is_tool_allowed(s["function"]["name"])]
