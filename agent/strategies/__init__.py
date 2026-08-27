"""策略注册表：管理与选择推理策略（可插拔，非单一固定工作流）。

当前策略：
- plan_execute（默认）：Plan-and-Execute 顶层外壳——任何任务先规划拆分子任务，
  子任务交给 ReAct 内核执行，收尾评审（见 PLAN §4）
- react：标准 ReAct 循环（子任务执行内核，也可独立运行简单任务）

新增策略只需继承 AgentStrategy + 在 _DEFAULT_STRATEGIES 注册一行。
"""

from .base import AgentStrategy
from .plan_execute import PlanExecuteStrategy
from .react import ReActStrategy

__all__ = ["AgentStrategy", "StrategyRegistry", "get_strategy", "list_strategies"]

_DEFAULT_STRATEGIES = [PlanExecuteStrategy(), ReActStrategy()]


class StrategyRegistry:
    def __init__(self):
        self._strategies: dict[str, AgentStrategy] = {}

    def register(self, strategy: AgentStrategy) -> None:
        self._strategies[strategy.name] = strategy

    def get(self, name: str) -> AgentStrategy:
        if name not in self._strategies:
            raise KeyError(f"未知策略：{name}（可用：{', '.join(self.names())}）")
        return self._strategies[name]

    def names(self) -> list[str]:
        return list(self._strategies.keys())


def get_strategy(name: str = "plan_execute") -> AgentStrategy:
    """获取默认注册表中的策略实例。"""
    registry = StrategyRegistry()
    for strategy in _DEFAULT_STRATEGIES:
        registry.register(strategy)
    return registry.get(name)


def list_strategies() -> list[str]:
    return [s.name for s in _DEFAULT_STRATEGIES]
