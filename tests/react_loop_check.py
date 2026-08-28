"""验证 ReAct 评审/测试轮次硬控制（mock LLM，不调用真实 API）。

场景：模型连续请求 3 次 code_review / run_tests——
期望：前 2 次正常执行，第 3 次被硬阻断并引导继续，循环正常结束。

运行：python tests/react_loop_check.py
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.strategies.react import ReActStrategy


def make_tool_call(cid: str, name: str, args: str = "{}"):
    tc = SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=args))
    # 模拟 openai SDK 对象的 model_dump 方法
    tc.model_dump = lambda: {
        "id": tc.id,
        "type": "function",
        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
    }
    return tc


def make_resp(content: str, tool_calls=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))]
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

    async def call_llm(self, *a, **k):
        self.llm_calls += 1
        return await self.llm.chat_async(*a, **k)

    def tool_schemas(self):
        return []

    def is_tool_allowed(self, name):
        return True

    def emit(self, event):
        self.events.append(event)


from agent.context import ContextManager  # noqa: E402

FakeAgent.context = ContextManager(max_tokens=100000)


async def run_scenario(responses, max_review=2, max_test=2):
    agent = FakeAgent(FakeLLM(responses))
    strategy = ReActStrategy(max_review_rounds=max_review, max_test_rounds=max_test)
    result = await strategy.run("测试任务", agent)
    return agent, strategy, result


async def main():
    print("=" * 50)
    print("[1] code_review 轮次控制：3 次请求 → 应执行 2 次，第 3 次阻断")
    agent, strategy, result = await run_scenario([
        make_resp("评审1", [make_tool_call("c1", "code_review", '{"path":"a.py"}')]),
        make_resp("评审2", [make_tool_call("c2", "code_review", '{"path":"a.py"}')]),
        make_resp("评审3", [make_tool_call("c3", "code_review", '{"path":"a.py"}')]),
        make_resp("任务完成"),
    ])
    executed = agent.registry.executed
    blocked_msgs = [e.get("output", "") for e in agent.events if e["type"] == "tool_result" and "上限" in str(e.get("output", ""))]
    print(f"   code_review 实际执行次数: {executed.count('code_review')}")
    print(f"   阻断提示: {blocked_msgs[0][:60] if blocked_msgs else '无'}")
    assert executed.count("code_review") == 2, "评审应只执行 2 次"
    assert blocked_msgs, "第 3 次应被阻断"
    assert result == "任务完成", "循环应正常结束"
    print("   ✅ 通过")

    print("=" * 50)
    print("[2] run_tests 轮次控制：3 次请求 → 应执行 2 次，第 3 次阻断")
    agent, strategy, result = await run_scenario([
        make_resp("测试1", [make_tool_call("t1", "run_tests", '{"path":"test_a.py"}')]),
        make_resp("测试2", [make_tool_call("t2", "run_tests", '{"path":"test_a.py"}')]),
        make_resp("测试3", [make_tool_call("t3", "run_tests", '{"path":"test_a.py"}')]),
        make_resp("完成"),
    ])
    executed = agent.registry.executed
    blocked_msgs = [e.get("output", "") for e in agent.events if e["type"] == "tool_result" and "上限" in str(e.get("output", ""))]
    print(f"   run_tests 实际执行次数: {executed.count('run_tests')}")
    assert executed.count("run_tests") == 2, "测试应只执行 2 次"
    assert blocked_msgs, "第 3 次应被阻断"
    print("   ✅ 通过")

    print("=" * 50)
    print("[3] 混合场景：评审 2 次 + 测试 2 次 + 第 3 次测试阻断")
    agent, strategy, result = await run_scenario([
        make_resp("r1", [make_tool_call("c1", "code_review", '{}')]),
        make_resp("r2", [make_tool_call("c2", "code_review", '{}')]),
        make_resp("t1", [make_tool_call("t1", "run_tests", '{}')]),
        make_resp("t2", [make_tool_call("t2", "run_tests", '{}')]),
        make_resp("t3", [make_tool_call("t3", "run_tests", '{}')]),
        make_resp("结束"),
    ])
    executed = agent.registry.executed
    print(f"   执行序列: {executed}")
    assert executed.count("code_review") == 2 and executed.count("run_tests") == 2, "各应执行 2 次"
    print("   ✅ 通过")

    print("=" * 50)
    print("✅ 轮次硬控制全部验证通过（未调用真实 API）")


if __name__ == "__main__":
    asyncio.run(main())
