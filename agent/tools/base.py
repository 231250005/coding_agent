"""工具抽象基类：每个工具 = JSON schema 定义 + 本地执行实现。

- name/description/parameters 决定模型"怎么看这个工具"（to_schema 导出给 LLM）
- execute() 决定"工具实际做什么"（在本地执行，不依赖任何云端工具）
"""

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    name: str = ""
    description: str = ""
    parameters: dict = {}

    def to_schema(self) -> dict:
        """导出为 OpenAI 函数调用格式的 JSON schema，供 LLM 识别。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @abstractmethod
    def execute(self, args: dict) -> dict:
        """执行工具。

        args: 模型按 schema 生成的参数
        返回: {"ok": bool, "output": str, ...} —— ok 表示是否成功，
             output 是回填给模型的文本结果。
        """
        raise NotImplementedError
