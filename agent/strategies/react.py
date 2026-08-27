"""ReAct 策略：标准 tool-calling 循环（思考 → 调用 → 观察 → … → 最终回复）。

循环流程：
1. 把 messages + 工具 schema 发给 LLM
2. 模型返回 tool_calls → 逐个本地执行 → 结果回填为 tool 消息 → 回到 1
3. 模型返回无 tool_calls 的回复 → 即任务最终回复 → 结束
4. 兜底：迭代次数达到上限强制结束（防止模型陷入死循环）

这是最通用的基础策略；PlanExecute / Reflect 在其上做目标与质量增强。
"""

import json

from ..events import DONE, ERROR, MESSAGE, THINKING, TOOL_CALL, TOOL_RESULT, make_event
from .base import AgentStrategy

DEFAULT_MAX_ITERATIONS = 20


class ReActStrategy(AgentStrategy):
    name = "react"
    description = "标准 ReAct 循环：思考 → 调用工具 → 观察结果 → 直到完成任务"

    def __init__(self, max_iterations: int = DEFAULT_MAX_ITERATIONS):
        self.max_iterations = max_iterations

    async def run(
        self,
        task: str,
        agent: "Agent",
        extra_context: str | None = None,
        report_final: bool = True,
    ) -> str:
        """执行任务，返回最终回复文本。

        extra_context: 子任务模式下的任务背景（前序子任务结果摘要），注入 user 消息
        report_final:  False 时（作为子任务内核被顶层策略调用）不发送 MESSAGE/DONE
                      事件，由顶层策略统一汇报，避免事件流语义混乱。
        """
        user_content = task
        if extra_context:
            user_content = (
                f"【任务】{task}\n\n"
                f"【任务背景：前序子任务已完成的结果摘要】\n{extra_context}"
            )
        messages: list = [
            {"role": "system", "content": agent.system_prompt},
            {"role": "user", "content": user_content},
        ]
        iterations = 0

        while iterations < self.max_iterations:
            iterations += 1
            resp = await agent.call_llm(
                messages, tools=agent.registry.schemas()
            )
            msg = resp.choices[0].message

            # 模型先给出过程说明（思考/计划），转发给前端展示
            if msg.content:
                agent.emit(make_event(THINKING, content=msg.content))

            # 有工具调用 → 执行并回填，进入下一轮
            if msg.tool_calls:
                assistant_msg = {
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                }
                messages.append(assistant_msg)
                for tc in msg.tool_calls:
                    agent.emit(
                        make_event(
                            TOOL_CALL,
                            id=tc.id,
                            name=tc.function.name,
                            args=tc.function.arguments,
                        )
                    )
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                        agent.emit(make_event(ERROR, content=f"工具参数 JSON 解析失败：{tc.function.arguments}"))
                    result = agent.registry.execute(tc.function.name, args)
                    agent.emit(
                        make_event(
                            TOOL_RESULT,
                            id=tc.id,
                            name=tc.function.name,
                            ok=result.get("ok", False),
                            output=result.get("output", ""),
                        )
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                continue

            # 无工具调用 → 这是最终回复
            final = msg.content or "(模型未返回内容)"
            if report_final:
                agent.emit(make_event(MESSAGE, content=final))
                agent.emit(make_event(DONE, iterations=iterations))
            return final

        agent.emit(make_event(ERROR, content=f"达到最大迭代次数（{self.max_iterations}），任务中止"))
        if report_final:
            agent.emit(make_event(DONE, iterations=iterations))
        return "任务未完成：达到最大迭代次数，已强制停止。请考虑把任务拆小后再试。"
