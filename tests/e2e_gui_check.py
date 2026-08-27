"""端到端验证：GUI 程序（俄罗斯方块）。

任务：让 agent 用 Python tkinter 写一个俄罗斯方块游戏并验证。
验证成功时屏幕上会真的弹出游戏窗口（运行几秒后被超时机制关闭，属正常）。

工作区指向系统临时目录，不会污染项目。

运行：python tests/e2e_gui_check.py
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
_WS = tempfile.mkdtemp(prefix="e2e_gui_ws_")
os.environ["WORKSPACE_DIR"] = _WS

from agent.agent import Agent


def pretty_print(event: dict) -> None:
    t = event["type"]
    if t == "thinking":
        print(f"\n🤔 {event['content'][:150]}")
    elif t == "tool_call":
        print(f"\n🔧 调用工具 [{event['name']}] 参数: {event['args'][:150]}")
    elif t == "tool_result":
        mark = "✅" if event.get("ok") else "❌"
        print(f"📦 结果 {mark}: {str(event.get('output', ''))[:150]}")
    elif t == "message":
        print(f"\n💬 {event['content'][:300]}")
    elif t == "error":
        print(f"\n⚠️ 错误: {event['content']}")
    elif t == "done":
        print(f"\n🏁 完成（{event.get('iterations', '?')} 轮）")


async def main() -> None:
    agent = Agent(on_event=pretty_print)
    task = (
        "用 Python 的 tkinter 库写一个俄罗斯方块小游戏，保存为 tetris.py，"
        "并用 run_command 验证它能正常弹出窗口"
    )
    print(f"任务: {task}\n" + "=" * 50)
    result = await agent.run(task)
    print("=" * 50)
    print("最终结果:", result[:300])

    game = Path(_WS) / "tetris.py"
    if game.is_file():
        print(f"\n✅ 验证：tetris.py 已生成（{game.stat().st_size} 字节）")
        print(f"   用户可自行运行：python {game.resolve()}")
    else:
        print(f"\n❌ 验证失败：tetris.py 未生成（工作区内容：{os.listdir(_WS)}）")

    shutil.rmtree(_WS, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
