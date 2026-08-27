"""CodeAgent 命令行入口（调试、演示用）。

运行：python cli.py
输入任务后 agent 将自主调用工具完成；输入 exit 退出。
"""

import asyncio

from agent.agent import Agent
from agent.strategies import list_strategies


def pretty_print(event: dict) -> None:
    """把事件流渲染成可读的过程日志。"""
    t = event["type"]
    if t == "thinking":
        print(f"\n🤔 {event['content']}")
    elif t == "tool_call":
        print(f"\n🔧 调用工具 [{event['name']}] 参数: {event['args']}")
    elif t == "tool_result":
        mark = "✅" if event.get("ok") else "❌"
        output = event.get("output", "")
        print(f"📦 结果 {mark}: {output[:400]}{'...' if len(output) > 400 else ''}")
    elif t == "message":
        print(f"\n💬 {event['content']}")
    elif t == "plan":
        steps = event.get("steps", [])
        print(f"\n📋 计划: {event.get('goal', '')}（{len(steps)} 个子任务）")
        for s in steps:
            print(f"   {s.get('id', '?')}. [{s.get('mode', '?')}] {s.get('task', '')}")
    elif t == "subtask_start":
        idx = event.get("index", "?")
        total = event.get("total", "?")
        print(f"\n📌 子任务 {idx}/{total} [{event.get('mode', '?')}]: {event.get('task', '')}")
    elif t == "subtask_done":
        print(f"✅ 子任务 {event.get('index', '?')} 完成: {event.get('summary', '')[:150]}")
    elif t == "replan":
        print(f"\n🔄 计划调整: {event.get('reason', '')}")
    elif t == "review":
        mark = "✅" if event.get("ok") else "⚠️"
        print(f"\n🔍 收尾评审 {mark}: {str(event.get('content', ''))[:300]}")
    elif t == "error":
        print(f"\n⚠️ 错误: {event['content']}")
    elif t == "done":
        print(f"\n🏁 任务结束（共 {event.get('iterations', '?')} 轮循环）")


async def main() -> None:
    print(f"CodeAgent CLI（策略: {', '.join(list_strategies())}）")
    print("输入编程任务，agent 将自主完成；输入 exit 退出。")
    print("-" * 50)

    agent = Agent(on_event=pretty_print)
    while True:
        try:
            task = input("\n>>> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not task:
            continue
        if task.lower() in ("exit", "quit"):
            break
        try:
            await agent.run(task)
        except KeyboardInterrupt:
            print("\n⚠️ 任务已中断")
        except Exception as e:
            print(f"\n⚠️ 运行异常：{type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
