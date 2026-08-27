"""Plan-and-Execute 顶层推理框架。

两级结构（见 PLAN §4）：
- 顶层（本文件，恒定外壳）：规划 → 子任务循环 → 收尾评审
- 内核：ReAct（mode=react，工具调用推理循环）/ 单次 LLM 回答（mode=plain）

核心设计（均落实为真实 LLM 调用，非空壳）：
1. 规划 JSON 协议：{goal, steps:[{id, task, mode, output}]}，由 LLM 生成，
   子任务数随任务复杂度自适应（简单 2~3 步，复杂最多 8 步）
2. 子任务级上下文隔离：每个子任务独立消息历史，完成后由 LLM 提取结果摘要，
   只把摘要放进全局上下文——长任务不上下文爆炸
3. 每步完成后由 LLM 判断：继续 / 重规划 / 全部完成（及时思考是否完成）
4. 收尾评审：调用 code_review 工具以评审者视角检查，发现问题回修（≤2 轮）
5. 多层终止条件：步骤完成判定 / 子任务数上限 / 单子任务迭代上限 / 重规划上限
"""

import json

from ..events import (
    DONE,
    ERROR,
    MESSAGE,
    PLAN,
    REPLAN,
    REVIEW,
    SUBTASK_DONE,
    SUBTASK_START,
    make_event,
)
from .base import AgentStrategy
from .react import ReActStrategy

# 多层终止条件上限
MAX_STEPS = 8              # 子任务数上限
MAX_REPLANS = 2            # 重规划次数上限
MAX_REVIEW_ROUNDS = 2      # 收尾评审修复轮数上限
SUBTASK_MAX_ITERATIONS = 12  # 单子任务 ReAct 迭代上限

PLANNER_PROMPT = """你是 CodeAgent 的任务规划器。请把用户任务分解为有序的子任务步骤列表。

任务：{task}

要求：
1. 先分析任务目标、约束和完成标准（什么才算真正完成，比如要测试通过、要提交 git）
2. 分解为 2~8 个有序子任务（简单任务 2~3 步，复杂任务可到 8 步）
3. 每个子任务标注 mode：
   - "react"：需要调用工具完成（写代码/改文件/探索代码库/运行命令与测试）
   - "plain"：纯思考分析，不需要工具（方案设计/代码理解/总结汇报）
4. 每个子任务写明预期产出（output 字段）
5. 编码任务的常见步骤：理解需求与探索环境 → 实现 → 测试验证 → 收尾（如 git 提交）
6. 步骤之间要有依赖顺序，后面的步骤可以依赖前面步骤的产出

只输出一个 JSON 对象，不要输出任何其他内容：
{{"goal": "对任务的总体理解与完成标准", "steps": [{{"id": 1, "task": "步骤描述", "mode": "react", "output": "预期产出"}}]}}"""

JUDGE_PROMPT = """你是任务执行监控器，负责判断任务是否需要继续推进。

任务目标：{goal}

执行进度（各子任务结果摘要）：
{progress}

剩余步骤：
{remaining}

请判断下一步动作：
- "done"：所有必要工作都已完成，任务可以结束
- "continue"：还有步骤需要执行，继续推进
- "replan"：当前计划已不适配实际进展，需要重新规划

只输出 JSON：{{"action": "done|continue|replan", "reason": "简短理由"}}"""

SUMMARIZE_PROMPT = """请把子任务的执行结果压缩为不超过 120 字的结构化摘要，突出：完成了什么、产出哪些文件、验证结果如何、有无遗留问题。

子任务：{task}
执行结果：
{result}

只输出摘要文本本身。"""

FINAL_SUMMARY_PROMPT = """你是 CodeAgent。请基于以下任务执行记录，生成面向用户的最终汇报（中文，清晰有条理）。

用户任务：{task}

各子任务执行记录：
{progress}

收尾评审结论：
{review}

汇报要求：
- 总结完成了什么、产出哪些文件、验证结果
- 如有遗留问题或注意事项（如运行方式），一并说明
- 不要输出 JSON"""


class PlanExecuteStrategy(AgentStrategy):
    name = "plan_execute"
    description = "Plan-and-Execute：先规划拆分子任务，逐步执行（ReAct 内核），收尾评审"

    async def run(self, task: str, agent: "Agent") -> str:
        plan = await self._plan(task, agent)
        agent.emit(make_event(PLAN, goal=plan.get("goal", ""), steps=plan.get("steps", [])))

        summaries: list[str] = []
        replans = 0
        step_index = 0

        # ---------- 子任务循环 ----------
        while step_index < len(plan["steps"]):
            if len(summaries) >= MAX_STEPS:
                agent.emit(make_event(ERROR, content=f"达到子任务数上限（{MAX_STEPS}），任务中止"))
                break
            step = plan["steps"][step_index]
            agent.emit(make_event(
                SUBTASK_START,
                index=step_index + 1,
                total=len(plan["steps"]),
                task=step["task"],
                mode=step.get("mode", "react"),
            ))

            result = await self._execute_step(step, summaries, agent)
            summary = await self._summarize(step, result, agent)
            summaries.append(summary)
            agent.emit(make_event(SUBTASK_DONE, index=step_index + 1, summary=summary))

            # 每步完成后的 LLM 判断：继续 / 重规划 / 完成
            action = await self._judge(task, plan, summaries, agent)
            if action == "done":
                break
            if action == "replan" and replans < MAX_REPLANS:
                replans += 1
                agent.emit(make_event(REPLAN, reason=f"第 {replans} 次重规划"))
                plan = await self._plan(task, agent, progress=summaries)
                agent.emit(make_event(PLAN, goal=plan.get("goal", ""), steps=plan.get("steps", [])))
                step_index = -1  # 从新计划第一个步骤开始
            step_index += 1

        # ---------- 收尾评审（质量兜底） ----------
        review_output = await self._final_review(task, summaries, agent)

        # ---------- 最终汇报 ----------
        final = await self._final_summary(task, summaries, review_output, agent)
        agent.emit(make_event(MESSAGE, content=final))
        agent.emit(make_event(DONE, iterations=len(summaries)))
        return final

    # ---------- ① 规划 ----------

    async def _plan(self, task: str, agent: "Agent", progress: list[str] | None = None) -> dict:
        progress_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(progress or [])) or "（无）"
        prompt = PLANNER_PROMPT.format(task=task)
        if progress:
            prompt += f"\n\n注意：以下子任务已经完成，请基于实际进展重新规划剩余工作（不要重复已完成的部分）：\n{progress_text}"
        resp = await agent.llm.chat_async(
            [{"role": "system", "content": "你是任务规划器。"}, {"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return self._parse_plan(resp.choices[0].message.content or "", task)

    @staticmethod
    def _parse_plan(text: str, task: str) -> dict:
        """解析规划 JSON，容忍 markdown 代码块包裹；失败降级为单步骤整任务执行。"""
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return PlanExecuteStrategy._fallback_plan(task)
        steps = data.get("steps", []) if isinstance(data, dict) else []
        if not isinstance(steps, list) or not steps:
            return PlanExecuteStrategy._fallback_plan(task)
        # 规范化字段，过滤无 task 的步骤
        clean_steps = []
        for i, s in enumerate(steps):
            if not isinstance(s, dict) or not s.get("task"):
                continue
            clean_steps.append({
                "id": s.get("id", i + 1),
                "task": s["task"],
                "mode": s.get("mode", "react") if s.get("mode") in ("react", "plain") else "react",
                "output": s.get("output", ""),
            })
        if not clean_steps:
            return PlanExecuteStrategy._fallback_plan(task)
        return {"goal": data.get("goal", task), "steps": clean_steps}

    @staticmethod
    def _fallback_plan(task: str) -> dict:
        return {
            "goal": task,
            "steps": [{"id": 1, "task": task, "mode": "react", "output": "任务完成"}],
        }

    # ---------- ② 子任务执行 ----------

    @staticmethod
    def _build_subtask_message(step: dict, summaries: list[str]) -> str:
        context = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(summaries))
        ctx_text = context or "（无，这是第一个子任务）"
        return (
            f"【当前子任务】{step['task']}\n"
            f"【预期产出】{step.get('output', '')}\n\n"
            f"【已完成子任务的结果摘要】\n{ctx_text}\n\n"
            f"请专注完成当前子任务。"
        )

    async def _execute_step(self, step: dict, summaries: list[str], agent: "Agent") -> str:
        if step.get("mode") == "plain":
            # plain：单次 LLM 回答，不给工具（纯思考分析）
            messages = [
                {"role": "system", "content": agent.system_prompt},
                {"role": "user", "content": self._build_subtask_message(step, summaries)},
            ]
            resp = await agent.llm.chat_async(messages)
            return resp.choices[0].message.content or "（无输出）"
        # react：ReAct 内核（子任务模式：不单独发 MESSAGE/DONE，由顶层统一汇报）
        runner = ReActStrategy(max_iterations=SUBTASK_MAX_ITERATIONS)
        return await runner.run(
            self._build_subtask_message(step, summaries),
            agent,
            extra_context="\n".join(f"{i + 1}. {s}" for i, s in enumerate(summaries)),
            report_final=False,
        )

    # ---------- 子任务摘要提取 ----------

    async def _summarize(self, step: dict, result: str, agent: "Agent") -> str:
        resp = await agent.llm.chat_async(
            [{"role": "system", "content": "你是任务记录员。"},
             {"role": "user", "content": SUMMARIZE_PROMPT.format(task=step["task"], result=result)}],
            temperature=0.2,
            max_retries=1,
        )
        return (resp.choices[0].message.content or result)[:200]

    # ---------- 步骤间判断 ----------

    async def _judge(self, task: str, plan: dict, summaries: list[str], agent: "Agent") -> str:
        # 剩余步骤 = 计划中尚未产生摘要的步骤
        remaining = [
            {"id": s.get("id", i + 1), "task": s["task"]}
            for i, s in enumerate(plan["steps"])
            if i >= len(summaries) - 1
        ]
        prompt = JUDGE_PROMPT.format(
            goal=plan.get("goal", task),
            progress="\n".join(f"{i + 1}. {s}" for i, s in enumerate(summaries)),
            remaining=json.dumps(remaining, ensure_ascii=False) or "（无）",
        )
        try:
            resp = await agent.llm.chat_async(
                [{"role": "system", "content": "你是任务执行监控器。"},
                 {"role": "user", "content": prompt}],
                temperature=0.1,
            )
            text = (resp.choices[0].message.content or "").strip()
            data = json.loads(text[text.find("{"): text.rfind("}") + 1])
            action = data.get("action", "continue")
            return action if action in ("done", "continue", "replan") else "continue"
        except Exception:
            return "continue"  # 判断失败时保守继续

    # ---------- ③ 收尾评审 ----------

    async def _final_review(self, task: str, summaries: list[str], agent: "Agent") -> str:
        try:
            review_tool = agent.registry.get("code_review")
        except KeyError:
            return "（未注册评审工具，跳过收尾评审）"

        context = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(summaries))
        issues = review_tool.execute({"context": f"任务需求：{task}\n执行记录：{context}"})
        agent.emit(make_event(REVIEW, ok=issues.get("ok", False), content=issues.get("output", "")))

        for round_no in range(MAX_REVIEW_ROUNDS):
            output = issues.get("output", "")
            if "评审通过" in output or "未发现问题" in output or "无问题" in output:
                return output
            # 有问题：把评审意见作为修复子任务，用 ReAct 内核修复后复评审
            agent.emit(make_event(SUBTASK_START, index=f"修复{round_no + 1}", total="评审", task="修复评审发现的问题", mode="react"))
            runner = ReActStrategy(max_iterations=SUBTASK_MAX_ITERATIONS)
            fix_task = f"根据以下代码评审意见修复代码问题：\n{output}"
            await runner.run(fix_task, agent, extra_context=context, report_final=False)
            issues = review_tool.execute({"context": f"任务需求：{task}\n执行记录：{context}"})
            agent.emit(make_event(REVIEW, ok=issues.get("ok", False), content=issues.get("output", "")))
        return issues.get("output", "（评审未通过但修复轮数已用尽）")

    # ---------- 最终汇报 ----------

    async def _final_summary(self, task: str, summaries: list[str], review: str, agent: "Agent") -> str:
        resp = await agent.llm.chat_async(
            [{"role": "system", "content": "你是 CodeAgent。"},
             {"role": "user", "content": FINAL_SUMMARY_PROMPT.format(
                 task=task,
                 progress="\n".join(f"{i + 1}. {s}" for i, s in enumerate(summaries)),
                 review=review,
             )}],
            temperature=0.3,
        )
        return resp.choices[0].message.content or "任务已完成。"
