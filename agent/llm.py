"""LLM 客户端：通义千问（OpenAI 兼容模式）。

封装 openai SDK 对百炼 dashscope compatible-mode 的调用：
- chat()       同步调用（简单场景）
- chat_async() 异步调用（agent 主循环使用），带指数退避重试
支持原生 tool calling（tools 参数），仅使用 chat.completions 接口（合规）。
"""

import asyncio
import os
from typing import Optional

from openai import AsyncOpenAI, OpenAI

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.7-flash"
MAX_RETRIES = 3


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
        self.async_client = AsyncOpenAI(api_key=self.api_key, base_url=base_url)

    def _build_kwargs(self, messages: list, tools: Optional[list], temperature: float) -> dict:
        kwargs = {"model": self.model, "messages": messages, "temperature": temperature}
        if tools:
            kwargs["tools"] = tools
        return kwargs

    def chat(self, messages: list, tools: Optional[list] = None, temperature: float = 0.3):
        """同步调用（冒烟测试/调试用）。"""
        return self.client.chat.completions.create(
            **self._build_kwargs(messages, tools, temperature)
        )

    async def chat_async(
        self,
        messages: list,
        tools: Optional[list] = None,
        temperature: float = 0.3,
        max_retries: int = MAX_RETRIES,
    ):
        """异步调用（agent 主循环使用），带指数退避重试。

        网络抖动 / 限流等临时错误会自动重试（1s、2s、4s 退避）；
        重试耗尽后抛出异常，由上层策略处理。
        """
        for attempt in range(max_retries):
            try:
                return await self.async_client.chat.completions.create(
                    **self._build_kwargs(messages, tools, temperature)
                )
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2**attempt)  # 1s、2s、4s 指数退避
        raise RuntimeError("unreachable")  # pragma: no cover
