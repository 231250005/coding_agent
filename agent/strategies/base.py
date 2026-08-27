"""策略抽象基类：所有推理策略统一接口。

策略决定"agent 如何组织思考与行动"——这是推理框架可插拔的关键：
新增策略只需继承 AgentStrategy 并实现 run()，注册一行即可生效。
当前唯一策略：react（规范化 tool-calling 循环）。
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 避免循环导入：agent.py 导入 strategies，strategies 引用 agent 类型
    from ..agent import Agent


class AgentStrategy(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    async def run(self, task: str, agent: "Agent") -> str:
        """执行任务，返回最终回复文本。

        agent 参数提供执行所需的全部能力：
        - agent.llm         LLM 客户端（chat_async）
        - agent.registry    工具注册表（schemas/execute）
        - agent.emit()      事件回调（CLI 打印 / WebSocket 推送）
        - agent.system_prompt  系统提示词
        """
        raise NotImplementedError
