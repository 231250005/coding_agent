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

    def validate(self, args: dict) -> tuple[bool, str]:
        """基本参数校验：检查必填参数（schema required）是否缺失/为空。

        返回 (是否通过, 错误信息)。错误信息可行动：指明缺哪个参数、期望类型与含义，
        模型收到后能立即重新发起正确调用。
        """
        required = self.parameters.get("required") or []
        for name in required:
            if name not in args or args.get(name) in (None, ""):
                prop = self.parameters.get("properties", {}).get(name, {})
                return False, (
                    f"参数校验失败：缺少必填参数 {name}（{name}: {prop.get('type', '?')}"
                    f"，{prop.get('description', '')}）。请重新发起完整、合法的工具调用。"
                )
        return True, ""

    @abstractmethod
    def execute(self, args: dict) -> dict:
        """执行工具。

        args: 模型按 schema 生成的参数
        返回: {"ok": bool, "output": str, ...} —— ok 表示是否成功，
             output 是回填给模型的文本结果。
        """
        raise NotImplementedError
