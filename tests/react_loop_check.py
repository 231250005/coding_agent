"""验证 ReAct 评审去重 / 测试轮次控制（mock LLM，不调用真实 API）。

评审规则（按内容去重，不按次数上限）：
- code_review(path=X)：X 内容自上次评审后未变化 → 阻断；每次写入/修改后允许评审一次
- code_review(无 path)：工作区改动集合未变化 → 阻断
- run_tests：每任务最多 2 轮（轮次硬上限，不变）

运行：python tests/react_loop_check.py
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.strategies.react import ReActStrategy

# 临时工作区（评审去重需要读取真实文件内容）
_TMP = tempfile.mkdtemp(prefix="react_check_")
os.environ["WORKSPACE_DIR"] = _TMP


def write(rel: str, content: str) -> None:
    p = Path(_TMP, rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


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
    """write_file 真实落盘到临时工作区，评审去重才能感知内容变化。"""

    def __init__(self):
        self.executed = []

    def schemas(self):
        return []

    def execute(self, name, args):
        self.executed.append(name)
        if name == "write_file":
            write(str(args["path"]), str(args["content"]))
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

    async def finalize_commit(self, task):
        return ""  # mock：不触发提交

    def emit(self, event):
        self.events.append(event)


from agent.context import ContextManager  # noqa: E402

FakeAgent.context = ContextManager(max_tokens=100000)


async def run_scenario(responses, max_test=2):
    agent = FakeAgent(FakeLLM(responses))
    strategy = ReActStrategy(max_test_rounds=max_test)
    result = await strategy.run("测试任务", agent)
    return agent, strategy, result


def count(agent, name) -> int:
    return agent.registry.executed.count(name)


def blocked_for(agent, keyword: str) -> list[str]:
    return [
        e.get("output", "")
        for e in agent.events
        if e["type"] == "tool_result" and keyword in str(e.get("output", ""))
    ]


async def main():
    write("a.py", "print(1)\n")

    print("=" * 50)
    print("[1] 评审按内容去重：同一文件同一内容不重复评审；修改后放行；不同文件互不影响")
    agent, strategy, result = await run_scenario([
        make_resp("评审1", [make_tool_call("c1", "code_review", '{"path":"a.py"}')]),
        make_resp("评审2", [make_tool_call("c2", "code_review", '{"path":"a.py"}')]),       # 内容未变 → 阻断
        make_resp("改a", [make_tool_call("w1", "write_file", '{"path":"a.py","content":"print(2)\\n"}')]),
        make_resp("评审3", [make_tool_call("c3", "code_review", '{"path":"a.py"}')]),       # 内容已变 → 放行
        make_resp("评审4", [make_tool_call("c4", "code_review", '{"path":"a.py"}')]),       # 内容未变 → 阻断
        make_resp("写b", [make_tool_call("w2", "write_file", '{"path":"b.py","content":"print(3)\\n"}')]),
        make_resp("评审b", [make_tool_call("c5", "code_review", '{"path":"b.py"}')]),       # 不同文件 → 放行
        make_resp("完成"),
    ])
    assert count(agent, "code_review") == 3, f"应执行 3 次评审，实际 {count(agent, 'code_review')}"
    assert len(blocked_for(agent, "无需重复评审")) == 2, "同内容重复评审应被阻断 2 次"
    assert result == "完成", "循环应正常结束"
    print(f"   执行序列: {agent.registry.executed}")
    print(f"   阻断提示: {blocked_for(agent, '无需重复评审')[0][:50]}")
    print("   ✅ 通过")

    print("=" * 50)
    print("[2] run_tests 轮次控制：3 次请求 → 应执行 2 次，第 3 次阻断（不变）")
    agent, strategy, result = await run_scenario([
        make_resp("测试1", [make_tool_call("t1", "run_tests", '{"path":"test_a.py"}')]),
        make_resp("测试2", [make_tool_call("t2", "run_tests", '{"path":"test_a.py"}')]),
        make_resp("测试3", [make_tool_call("t3", "run_tests", '{"path":"test_a.py"}')]),
        make_resp("完成"),
    ])
    assert count(agent, "run_tests") == 2, "测试应只执行 2 次"
    assert len(blocked_for(agent, "上限")) == 1, "第 3 次应被阻断"
    print(f"   执行序列: {agent.registry.executed}")
    print("   ✅ 通过")

    print("=" * 50)
    print("[3] 无 path 评审：工作区改动集合未变化 → 阻断；有新增改动 → 放行")
    agent, strategy, result = await run_scenario([
        make_resp("评审1", [make_tool_call("c1", "code_review", "{}")]),
        make_resp("评审2", [make_tool_call("c2", "code_review", "{}")]),          # 无改动 → 阻断
        make_resp("写c", [make_tool_call("w1", "write_file", '{"path":"c.py","content":"print(4)\\n"}')]),
        make_resp("评审3", [make_tool_call("c3", "code_review", "{}")]),          # 有改动 → 放行
        make_resp("评审4", [make_tool_call("c4", "code_review", "{}")]),          # 无改动 → 阻断
        make_resp("结束"),
    ])
    assert count(agent, "code_review") == 2, f"应执行 2 次评审，实际 {count(agent, 'code_review')}"
    assert len(blocked_for(agent, "无需重复评审")) == 2, "无改动重复评审应被阻断 2 次"
    print(f"   执行序列: {agent.registry.executed}")
    print("   ✅ 通过")

    print("=" * 50)
    print("✅ 评审去重与轮次控制全部验证通过（未调用真实 API）")


if __name__ == "__main__":
    asyncio.run(main())
