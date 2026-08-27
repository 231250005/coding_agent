"""策略注册表：管理与选择推理策略（可插拔）。

当前策略：
- react（默认）：规范化 ReAct 循环——思考 → 调用现有工具 → 观察结果，
  循环直到模型认为任务完成（见 PLAN §4）

新增策略只需继承 AgentStrategy + 在 _DEFAULT_STRATEGIES 注册一行。
"""

from .base import AgentStrategy
from .react import ReActStrategy

__all__ = ["AgentStrategy", "StrategyRegistry", "get_strategy", "list_strategies"]

_DEFAULT_STRATEGIES = [ReActStrategy()]


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


def get_strategy(name: str = "react") -> AgentStrategy:
    """获取默认注册表中的策略实例。"""
    registry = StrategyRegistry()
    for strategy in _DEFAULT_STRATEGIES:
        registry.register(strategy)
    return registry.get(name)


def list_strategies() -> list[str]:
    return [s.name for s in _DEFAULT_STRATEGIES]
