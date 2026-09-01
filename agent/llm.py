"""LLM 客户端：通义千问（OpenAI 兼容模式）。

封装 openai SDK 对百炼 dashscope compatible-mode 的调用：
- chat()       同步调用（简单场景）
- chat_async() 异步调用（agent 主循环使用），带指数退避重试
支持原生 tool calling（tools 参数），仅使用 chat.completions 接口（合规）。
"""

import asyncio
import os
from typing import Optional

from openai import APIConnectionError, APIError, AsyncOpenAI, OpenAI

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.7-max-2026-06-08"  # 免费额度耗尽后切换；QWEN_MODEL 环境变量可覆盖
MAX_RETRIES = 3
MAX_TOKENS = 16384  # 单次生成上限（qwen3.7-plus 支持长输出；仍保留截断兜底）


def _is_retryable(e: Exception) -> bool:
    """判断异常是否值得重试。

    只重试：连接类错误（网络抖动）、429 限流、5xx 服务端错误；
    不重试：400 参数错误、401/403 鉴权错误等（重试只会白等）。
    """
    if isinstance(e, APIConnectionError):
        return True  # 网络/连接错误，可重试
    if isinstance(e, APIError):
        status = getattr(e, "status_code", None)
        if status is None:
            return True  # 无状态码的 API 错误，保守重试
        return status == 429 or status >= 500
    return True  # 未知异常（超时等），保守重试


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

    def _build_kwargs(
        self, messages: list, tools: Optional[list], temperature: float, max_tokens: int
    ) -> dict:
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
        return kwargs

    def chat(self, messages: list, tools: Optional[list] = None, temperature: float = 0.3, max_tokens: int = MAX_TOKENS):
        """同步调用（冒烟测试/调试/工具内部使用）。"""
        return self.client.chat.completions.create(
            **self._build_kwargs(messages, tools, temperature, max_tokens)
        )

    async def chat_async(
        self,
        messages: list,
        tools: Optional[list] = None,
        temperature: float = 0.3,
        max_retries: int = MAX_RETRIES,
        max_tokens: int = MAX_TOKENS,
    ):
        """异步调用（agent 主循环使用），带指数退避重试。

        网络抖动 / 限流等临时错误会自动重试（1s、2s、4s 退避）；
        重试耗尽后抛出异常，由上层策略处理。
        """
        for attempt in range(max_retries):
            try:
                return await self.async_client.chat.completions.create(
                    **self._build_kwargs(messages, tools, temperature, max_tokens)
                )
            except Exception as e:
                # 只重试可重试错误（连接/429/5xx）；400/401 等直接抛出
                if not _is_retryable(e) or attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2**attempt)  # 1s、2s、4s 指数退避
        raise RuntimeError("unreachable")  # pragma: no cover
