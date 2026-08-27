"""端到端验证：Plan-and-Execute 两级推理框架。

任务：实现待办事项管理器 + 测试验证 —— 需要规划拆分多个子任务
（实现功能 → 写测试 → 运行测试 → 收尾评审），验证：
1. plan 事件出现（规划拆分 ≥2 个子任务）
2. 子任务逐个执行（subtask_start/done 事件）
3. 收尾评审调用（review 事件）

工作区指向系统临时目录，不会污染项目。

运行：python tests/e2e_plan_check.py
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
_WS = tempfile.mkdtemp(prefix="e2e_plan_ws_")
os.environ["WORKSPACE_DIR"] = _WS

from agent.agent import Agent

# 统计各类事件数量，验证框架结构
event_counts: dict[str, int] = {}
n_subtasks = 0


def pretty_print(event: dict) -> None:
    global n_subtasks
    t = event["type"]
    event_counts[t] = event_counts.get(t, 0) + 1
    if t == "plan":
        steps = event.get("steps", [])
        n_subtasks = len(steps)
        print(f"\n📋 计划: {event.get('goal', '')[:60]}（{len(steps)} 个子任务）")
        for s in steps:
            print(f"   {s.get('id')}. [{s.get('mode')}] {s.get('task', '')[:70]}")
    elif t == "subtask_start":
        print(f"\n📌 子任务 {event.get('index')}/{event.get('total')} [{event.get('mode')}]: {event.get('task', '')[:70]}")
    elif t == "subtask_done":
        print(f"✅ 子任务完成: {event.get('summary', '')[:120]}")
    elif t == "review":
        print(f"\n🔍 收尾评审: {str(event.get('content', ''))[:200]}")
    elif t == "replan":
        print(f"\n🔄 计划调整")
    elif t == "thinking":
        print(f"🤔 {event['content'][:80]}")
    elif t == "tool_call":
        print(f"🔧 [{event['name']}]")
    elif t == "tool_result":
        print(f"📦 {'✅' if event.get('ok') else '❌'} {str(event.get('output', ''))[:100]}")
    elif t == "message":
        print(f"\n💬 {event['content'][:200]}")
    elif t == "done":
        print(f"\n🏁 完成（{event.get('iterations')} 个子任务摘要）")


async def main() -> None:
    agent = Agent(on_event=pretty_print)
    task = (
        "用 Python 实现一个命令行待办事项管理器 todo.py，"
        "支持 add（添加事项）、remove（移除事项）、list（列出全部）三个命令，"
        "并编写单元测试验证三个命令都正常工作，确保测试全部通过"
    )
    print(f"任务: {task}\n" + "=" * 60)
    result = await agent.run(task)
    print("=" * 60)

    # ---- 结构验证 ----
    print("\n=== 框架结构验证 ===")
    assert event_counts.get("plan", 0) >= 1, "缺少 plan 事件（未执行规划）"
    assert n_subtasks >= 2, f"子任务数应 ≥2，实际 {n_subtasks}"
    assert event_counts.get("subtask_start", 0) >= 2, "子任务未逐个执行"
    assert event_counts.get("tool_call", 0) >= 1, "子任务内未调用工具"
    assert event_counts.get("review", 0) >= 1, "缺少收尾评审"
    print(f"✅ plan 事件 ×{event_counts['plan']}（子任务 {n_subtasks} 个）")
    print(f"✅ subtask_start ×{event_counts.get('subtask_start', 0)} / subtask_done ×{event_counts.get('subtask_done', 0)}")
    print(f"✅ tool_call ×{event_counts.get('tool_call', 0)}（子任务内真实工具调用）")
    print(f"✅ review ×{event_counts.get('review', 0)}（收尾评审）")
    print(f"✅ replan ×{event_counts.get('replan', 0)}")

    todo = Path(_WS) / "todo.py"
    if todo.is_file():
        print(f"✅ 产物验证：todo.py 已生成（{todo.stat().st_size} 字节）")
    else:
        print(f"❌ 产物验证失败：todo.py 未生成（工作区：{os.listdir(_WS)}）")

    shutil.rmtree(_WS, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
