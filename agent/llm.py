"""LLM 客户端：通义千问（OpenAI 兼容模式）。

封装 openai SDK 对百炼 dashscope compatible-mode 的调用。
当前为最小实现：普通对话 + 原生 tool calling（非流式），
后续在此基础之上添加流式输出、重试、token 统计等。
"""

import os
from typing import Optional

from openai import OpenAI

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.7-flash"


class LLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
    ):
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "缺少 DASHSCOPE_API_KEY：请通过环境变量或 .env 文件提供 API Key"
            )
        self.model = model or os.environ.get("QWEN_MODEL") or DEFAULT_MODEL
        self.client = OpenAI(api_key=self.api_key, base_url=base_url)

    def chat(self, messages: list, tools: Optional[list] = None, temperature: float = 0.3):
        """发送对话请求，支持原生 tool calling。

        messages: OpenAI 格式的对话消息列表
        tools:    OpenAI 格式的工具定义列表（JSON schema）
        返回:     完整响应对象（resp.choices[0].message 可拿到 content / tool_calls）
        """
        kwargs = {"model": self.model, "messages": messages, "temperature": temperature}
        if tools:
            kwargs["tools"] = tools
        return self.client.chat.completions.create(**kwargs)
