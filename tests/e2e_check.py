"""端到端验证：agent 能否自主完成一个真实编程任务。

任务：写一个猜数字小游戏并运行验证 —— 需要 agent 自主完成
write_file（写代码）→ run_command（运行验证）→ 可能的 read_file/修复 闭环。

工作区指向系统临时目录，不会污染项目。

运行：python tests/e2e_check.py
"""

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

# 确保能导入项目根目录下的 agent 包（无论从哪运行）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 测试隔离：临时工作区
_WS = tempfile.mkdtemp(prefix="e2e_ws_")
os.environ["WORKSPACE_DIR"] = _WS

from agent.agent import Agent


def pretty_print(event: dict) -> None:
    t = event["type"]
    if t == "thinking":
        print(f"\n🤔 {event['content']}")
    elif t == "tool_call":
        print(f"\n🔧 调用工具 [{event['name']}] 参数: {event['args'][:200]}")
    elif t == "tool_result":
        mark = "✅" if event.get("ok") else "❌"
        print(f"📦 结果 {mark}: {str(event.get('output', ''))[:200]}")
    elif t == "message":
        print(f"\n💬 {event['content']}")
    elif t == "error":
        print(f"\n⚠️ 错误: {event['content']}")
    elif t == "done":
        print(f"\n🏁 完成（{event.get('iterations', '?')} 轮）")


async def main() -> None:
    agent = Agent(on_event=pretty_print)
    task = "用 Python 写一个猜数字小游戏，保存为 game.py，并用 run_command 运行验证它能正常运行"
    print(f"任务: {task}\n" + "=" * 50)
    result = await agent.run(task)
    print("=" * 50)
    print("最终结果:", result)

    game = Path(_WS) / "game.py"
    if game.is_file():
        print(f"\n✅ 验证：game.py 已生成（{game.stat().st_size} 字节）")
    else:
        print(f"\n❌ 验证失败：game.py 未生成（工作区内容：{os.listdir(_WS)}）")

    shutil.rmtree(_WS, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
