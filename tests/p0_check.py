"""P0 修复验证（mock，不调用真实 API）。

覆盖：
1. finish_reason=length：截断的 tool_calls 不执行，失败回传
2. 工具参数 JSON 解析失败：不静默执行，明确错误回传
3. LLM 重试分类：400 不重试 / 429、5xx、连接错误重试
4. SSE 订阅者：无订阅者时事件丢弃（防泄漏）

运行：python tests/p0_check.py
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.context import ContextManager
from agent.strategies.react import ReActStrategy


def make_tool_call(cid: str, name: str, args: str = "{}"):
    tc = SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=args))
    tc.model_dump = lambda: {
        "id": tc.id,
        "type": "function",
        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
    }
    return tc


def make_resp(content: str, tool_calls=None, finish_reason: str = "stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content, tool_calls=tool_calls),
            finish_reason=finish_reason,
        )]
    )


class FakeLLM:
    def __init__(self, responses):
        self.responses = responses

    async def chat_async(self, *a, **k):
        return self.responses.pop(0)


class FakeRegistry:
    def __init__(self):
        self.executed = []

    def schemas(self):
        return []

    def execute(self, name, args):
        self.executed.append(name)
        return {"ok": True, "output": "ok"}


class FakeAgent:
    def __init__(self, llm):
        self.llm = llm
        self.registry = FakeRegistry()
        self.system_prompt = "system"
        self.llm_calls = 0
        self.events = []
        self.context = ContextManager(max_tokens=100000)
        self.permissions = SimpleNamespace(get=lambda x: None)

    async def call_llm(self, *a, **k):
        self.llm_calls += 1
        return await self.llm.chat_async(*a, **k)

    def tool_schemas(self):
        return []

    def is_tool_allowed(self, name):
        return True

    async def finalize_commit(self, task):
        return ""

    def emit(self, event):
        self.events.append(event)


def main():
    print("=" * 50)
    print("[1] finish_reason=length：截断的 tool_calls 不执行")
    agent = FakeAgent(FakeLLM([
        make_resp("思考", [make_tool_call("c1", "write_file", '{"path": "a.py"}')], finish_reason="length"),
        make_resp("任务完成"),
    ]))
    asyncio.run(ReActStrategy().run("任务", agent))
    assert agent.registry.executed == [], f"截断的 tool_calls 不应执行，实际执行了 {agent.registry.executed}"
    errors = [e for e in agent.events if e["type"] == "error"]
    assert errors, "应 emit 截断错误事件"
    print("   ✅ 工具未执行，失败回传")

    print("=" * 50)
    print("[2] 工具参数 JSON 解析失败：不静默执行")
    agent = FakeAgent(FakeLLM([
        make_resp("思考", [make_tool_call("c1", "grep", "{broken json")]),
        make_resp("完成"),
    ]))
    asyncio.run(ReActStrategy().run("任务", agent))
    assert agent.registry.executed == [], "坏 JSON 不应执行工具"
    results = [e for e in agent.events if e["type"] == "tool_result"]
    assert results and results[0]["ok"] is False, "应有明确的失败结果回传"
    print("   ✅ 工具未执行，明确错误回传")

    print("=" * 50)
    print("[3] LLM 重试分类")
    from openai import APIConnectionError, BadRequestError, InternalServerError, RateLimitError
    from agent.llm import _is_retryable

    class FakeResponse:
        def __init__(self, status_code):
            self.request = SimpleNamespace()
            self.status_code = status_code
            self.headers = {}
            self.text = ""

        def json(self, **k):
            return {}

    assert not _is_retryable(BadRequestError("400", response=FakeResponse(400), body=None)), "400 不应重试"
    assert _is_retryable(RateLimitError("429", response=FakeResponse(429), body=None)), "429 应重试"
    assert _is_retryable(InternalServerError("500", response=FakeResponse(500), body=None)), "5xx 应重试"
    assert _is_retryable(APIConnectionError(request=None)), "连接错误应重试"
    print("   ✅ 400 不重试 / 429、5xx、连接错误重试")

    print("=" * 50)
    print("[4] SSE 订阅者：无订阅者丢弃事件（防泄漏）")
    from server.agent_runner import SessionRunner
    runner = SessionRunner(1, lambda: None, ".")
    runner.emit({"type": "thinking", "content": "x"})
    assert runner.events.qsize() == 0, "无订阅者应丢弃"
    runner.subscribe()
    runner.emit({"type": "thinking", "content": "y"})
    assert runner.events.qsize() == 1, "有订阅者应入队"
    runner.unsubscribe()
    runner.emit({"type": "thinking", "content": "z"})
    assert runner.events.qsize() == 1, "断开后应丢弃"
    print("   ✅ 无订阅者丢弃 / 有订阅者入队 / 断开后丢弃")

    print("=" * 50)
    print("✅ P0-2~5 全部验证通过（未调用真实 API）")


if __name__ == "__main__":
    main()
