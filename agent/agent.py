"""Agent 编排器：组装 LLM、工具、提示词、策略、权限，对外提供统一执行入口。

职责：
- 组装系统提示词、工具注册表、LLM 客户端（依赖注入，便于测试与替换）
- 通过事件回调（on_event）向 CLI / WebSocket 实时推送运行过程
- LLM 调用预算护栏：单任务调用次数超限强制中止（防止失控烧额度）
- 三级权限：工具可见性过滤（L1/L2 无 git）+ L1 软修改确认等待
- 兜底错误处理：策略运行异常时返回错误信息而非崩溃
"""

import os
from typing import Awaitable, Callable, Optional

from .events import ERROR, DONE, REQUEST_CONFIRMATION, make_event
from .llm import LLMClient
from .permissions import FileChange, PermissionLevel, PermissionManager
from .prompts import build_system_prompt
from .sandbox import get_workspace
from .strategies import AgentStrategy, get_strategy
from .tools import ToolRegistry, build_default_registry

# 感知权限的文件工具（注入 PermissionManager）
_PERMISSION_AWARE_TOOLS = ("write_file", "read_file", "edit_file")


class Agent:
    def __init__(
        self,
        llm: Optional[LLMClient] = None,
        registry: Optional[ToolRegistry] = None,
        strategy: Optional[AgentStrategy] = None,
        workspace: Optional[str] = None,
        on_event: Optional[Callable[[dict], None]] = None,
        max_llm_calls: Optional[int] = None,
        permission_level: int | PermissionLevel = PermissionLevel.L3,
        confirm_callback: Optional[Callable[[FileChange], Awaitable[str]]] = None,
    ):
        self.llm = llm or LLMClient()
        # code_review / generate_test 等依赖 LLM 的工具需要注入客户端
        self.registry = registry or build_default_registry(llm=self.llm)
        self.strategy = strategy or get_strategy("react")
        self.system_prompt = build_system_prompt(workspace)
        self.on_event = on_event or (lambda event: None)
        # 预算护栏：单任务 LLM 调用次数上限（环境变量 MAX_LLM_CALLS 可覆盖）
        self.llm_calls = 0
        self.max_llm_calls = max_llm_calls or int(os.environ.get("MAX_LLM_CALLS", "60"))
        # 三级权限
        self.permissions = PermissionManager(PermissionLevel(permission_level))
        self.confirm_callback = confirm_callback
        self._inject_permissions()

    def _inject_permissions(self) -> None:
        """给文件类工具注入 PermissionManager（write/edit/read 感知权限）。"""
        for name in _PERMISSION_AWARE_TOOLS:
            self.registry.get(name).permissions = self.permissions

    def emit(self, event: dict) -> None:
        """推送事件给外部（CLI 打印 / WebSocket 推送）。"""
        self.on_event(event)

    async def call_llm(self, *args, **kwargs):
        """LLM 调用统一入口：计数 + 预算护栏，超限抛异常终止任务。"""
        self.llm_calls += 1
        if self.llm_calls > self.max_llm_calls:
            raise RuntimeError(
                f"LLM 调用预算超限（>{self.max_llm_calls} 次），任务中止以控制成本"
            )
        return await self.llm.chat_async(*args, **kwargs)

    # ---------- 权限 ----------

    def tool_schemas(self) -> list[dict]:
        """按权限级别过滤后的工具 schema（L1/L2 不含 git 工具）。"""
        return self.permissions.filter_schemas(self.registry.schemas())

    def is_tool_allowed(self, tool_name: str) -> bool:
        return self.permissions.is_tool_allowed(tool_name)

    async def wait_confirmation(self, change: FileChange) -> str:
        """L1：暂停循环等待用户确认。返回 "confirmed" 或 "rejected"。"""
        self.emit(make_event(
            REQUEST_CONFIRMATION,
            change_id=change.change_id,
            file_path=change.file_path,
            operation=change.operation,
            diff=change.diff_preview,
        ))
        if self.confirm_callback is not None:
            try:
                return await self.confirm_callback(change)
            except Exception:
                return "rejected"
        return "rejected"  # 无确认回调时默认拒绝（安全优先）

    async def run(self, task: str) -> str:
        """执行任务，返回最终回复文本。"""
        try:
            return await self.strategy.run(task, self)
        except Exception as e:
            self.emit(make_event(ERROR, content=f"agent 运行异常：{type(e).__name__}: {e}"))
            self.emit(make_event(DONE, iterations=0, llm_calls=self.llm_calls))
            return f"任务运行失败：{type(e).__name__}: {e}"
