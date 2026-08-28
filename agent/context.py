"""上下文管理：token 估算 + 长对话压缩（题目要求的"对话历史与上下文管理"）。

组成：
- estimate_tokens()：无依赖的 token 近似估算（CJK 1 字符≈1 token，其他 4 字符≈1 token）
- ContextManager：管理运行时 messages 列表，超限时两级压缩——
  ① 裁剪最旧的 tool 结果（零成本，保留 tool_call_id）
  ② LLM 摘要压缩最早的一段对话（保留任务主线）

保护规则：system 消息永不压缩；最近 keep_recent 条消息永不压缩。
阈值默认 100000（MAX_CONTEXT_TOKENS 环境变量可覆盖），常态不干预、长任务自动治理。
"""

import os
import re
from typing import Awaitable, Callable, Optional

# CJK 字符（中文/日文/韩文）：1 字符 ≈ 1 token
_CJK_RE = re.compile(r"[一-鿿぀-ヿ가-힯]")
# 每条约 4 token 的消息元数据开销
_MSG_OVERHEAD = 4

_TOOL_PLACEHOLDER = "…（早期工具结果已归档，如需详情可用 read_file 重新读取）…"

SUMMARIZE_PROMPT = """请把以下对话历史压缩为一段不超过 {limit} 字的摘要。
必须保留：任务目标、已完成的关键动作、产出文件、验证结果、当前状态、剩余待办。
不要包含工具执行的细节输出。

历史消息：
{history}
"""


def estimate_tokens(text: str) -> int:
    """无依赖的 token 近似估算（与真实 usage 偏差在可接受范围）。"""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    other = len(text) - cjk
    return cjk + other // 4 + 1


def _format_history(messages: list[dict], per_line: int = 200) -> str:
    """把消息列表格式化成摘要输入（tool 消息只显示角色，不显示大段结果）。"""
    lines = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content") or ""
        if role == "tool":
            lines.append(f"[tool] 工具结果（已省略）")
        else:
            lines.append(f"[{role}] {content[:per_line]}")
    return "\n".join(lines)


class ContextManager:
    def __init__(
        self,
        max_tokens: Optional[int] = None,
        keep_recent: int = 10,
        max_summary_chars: int = 800,
    ):
        # 阈值默认 100000（十万），可用 MAX_CONTEXT_TOKENS 环境变量覆盖
        self.max_tokens = max_tokens or int(os.environ.get("MAX_CONTEXT_TOKENS", "100000"))
        self.keep_recent = keep_recent
        self.max_summary_chars = max_summary_chars

    # ---------- 统计 ----------

    def count_tokens(self, messages: list[dict]) -> int:
        total = 0
        for m in messages:
            total += estimate_tokens(m.get("content") or "")
            # 工具调用的参数也算
            for tc in m.get("tool_calls") or []:
                total += estimate_tokens(tc.get("function", {}).get("arguments", ""))
            total += _MSG_OVERHEAD
        return total

    # ---------- 核心入口 ----------

    async def ensure_within_budget(
        self,
        messages: list[dict],
        call_llm: Optional[Callable[..., Awaitable]] = None,
    ) -> tuple[list[dict], dict]:
        """超限时压缩消息列表，返回 (新消息, 压缩统计)。

        call_llm：第二级摘要使用的 LLM 调用（传 agent.call_llm 可计入预算护栏）；
        为 None 时只做第一级裁剪。
        """
        stats: dict = {}
        total = self.count_tokens(messages)
        if total <= self.max_tokens:
            return messages, stats

        # 第一级：裁剪最旧的 tool 结果（零成本）
        messages, truncated = self._truncate_tool_results(messages)
        stats["truncated"] = truncated
        stats["released"] = total - self.count_tokens(messages)
        if self.count_tokens(messages) <= self.max_tokens or call_llm is None:
            return messages, stats

        # 第二级：LLM 摘要最早的一段对话
        messages, summarized = await self._summarize_old(messages, call_llm)
        stats["summarized"] = summarized
        stats["released"] = total - self.count_tokens(messages)
        return messages, stats

    # ---------- 第一级：裁剪 ----------

    def _truncate_tool_results(self, messages: list[dict]) -> tuple[list[dict], int]:
        """把可裁剪区域（跳过 system 与最近 keep_recent 条）中最旧的 tool 结果替换为占位符。

        保留 tool_call_id 与角色结构（模型依赖 id 对应关系）。
        """
        if len(messages) <= self.keep_recent + 1:
            return messages, 0
        cut_end = len(messages) - self.keep_recent  # 可裁剪区：索引 1 .. cut_end-1
        new = list(messages)
        count = 0
        for i in range(1, cut_end):
            if messages[i].get("role") == "tool":
                new[i] = {**messages[i], "content": _TOOL_PLACEHOLDER}
                count += 1
        return new, count

    # ---------- 第二级：摘要 ----------

    async def _summarize_old(
        self,
        messages: list[dict],
        call_llm: Callable[..., Awaitable],
    ) -> tuple[list[dict], int]:
        """把可裁剪区最早的一半消息压缩成一条 [历史摘要] 消息。"""
        if len(messages) <= self.keep_recent + 1:
            return messages, 0
        cut_end = len(messages) - self.keep_recent
        span = cut_end - 1
        if span <= 0:
            return messages, 0
        cut = max(1, span // 2)  # 压缩最早一半
        old = messages[1 : 1 + cut]

        prompt = SUMMARIZE_PROMPT.format(
            limit=self.max_summary_chars,
            history=_format_history(old),
        )
        try:
            resp = await call_llm(
                [{"role": "system", "content": "你是对话历史记录员。"},
                 {"role": "user", "content": prompt}],
                temperature=0.2,
                max_retries=1,
            )
            summary = (resp.choices[0].message.content or "").strip()[: self.max_summary_chars]
            if not summary:
                return messages, 0
        except Exception:
            return messages, 0  # 摘要失败不阻塞主流程

        summary_msg = {"role": "user", "content": f"[历史摘要] {summary}"}
        new_messages = messages[:1] + [summary_msg] + messages[1 + cut :]
        return new_messages, len(old)
