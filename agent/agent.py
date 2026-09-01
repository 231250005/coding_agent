"""Agent 编排器：组装 LLM、工具、提示词、策略、权限，对外提供统一执行入口。

职责：
- 组装系统提示词、工具注册表、LLM 客户端（依赖注入，便于测试与替换）
- 通过事件回调（on_event）向 CLI / WebSocket 实时推送运行过程
- LLM 调用预算护栏：单任务调用次数超限强制中止（防止失控烧额度）
- 三级权限：工具可见性过滤（L1/L2 无 git）+ L1 软修改确认等待
- 兜底错误处理：策略运行异常时返回错误信息而非崩溃
"""

import asyncio
import os
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .context import ContextManager
from .events import ERROR, DONE, REQUEST_CONFIRMATION, make_event
from .llm import LLMClient
from .permissions import FileChange, PermissionLevel, PermissionManager
from .prompts import AGENTS_MD_FULL_LIMIT, build_system_prompt
from .sandbox import get_workspace, set_workspace
from .strategies import AgentStrategy, get_strategy
from .tools import ToolRegistry, build_default_registry

# 感知权限的文件工具（注入 PermissionManager；generate_test 也会写文件）
_PERMISSION_AWARE_TOOLS = ("write_file", "read_file", "edit_file", "generate_test")


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
        permissions: Optional[PermissionManager] = None,
        confirm_callback: Optional[Callable[[FileChange], Awaitable[str]]] = None,
        change_sink: Optional[Callable] = None,
    ):
        self.llm = llm or LLMClient()
        # code_review / generate_test 等依赖 LLM 的工具需要注入客户端
        self.registry = registry or build_default_registry(llm=self.llm)
        self.strategy = strategy or get_strategy("react")
        self.workspace = workspace
        self.system_prompt = build_system_prompt(workspace)
        # 超长 AGENTS.md（>全文注入上限）：标记待异步摘要（不阻塞构建事件循环）
        self._agents_md_pending: Optional[str] = None
        self._detect_long_agents_md(workspace)
        self.on_event = on_event or (lambda event: None)
        # 预算护栏：单任务 LLM 调用次数上限（环境变量 MAX_LLM_CALLS 可覆盖）
        self.llm_calls = 0
        self.max_llm_calls = max_llm_calls or int(os.environ.get("MAX_LLM_CALLS", "60"))
        # 三级权限：支持注入会话级共享 manager（Web 场景多任务复用、变更累积）；
        # 未注入时新建（CLI 场景），change_sink 为可选持久化钩子
        if permissions is not None:
            self.permissions = permissions
            self.permissions.level = PermissionLevel(permission_level)
        else:
            self.permissions = PermissionManager(
                PermissionLevel(permission_level), change_sink=change_sink
            )
        self.confirm_callback = confirm_callback
        self._inject_permissions()
        # 上下文管理（token 估算 + 长对话压缩）
        self.context = ContextManager()

    def _detect_long_agents_md(self, workspace: Optional[str]) -> None:
        """超长 AGENTS.md（>4000 字符）：记录内容，run() 时异步 LLM 摘要注入。"""
        ws = Path(workspace) if workspace else get_workspace()
        p = ws / "AGENTS.md"
        if not p.is_file():
            return
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        if len(content) > AGENTS_MD_FULL_LIMIT:
            self._agents_md_pending = content

    async def _summarize_agents_md(self, content: str) -> Optional[str]:
        """LLM 摘要 AGENTS.md（线程池执行，不阻塞事件循环）。失败降级不注入。"""
        prompt = (
            "请把以下项目规范文件（AGENTS.md）压缩为不超过 500 字的摘要，"
            "必须保留：命令、依赖、代码规范、重要约束。\n\n"
        ) + content[:12000]
        try:
            resp = await asyncio.to_thread(
                self.llm.chat,
                [{"role": "system", "content": "你是项目规范整理员。"},
                 {"role": "user", "content": prompt}],
                0.2,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception:
            return None

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

    async def finalize_commit(self, task: str) -> str:
        """L3：任务运行完成后自动提交全部改动（如有 git 仓库）。

        返回提交说明文本；非 L3 / 非 git 仓库 / 无改动时返回空串（不阻塞任务）。
        """
        if self.permissions.level != PermissionLevel.L3:
            return ""
        try:
            from .tools.git_tools import GitCommitTool

            message = f"agent 任务完成：{task[:50]}"
            r = GitCommitTool().execute({"message": message})
            if r.get("ok"):
                return r["output"]
            return ""  # 非仓库或无可提交改动：静默跳过
        except Exception:
            return ""

    async def run(self, task: str, history: Optional[list] = None) -> str:
        """执行任务，返回最终回复文本。

        history: 跨任务对话历史（多轮记忆），由 server 层从会话记录加载。
        """
        # 设置当前任务工作区（asyncio 任务隔离，多会话互不干扰）
        set_workspace(self.workspace)
        # 超长 AGENTS.md：异步摘要后注入系统提示词（信息保留主干，非硬截断）
        if self._agents_md_pending:
            summary = await self._summarize_agents_md(self._agents_md_pending)
            if summary:
                self.system_prompt += "\n\n## 项目规范（AGENTS.md 摘要）\n" + summary
            self._agents_md_pending = None
        try:
            return await self.strategy.run(task, self, history=history)
        except Exception as e:
            self.emit(make_event(ERROR, content=f"agent 运行异常：{type(e).__name__}: {e}"))
            self.emit(make_event(DONE, iterations=0, llm_calls=self.llm_calls))
            return f"任务运行失败：{type(e).__name__}: {e}"
