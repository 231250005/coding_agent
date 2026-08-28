"""CodeAgent 命令行入口（调试、演示用）。

运行：python cli.py
输入任务后 agent 将自主调用工具完成；输入 exit 退出。
启动时选择三级权限：
  1 = 软修改需确认（L1）  2 = 直接修改可撤销（L2）  3 = 自动 git 提交（L3）
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
        icon = "🔍" if event["name"] == "code_review" else "🔧"
        print(f"\n{icon} 调用工具 [{event['name']}] 参数: {event['args']}")
    elif t == "tool_result":
        mark = "✅" if event.get("ok") else "❌"
        output = event.get("output", "")
        print(f"📦 结果 {mark}: {output[:400]}{'...' if len(output) > 400 else ''}")
    elif t == "request_confirmation":
        print(f"\n🔔 等待确认 [{event['operation']}] {event['file_path']}")
        print("   " + str(event.get("diff", "")).replace("\n", "\n   ")[:400])
    elif t == "context_compressed":
        print(f"\n📄 上下文已压缩：释放 {event.get('released', 0)} token"
              f"（裁剪工具结果 {event.get('truncated', 0)} 条"
              f"{', 摘要历史 ' + str(event.get('summarized')) + ' 条' if event.get('summarized') else ''}）")
    elif t == "usage":
        prompt = event.get("prompt_tokens", "?")
        comp = event.get("completion_tokens", "?")
        ctx = event.get("context_tokens", "?")
        print(f"   📊 调用#{event.get('llm_calls', '?')} | 上下文 {ctx} token | 本轮 {prompt}+{comp} token")
    elif t == "message":
        print(f"\n💬 {event['content']}")
    elif t == "error":
        print(f"\n⚠️ 错误: {event['content']}")
    elif t == "done":
        print(f"\n🏁 任务结束（共 {event.get('iterations', '?')} 轮循环）")


async def cli_confirm(change) -> str:
    """L1 权限的用户确认交互。"""
    print(f"\n🔔 需要确认：{change.operation} {change.file_path}")
    print("   变更预览：")
    print("   " + change.diff_preview.replace("\n", "\n   ")[:400])
    ans = input("   确认应用？(y/N): ").strip().lower()
    return "confirmed" if ans == "y" else "rejected"


async def main() -> None:
    print(f"CodeAgent CLI（策略: {', '.join(list_strategies())}）")
    print("权限级别：1=软修改需确认 / 2=直接修改可撤销 / 3=自动git提交（默认）")
    try:
        level_input = input("选择权限级别 [1/2/3]（回车默认 3）: ").strip()
        level = int(level_input) if level_input else 3
    except (ValueError, EOFError, KeyboardInterrupt):
        level = 3
    print("-" * 50)
    print(f"已选择权限级别 L{level}。输入编程任务，agent 将自主完成；输入 exit 退出。")

    agent = Agent(on_event=pretty_print, permission_level=level, confirm_callback=cli_confirm)
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
