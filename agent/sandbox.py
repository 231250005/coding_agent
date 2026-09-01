"""安全层：工作区隔离、路径防护、输出截断。

所有工具都限定在"工作区"（WORKSPACE_DIR，默认项目根目录）内操作，
防止模型生成的路径逃逸到工作区之外（如 ../../Windows/...）。
"""

import contextvars
import os
from pathlib import Path

# 输出截断上限（字符数）：防止工具输出撑爆模型上下文
MAX_OUTPUT_CHARS = 8000
# 命令默认超时（秒）
DEFAULT_TIMEOUT = 60
# 单文件读取上限（行数）
MAX_READ_LINES = 500

# 环境变量默认值：未配置时使用项目根目录
DEFAULT_WORKSPACE = str(Path.cwd())

# 当前任务工作区（asyncio 任务隔离：Web 场景每个会话的任务互不干扰）
_workspace_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("agent_workspace", default=None)


def set_workspace(workspace: str | None) -> None:
    """设置当前 asyncio 任务的工作区（由 Agent.run 在任务开始时调用）。"""
    _workspace_var.set(workspace)


def get_workspace() -> Path:
    """获取当前任务的工作区（优先级：任务工作区 > WORKSPACE_DIR 环境变量 > 项目根）。"""
    ws = _workspace_var.get()
    if ws:
        return Path(ws).resolve()
    return Path(os.environ.get("WORKSPACE_DIR") or DEFAULT_WORKSPACE).resolve()


def safe_join(rel_path: str) -> Path:
    """把工具传入的相对路径解析到工作区内，防止路径穿越（../ 逃逸）。

    工具只能传相对工作区的路径；越界直接抛异常，由工具层转成失败结果回给模型。
    """
    if not rel_path or not rel_path.strip():
        raise ValueError("路径不能为空")
    workspace = get_workspace()
    target = (workspace / rel_path.strip()).resolve()
    if not target.is_relative_to(workspace):
        raise ValueError(f"路径越界（不允许访问工作区之外）：{rel_path}")
    return target


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """截断过长的文本，保留头部并提示截断原因（文件内容类适用）。"""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… (输出过长已截断，仅显示前 {limit} 字符)"


def truncate_tail(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """截断过长的文本，**保留末尾**并提示截断原因（命令输出类适用）。

    命令的错误信息（Traceback / FAILED / fatal）在输出末尾——
    保留尾部才能让模型"看到错误"并自我纠错。
    """
    if len(text) <= limit:
        return text
    return f"… (输出过长已截断开头，仅显示末尾 {limit} 字符)\n" + text[-limit:]


def truncate_with_meta(
    text: str, limit: int = MAX_OUTPUT_CHARS, tail: bool = False
) -> tuple[str, bool, int]:
    """截断并返回元数据：(截断后文本, 是否发生截断, 原始总字符数)。

    供工具返回结构化截断信息（truncated / total_chars），
    模型据此知道"输出被截断了、总量多少"，主动补齐遗漏部分。
    """
    total = len(text)
    if total <= limit:
        return text, False, total
    if tail:
        return truncate_tail(text, limit), True, total
    return truncate(text, limit), True, total
