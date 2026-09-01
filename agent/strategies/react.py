"""ReAct 策略：规范化 tool-calling 循环（思考 → 调用 → 观察 → … → 最终回复）。

循环流程（每步规范化）：
1. 把 messages + 工具 schema 发给 LLM
2. 模型返回 tool_calls → 逐个本地执行 → 结果回填为 tool 消息 → 回到 1
3. 模型返回无 tool_calls 的回复 → 即任务最终回复 → 结束
4. 兜底：迭代次数达到上限强制结束（防止模型陷入死循环）

工具规范性由系统提示词约束（见 prompts.py）：
只调用注册表中真实存在的工具，禁止编造工具或声称完成工具集不支持的动作。
"""

import asyncio
import hashlib
import json
import subprocess

from ..events import CONTEXT_COMPRESSED, DONE, ERROR, MESSAGE, THINKING, TOOL_CALL, TOOL_RESULT, USAGE, make_event
from ..sandbox import get_workspace
from .base import AgentStrategy

DEFAULT_MAX_ITERATIONS = 20
# 测试轮次硬上限：防止模型陷入"测试→修改→再测试"的无限循环
MAX_TEST_ROUNDS = 2


class ReActStrategy(AgentStrategy):
    name = "react"
    description = "规范化 ReAct 循环：思考 → 调用现有工具 → 观察结果 → 直到任务完成"

    def __init__(
        self,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        max_test_rounds: int = MAX_TEST_ROUNDS,
    ):
        self.max_iterations = max_iterations
        self.max_test_rounds = max_test_rounds
        # 评审按"内容是否变化"去重，不按次数上限：
        # rel 路径 → 上次评审时的文件内容 md5（指定 path 的评审）
        self._reviewed_files: dict[str, str] = {}
        # 无 path 评审的工作区改动集合指纹（git diff / 最近修改文件快照）
        self._no_path_key: str | None = None
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
            prompt_tokens = getattr(usage, "prompt_tokens", None)
            # usage 锚定：真实 prompt_tokens = 发送时 messages 的总量，
            # 记录供后续 token 估算校准（压缩触发时机更准）
            agent.context.record_usage(prompt_tokens, len(messages))
            agent.emit(make_event(
                USAGE,
                llm_calls=agent.llm_calls,
                context_tokens=agent.context.count_tokens(messages),
                prompt_tokens=prompt_tokens,
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

                    # 评审/测试控制：评审按内容去重、测试按轮次上限，命中直接阻断并引导继续
                    blocked = self._check_round_limit(name, args)
                    if blocked:
                        result = {"ok": False, "output": blocked}
                    elif not agent.is_tool_allowed(name):
                        result = {"ok": False, "output": f"当前权限级别不允许使用 {name} 工具（仅 L3 可用 git 操作）。"}
                    else:
                        # 统一走注册表执行：未知工具名会返回失败结果（不崩溃）。
                        # 关键：工具（run_command 等）是同步 subprocess，直接调用会阻塞
                        # 事件循环 → 任务运行期间 HTTP 请求（L1 确认等）全部排队。
                        # 放入线程池执行，事件循环保持响应。
                        result = await asyncio.to_thread(agent.registry.execute, name, args)

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

    # ---------- 评审去重 / 测试轮次控制 ----------

    def reset(self) -> None:
        """重置本轮任务状态（Agent.run 每次运行前调用）。

        策略实例可能在多个任务间复用（如 CLI 的 REPL 循环），
        去重状态必须每任务重置，否则上一任务的评审记录会误拦本任务。
        """
        self._reviewed_files.clear()
        self._no_path_key = None
        self.test_calls = 0

    def _check_round_limit(self, tool_name: str, args: dict) -> str | None:
        """评审/测试的控制检查。

        返回 None 表示放行；返回文本表示阻断，该文本作为工具失败结果回给模型，
        引导模型继续下一步而不是继续该工具的循环。

        - code_review：按"内容是否变化"去重，不按次数——
          每次写入/修改后允许评审一次，同一文件的同一内容只评审一次（不重复评审）
        - run_tests：每任务最多 2 轮（硬上限，防"测试→修改→再测试"死循环）
        """
        if tool_name == "code_review":
            return self._check_review(args)
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

    def _check_review(self, args: dict) -> str | None:
        """评审去重：以被审内容是否变化为准，而不是调用次数。

        - 指定 path：按文件内容 md5 去重——内容与上次评审时一致则阻断；
        - 无 path：按工作区改动集合指纹去重（git diff；非仓库为最近 3 个 .py 快照），
          与 CodeReviewTool 的收集逻辑对齐。
        """
        path = str(args.get("path") or "").strip()
        if path:
            # 轻量归一化（./ 前缀、反斜杠），便于同一文件的多次调用对齐
            rel = path.replace("\\", "/")
            while rel.startswith("./"):
                rel = rel[2:]
            try:
                ws = get_workspace()
                target = (ws / rel).resolve()
                # 路径越界/文件不存在：交给工具报错（这里放行）
                if not target.is_relative_to(ws) or not target.is_file():
                    return None
                digest = hashlib.md5(
                    target.read_text(encoding="utf-8", errors="replace").encode("utf-8")
                ).hexdigest()
            except OSError:
                return None
            if self._reviewed_files.get(rel) == digest:
                return (
                    f"文件 {rel} 自上次评审后内容未发生变化，无需重复评审。"
                    f"请基于已有评审意见直接决定下一步（有新的修改后再评审）。"
                )
            self._reviewed_files[rel] = digest
            return None

        key = self._changeset_key()
        if key is not None and key == self._no_path_key:
            return (
                "工作区改动与上次评审时一致，无需重复评审。"
                "请基于已有评审意见直接决定下一步（有新的修改后再评审）。"
            )
        if key is not None:
            self._no_path_key = key
        return None

    def _changeset_key(self) -> str | None:
        """工作区改动集合指纹，与 CodeReviewTool 的收集逻辑对齐。

        优先 git diff HEAD（能精确反映本次改动）；非 git 仓库退化为
        最近修改的 3 个 .py 文件的 (路径, mtime, size) 快照。
        """
        ws = get_workspace()
        try:
            proc = subprocess.run(
                ["git", "diff", "HEAD"], cwd=ws, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=15,
            )
            if proc.returncode == 0:
                return "diff:" + hashlib.md5(proc.stdout.encode("utf-8")).hexdigest()
        except Exception:
            pass
        try:
            py_files = sorted(
                (p for p in ws.rglob("*.py") if ".git" not in p.parts),
                key=lambda p: p.stat().st_mtime, reverse=True,
            )[:3]
            snapshot = [
                (p.relative_to(ws).as_posix(), p.stat().st_mtime, p.stat().st_size)
                for p in py_files
            ]
            return "files:" + repr(snapshot)
        except OSError:
            return None
