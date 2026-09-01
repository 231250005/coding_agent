"""运行日志：按日期记录每次任务（多轮对话）的完整事件过程。

- 每个任务一个日志块（任务内容 / 会话元信息 / 逐步事件），按日期归档：
  项目根目录 log/YYYY-MM-DD.log（跨天自动切换新文件）
- 事件与 CLI / Web 共用同一套 AgentEvent 结构（思考 / 工具调用与结果 /
  L1 确认 / 上下文压缩 / 用量 / 最终回复），挂接在 Agent.emit() 上，
  两种运行模式（CLI、Web）无需额外接线即可全覆盖
- 线程安全：Web 场景多会话并发写入，用锁串行化
- 配置：AGENT_LOG=0 关闭（默认开启）；AGENT_LOG_DIR 可改目录
- 日志写失败（目录不可写等）静默降级，不影响 agent 运行
"""

import os
import threading
from datetime import datetime
from pathlib import Path

# 默认日志目录：项目根目录下的 log/
DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "log"


def format_event(event: dict) -> str:
    """把 AgentEvent 事件格式化成可读日志行（与 CLI pretty_print 风格一致）。"""
    t = event["type"]
    if t == "thinking":
        return f"🤔 {event.get('content', '')}"
    if t == "tool_call":
        return f"🔧 调用工具 [{event.get('name')}] 参数: {event.get('args', '')}"
    if t == "tool_result":
        mark = "✅" if event.get("ok") else "❌"
        return f"📦 结果 {mark}: {event.get('output', '')}"
    if t == "request_confirmation":
        diff = str(event.get("diff", "")).replace("\n", "\n      ")
        return (
            f"🔔 等待确认 [{event.get('operation')}] {event.get('file_path')}\n"
            f"      {diff}"
        )
    if t == "context_compressed":
        summarized = f"，摘要历史 {event.get('summarized')} 条" if event.get("summarized") else ""
        return (
            f"📄 上下文已压缩：释放 {event.get('released', 0)} token"
            f"（裁剪工具结果 {event.get('truncated', 0)} 条{summarized}）"
        )
    if t == "usage":
        return (
            f"📊 调用#{event.get('llm_calls', '?')} | 上下文 {event.get('context_tokens', '?')} token"
            f" | 本轮 {event.get('prompt_tokens', '?')}+{event.get('completion_tokens', '?')} token"
        )
    if t == "message":
        return f"💬 {event.get('content', '')}"
    if t == "error":
        return f"⚠️ 错误: {event.get('content', '')}"
    if t == "done":
        return (
            f"🏁 任务结束（共 {event.get('iterations', '?')} 轮循环，"
            f"LLM 调用 {event.get('llm_calls', '?')} 次）"
        )
    return f"[{t}] {event}"


class RunLogger:
    """任务运行日志写入器（按日期归档，跨天自动切换文件）。"""

    def __init__(self, log_dir: Path | None = None):
        self.log_dir = Path(log_dir) if log_dir else Path(
            os.environ.get("AGENT_LOG_DIR") or DEFAULT_LOG_DIR
        )
        self._lock = threading.Lock()

    def begin_run(self, task: str, meta: dict | None = None) -> None:
        """任务开始：写入任务内容与元信息（会话 ID / 权限 / 工作区 / 历史轮数）。"""
        now = datetime.now()
        lines = [
            "=" * 60,
            f"[{now:%Y-%m-%d %H:%M:%S}] 任务开始：{task}",
        ]
        if meta:
            lines.append(f"[{now:%H:%M:%S}] " + " | ".join(f"{k}={v}" for k, v in meta.items()))
        lines.append("-" * 60)
        self._write("\n".join(lines) + "\n")

    def event(self, event: dict) -> None:
        """记录一条事件。"""
        self._write(f"[{datetime.now():%H:%M:%S}] {format_event(event)}\n")

    def end_run(self, note: str = "") -> None:
        """任务结束：写入结束标记。"""
        line = f"[{datetime.now():%H:%M:%S}] 任务结束" + (f"：{note}" if note else "")
        self._write(line + "\n" + "=" * 60 + "\n")

    def _write(self, text: str) -> None:
        """追加写入当日日志文件（打开-追加-关闭，崩溃不丢数据；加锁防并发交错）。"""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return  # 日志目录不可写：静默降级，不阻塞 agent
        path = self.log_dir / f"{datetime.now():%Y-%m-%d}.log"
        try:
            with self._lock:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(text)
        except OSError:
            pass  # 写日志失败不影响 agent 运行
