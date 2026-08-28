"""上下文管理验证（mock，不调用真实 API）。

覆盖：
1. token 估算器（中/英/混合）
2. 第一级裁剪：旧 tool 结果替换为占位符，保留 tool_call_id，system 与最近消息不动
3. 第二级摘要：mock LLM 返回摘要 → 消息数减少、摘要消息插入
4. 未超限时不动

运行：python tests/context_check.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.context import ContextManager, estimate_tokens


def check(name: str, cond: bool, detail: str = ""):
    mark = "✅" if cond else "❌"
    print(f"   {mark} {name}" + (f" | {detail}" if detail else ""))
    if not cond:
        raise AssertionError(f"检查失败：{name}")


def make_msgs(n_tool: int) -> list[dict]:
    """构造 system + user + n_tool 组 (assistant+tool) 的消息。"""
    msgs = [
        {"role": "system", "content": "你是 CodeAgent。" * 5},
        {"role": "user", "content": "实现一个待办事项工具"},
    ]
    for i in range(n_tool):
        msgs.append({"role": "assistant", "content": f"第 {i + 1} 轮思考", "tool_calls": [
            {"id": f"call_{i}", "type": "function",
             "function": {"name": "run_command", "arguments": '{"command": "python x.py"}'}}
        ]})
        msgs.append({"role": "tool", "tool_call_id": f"call_{i}", "content": "x" * 500})  # 每条 500 字符
    return msgs


async def main():
    print("=" * 50)
    print("[1] token 估算器")
    zh = estimate_tokens("实现一个俄罗斯方块小游戏并添加测试")
    en = estimate_tokens("implement tetris and add tests")
    mixed = estimate_tokens("实现 tetris 游戏，10 levels，添加 5 个 tests")
    print(f"   中文 {zh} | 英文 {en} | 混合 {mixed}")
    check("中文估算合理（>15）", zh > 15, f"zh={zh}")
    check("英文估算合理（4字符≈1token）", en >= 5, f"en={en}（31 字符）")

    print("=" * 50)
    print("[2] 第一级裁剪：旧 tool 结果被替换，system 与最近消息不动")
    ctx = ContextManager(max_tokens=800, keep_recent=4)
    msgs = make_msgs(6)
    total = ctx.count_tokens(msgs)
    new_msgs, stats = await ctx.ensure_within_budget(msgs, call_llm=None)
    check("触发压缩", stats.get("truncated", 0) > 0, f"truncated={stats.get('truncated')}")
    check("释放了 token", stats.get("released", 0) > 0, f"released={stats.get('released')}")
    check("system 未动", new_msgs[0]["content"] == msgs[0]["content"])
    check("最近 keep_recent 条未动", new_msgs[-4:] == msgs[-4:])
    tool_ids = [m.get("tool_call_id") for m in new_msgs if m.get("role") == "tool"]
    check("tool_call_id 全部保留", all(tid is not None for tid in tool_ids))
    placeholders = [m for m in new_msgs if m.get("role") == "tool" and "已归档" in m["content"]]
    check("旧结果变为占位符", len(placeholders) > 0, f"{len(placeholders)} 条占位")

    print("=" * 50)
    print("[3] 第二级摘要：mock LLM 压缩最早对话")
    calls = []

    async def fake_call_llm(*a, **k):
        calls.append(a)
        class _Msg:
            content = "用户要求实现待办事项工具；已完成 todo.py；测试通过；准备提交。"
        class _Choice:
            message = _Msg()
        class _Resp:
            choices = [_Choice()]
        return _Resp()

    ctx2 = ContextManager(max_tokens=200, keep_recent=4)
    msgs2 = make_msgs(6)  # 6*500 字符 tool 结果，裁剪后仍超 200
    new2, stats2 = await ctx2.ensure_within_budget(msgs2, call_llm=fake_call_llm)
    check("触发摘要", stats2.get("summarized", 0) > 0, f"summarized={stats2.get('summarized')}")
    check("出现历史摘要消息", any("[历史摘要]" in m.get("content", "") for m in new2))
    check("消息数减少", len(new2) < len(msgs2), f"{len(msgs2)} → {len(new2)}")
    check("摘要调用了 LLM", len(calls) == 1)

    print("=" * 50)
    print("[4] 未超限不动")
    ctx3 = ContextManager(max_tokens=100000)
    msgs3 = make_msgs(3)
    new3, stats3 = await ctx3.ensure_within_budget(msgs3, call_llm=fake_call_llm)
    check("无压缩发生", not stats3 and new3 == msgs3)

    print("=" * 50)
    print("✅ 上下文管理验证全部通过")


if __name__ == "__main__":
    asyncio.run(main())
