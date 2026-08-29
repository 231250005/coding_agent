"""ReAct 策略：规范化 tool-calling 循环（思考 → 调用 → 观察 → … → 最终回复）。

循环流程（每步规范化）：
1. 把 messages + 工具 schema 发给 LLM
2. 模型返回 tool_calls → 逐个本地执行 → 结果回填为 tool 消息 → 回到 1
3. 模型返回无 tool_calls 的回复 → 即任务最终回复 → 结束
4. 兜底：迭代次数达到上限强制结束（防止模型陷入死循环）

工具规范性由系统提示词约束（见 prompts.py）：
只调用注册表中真实存在的工具，禁止编造工具或声称完成工具集不支持的动作。
"""

import json

from ..events import CONTEXT_COMPRESSED, DONE, ERROR, MESSAGE, THINKING, TOOL_CALL, TOOL_RESULT, USAGE, make_event
from .base import AgentStrategy

DEFAULT_MAX_ITERATIONS = 20
# 评审 / 测试 轮次硬上限：防止模型陷入"评审→修改→再评审"或"测试→修改→再测试"的无限循环
MAX_REVIEW_ROUNDS = 2
MAX_TEST_ROUNDS = 2


class ReActStrategy(AgentStrategy):
    name = "react"
    description = "规范化 ReAct 循环：思考 → 调用现有工具 → 观察结果 → 直到任务完成"

    def __init__(
        self,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        max_review_rounds: int = MAX_REVIEW_ROUNDS,
        max_test_rounds: int = MAX_TEST_ROUNDS,
    ):
        self.max_iterations = max_iterations
        self.max_review_rounds = max_review_rounds
        self.max_test_rounds = max_test_rounds
        self.review_calls = 0  # 本轮任务 code_review 已执行次数
        self.test_calls = 0    # 本轮任务 run_tests 已执行次数

    async def run(self, task: str, agent: "Agent", history: list | None = None) -> str:
        """执行任务，返回最终回复文本。

        history: 跨任务对话历史（user/assistant 消息，含可选的 [历史摘要]），
        拼在 system 之后、当前任务之前，实现多轮对话记忆。
        """
        messages: list = [{"role": "system", "content": agent.system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": task})
        iterations = 0

        while iterations < self.max_iterations:
            iterations += 1
            # 上下文管理：超限时压缩（裁剪旧工具结果 / LLM 摘要）
            messages, ctx_stats = await agent.context.ensure_within_budget(messages, agent.call_llm)
            if ctx_stats:
                agent.emit(make_event(
                    CONTEXT_COMPRESSED,
                    released=ctx_stats.get("released", 0),
                    truncated=ctx_stats.get("truncated", 0),
                    summarized=ctx_stats.get("summarized", 0),
                ))
            resp = await agent.call_llm(
                messages, tools=agent.tool_schemas()
            )
            # 用量统计：真实 token（API usage）+ 当前上下文估算 + 累计调用次数
            usage = getattr(resp, "usage", None)
            agent.emit(make_event(
                USAGE,
                llm_calls=agent.llm_calls,
                context_tokens=agent.context.count_tokens(messages),
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
            ))
            msg = resp.choices[0].message
            # finish_reason：模型停止原因（length = 输出被 max_tokens 截断）
            finish_reason = getattr(resp.choices[0], "finish_reason", None)

            # 模型先给出过程说明（思考/计划），转发给前端展示
            if msg.content:
                agent.emit(make_event(THINKING, content=msg.content))

            # 有工具调用 → 逐个执行并回填，进入下一轮
            if msg.tool_calls:
                assistant_msg = {
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                }
                messages.append(assistant_msg)

                # finish_reason == length：输出被截断，tool_calls 参数可能残缺，
                # 一律判失败，不执行（截断的参数执行会带来错误副作用）
                if finish_reason == "length":
                    agent.emit(make_event(
                        ERROR,
                        content="模型响应达到输出上限（finish_reason=length），本轮工具调用参数可能被截断，全部视为失败",
                    ))
                    for tc in msg.tool_calls:
                        fail = {"ok": False, "output": "模型响应被截断，工具调用参数可能不完整，请重新发起完整调用"}
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(fail, ensure_ascii=False),
                        })
                    continue

                for tc in msg.tool_calls:
                    name = tc.function.name
                    agent.emit(
                        make_event(
                            TOOL_CALL,
                            id=tc.id,
                            name=name,
                            args=tc.function.arguments,
                        )
                    )
                    # 参数 JSON 解析失败：不静默执行，给模型明确错误让其重新发起
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        parse_fail = {
                            "ok": False,
                            "output": (
                                f"工具参数 JSON 解析失败：{tc.function.arguments[:200]}。"
                                f"参数格式不合法，请重新发起完整、合法的工具调用。"
                            ),
                        }
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(parse_fail, ensure_ascii=False),
                        })
                        agent.emit(make_event(
                            TOOL_RESULT, id=tc.id, name=name,
                            ok=False, output=parse_fail["output"],
                        ))
                        continue

                    # 轮次硬控制：评审/测试各最多 N 轮，超限直接阻断并引导继续
                    blocked = self._check_round_limit(name)
                    if blocked:
                        result = {"ok": False, "output": blocked}
                    elif not agent.is_tool_allowed(name):
                        result = {"ok": False, "output": f"当前权限级别不允许使用 {name} 工具（仅 L3 可用 git 操作）。"}
                    else:
                        # 统一走注册表执行：未知工具名会返回失败结果（不崩溃）
                        result = agent.registry.execute(name, args)

                    # L1 权限：软修改等待用户确认（暂停循环）
                    pending_id = result.get("pending_change")
                    if pending_id:
                        change = agent.permissions.get(pending_id)
                        if change is not None:
                            decision = await agent.wait_confirmation(change)
                            if decision == "confirmed":
                                result["output"] += f"\n[用户已确认] {agent.permissions.confirm(pending_id)}"
                            else:
                                result["output"] += f"\n[用户已拒绝] {agent.permissions.reject(pending_id)}"
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
            # L3：任务完成时自动提交全部改动（如有 git 仓库）
            commit_note = await agent.finalize_commit(task)
            if commit_note:
                final += f"\n\n[L3 自动提交] {commit_note}"
            agent.emit(make_event(MESSAGE, content=final))
            agent.emit(make_event(DONE, iterations=iterations, llm_calls=agent.llm_calls))
            return final

        agent.emit(make_event(ERROR, content=f"达到最大迭代次数（{self.max_iterations}），任务中止"))
        agent.emit(make_event(DONE, iterations=iterations, llm_calls=agent.llm_calls))
        return "任务未完成：达到最大迭代次数，已强制停止。请考虑把任务拆小后再试。"

    # ---------- 轮次硬控制 ----------

    def _check_round_limit(self, tool_name: str) -> str | None:
        """评审/测试工具的轮次上限检查。

        返回 None 表示放行；返回文本表示阻断，该文本作为工具失败结果回给模型，
        引导模型继续下一步而不是继续该工具的循环。
        """
        if tool_name == "code_review":
            if self.review_calls >= self.max_review_rounds:
                return (
                    f"评审次数已达上限（{self.max_review_rounds} 次）。"
                    f"请基于已有评审意见直接决定下一步：修复明显问题后继续测试，"
                    f"或完成交付。不要再次调用 code_review。"
                )
            self.review_calls += 1
            return None
        if tool_name == "run_tests":
            if self.test_calls >= self.max_test_rounds:
                return (
                    f"测试次数已达上限（{self.max_test_rounds} 次）。"
                    f"请基于已有测试结果直接决定下一步：修复明显问题后再次验证，"
                    f"或完成交付。不要再次调用 run_tests。"
                )
            self.test_calls += 1
            return None
        return None
