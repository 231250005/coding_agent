"""运行日志验证：Agent 运行事件按日期写入 log/ 文件夹（mock LLM，不调用真实 API）。

验证：
1. 每个任务一个日志块（任务内容 / 元信息 / 逐步事件 / 结束标记）
2. 工具调用与结果、最终回复、结束统计都出现在日志中
3. 日志文件名按日期（YYYY-MM-DD.log）
4. 关闭开关 AGENT_LOG=0 时不写日志

运行：python tests/logging_check.py
"""

import asyncio
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 独立日志目录与工作区（不污染真实 log/ 与仓库）
_TMP = Path(tempfile.mkdtemp(prefix="logging_check_"))
_WS = _TMP / "workspace"
_WS.mkdir()
_LOG_DIR = _TMP / "log"
os.environ["WORKSPACE_DIR"] = str(_WS)
os.environ["AGENT_LOG_DIR"] = str(_LOG_DIR)

from agent.agent import Agent  # noqa: E402
from agent.permissions import PermissionLevel  # noqa: E402


def make_tool_call(cid: str, name: str, args: str):
    tc = SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=args))
    tc.model_dump = lambda: {
        "id": tc.id,
        "type": "function",
        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
    }
    return tc


def make_resp(content: str, tool_calls=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content, tool_calls=tool_calls),
            finish_reason="stop",
        )],
        usage=None,
    )


class FakeLLM:
    def __init__(self, responses):
        self.responses = responses

    async def chat_async(self, *a, **k):
        return self.responses.pop(0)


def check(name: str, cond: bool, detail: str = ""):
    mark = "✅" if cond else "❌"
    print(f"   {mark} {name}" + (f" | {detail}" if detail else ""))
    if not cond:
        raise AssertionError(f"检查失败：{name}")


def today_log() -> Path:
    return _LOG_DIR / f"{datetime.now():%Y-%m-%d}.log"


async def main():
    # ---------- 场景 1：完整事件流写入日志 ----------
    print("=" * 50)
    print("[1] 任务完整事件流写入按日期的日志文件")
    llm = FakeLLM([
        make_resp("先创建文件", [make_tool_call("c1", "write_file",
                    '{"path": "hello.py", "content": "print(\'hi\')\\n"}')]),
        make_resp("完成"),
    ])
    # L2：避免 L3 自动 git 提交（测试工作区非仓库也会跳过，这里显式用 L2 更稳）
    agent = Agent(llm=llm, permission_level=PermissionLevel.L2, log_meta={"会话ID": 99})
    result = await agent.run("写一个 hello.py")
    check("任务返回最终回复", result == "完成", result)

    log_file = today_log()
    check("日志文件按日期生成", log_file.is_file(), log_file.name)
    content = log_file.read_text(encoding="utf-8")
    check("包含任务内容", "任务开始：写一个 hello.py" in content)
    check("包含元信息（会话/权限/工作区）",
          "会话ID=99" in content and "权限=L2" in content and "历史轮数=0" not in content)
    check("包含思考过程", "🤔 先创建文件" in content)
    check("包含工具调用", "调用工具 [write_file]" in content and "hello.py" in content)
    check("包含工具结果", "📦 结果 ✅" in content)
    check("包含最终回复", "💬 完成" in content)
    check("包含任务结束统计", "任务结束" in content and "LLM 调用 2 次" in content)
    check("临时文件已写入工作区", (_WS / "hello.py").is_file())
    print("   ✅ 通过")

    # ---------- 场景 2：多任务追加同一日志文件，块与块分隔 ----------
    print("=" * 50)
    print("[2] 多任务追加同一日志文件（每次多轮对话一个块）")
    agent2 = Agent(llm=FakeLLM([make_resp("完成2")]), permission_level=PermissionLevel.L3)
    await agent2.run("第二个任务")
    content = log_file.read_text(encoding="utf-8")
    check("第二个任务块已追加", content.count("任务开始：") == 2, f"块数={content.count('任务开始：')}")
    check("两块内容都在", "任务开始：写一个 hello.py" in content and "任务开始：第二个任务" in content)
    print("   ✅ 通过")

    # ---------- 场景 3：AGENT_LOG=0 关闭 ----------
    print("=" * 50)
    print("[3] AGENT_LOG=0 时关闭日志")
    os.environ["AGENT_LOG"] = "0"
    agent3 = Agent(llm=FakeLLM([make_resp("完成3")]), permission_level=PermissionLevel.L2)
    check("logger 为 None", agent3.logger is None)
    await agent3.run("关闭日志的任务")
    content = log_file.read_text(encoding="utf-8")
    check("未写入任何日志", "任务开始：关闭日志的任务" not in content)
    os.environ.pop("AGENT_LOG", None)
    print("   ✅ 通过")

    shutil.rmtree(_TMP, ignore_errors=True)
    print("=" * 50)
    print("✅ 运行日志验证全部通过")


if __name__ == "__main__":
    asyncio.run(main())
