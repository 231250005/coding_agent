"""Agent 编排器：组装 LLM、工具、提示词、策略，对外提供统一执行入口。

职责：
- 组装系统提示词、工具注册表、LLM 客户端（依赖注入，便于测试与替换）
- 通过事件回调（on_event）向 CLI / WebSocket 实时推送运行过程
- 兜底错误处理：策略运行异常时返回错误信息而非崩溃
"""

from typing import Callable, Optional

from .events import ERROR, DONE, make_event
from .llm import LLMClient
from .prompts import build_system_prompt
from .sandbox import get_workspace
from .strategies import AgentStrategy, get_strategy
from .tools import ToolRegistry, build_default_registry


class Agent:
    def __init__(
        self,
        llm: Optional[LLMClient] = None,
        registry: Optional[ToolRegistry] = None,
        strategy: Optional[AgentStrategy] = None,
        workspace: Optional[str] = None,
        on_event: Optional[Callable[[dict], None]] = None,
    ):
        self.llm = llm or LLMClient()
        # code_review 等依赖 LLM 的工具需要注入客户端
        self.registry = registry or build_default_registry(llm=self.llm)
        self.strategy = strategy or get_strategy("plan_execute")
        self.system_prompt = build_system_prompt(workspace)
        self.on_event = on_event or (lambda event: None)

    def emit(self, event: dict) -> None:
        """推送事件给外部（CLI 打印 / WebSocket 推送）。"""
        self.on_event(event)

    async def run(self, task: str) -> str:
        """执行任务，返回最终回复文本。"""
        try:
            return await self.strategy.run(task, self)
        except Exception as e:
            self.emit(make_event(ERROR, content=f"agent 运行异常：{type(e).__name__}: {e}"))
            self.emit(make_event(DONE, iterations=0))
            return f"任务运行失败：{type(e).__name__}: {e}"
