"""Agent 事件模型：CLI 打印与 WebSocket 推送共用同一套事件结构。

事件类型：
- thinking    模型的过程说明（调用工具前的思考/计划）
- tool_call   开始调用工具（name/args）
- tool_result 工具执行结果（ok/output）
- message     模型的最终回复（任务完成）
- error       错误信息
- done        整个任务结束（含迭代次数、LLM 调用次数统计）
"""

from typing import Any, Callable, Dict

# 事件类型常量
THINKING = "thinking"
TOOL_CALL = "tool_call"
TOOL_RESULT = "tool_result"
MESSAGE = "message"
ERROR = "error"
DONE = "done"

# 事件回调：接收一个事件字典
EventCallback = Callable[[Dict[str, Any]], None]


def make_event(type_: str, **fields: Any) -> dict:
    """构造统一格式的事件字典。"""
    return {"type": type_, **fields}
