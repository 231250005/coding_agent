"""会话运行器：asyncio 桥接 agent 与 Web（SSE 事件流 + L1 确认 + 变更持久化）。

- 每个会话一个 SessionRunner，持有事件队列（SSE 订阅）与变更持久化钩子
- run_task()：创建 Agent（注入 permissions/confirm_callback/change_sink）运行任务
- 权限每轮切换：复用会话级 PermissionManager，仅更新 level（变更记录会话级累积）
- L1 确认：confirm_callback 挂起 Future，由 REST confirm/reject 接口 resolve
"""

import asyncio
from typing import Optional

from agent.agent import Agent
from agent.llm import LLMClient
from agent.permissions import FileChange, PermissionLevel, PermissionManager

from .tables.file_changes import FileChangeTable
from .tables.messages import MessageTable

# L1 确认超时（秒）：用户未确认则自动拒绝，避免 agent 无限挂起
CONFIRM_TIMEOUT = 300
# 跨任务摘要触发阈值：未摘要的轮次数（user 消息数）超过该值才触发增量摘要
SUMMARY_TRIGGER_ROUNDS = 10
# 摘要时每条消息的内容预览长度
SUMMARY_MSG_PREVIEW = 500

SUMMARIZE_PROMPT = """你是对话历史记录员。请把新增的对话合并进已有摘要，生成更新后的会话摘要。

旧摘要（可能为空）：
{old_summary}

新增对话（最近几轮，未摘要的部分）：
{new_messages}

要求：
1. 输出更新后的完整摘要（不是只写新增部分）
2. 保留关键信息：已完成的工作、产出文件路径、函数/命令名、关键决策、用户偏好、测试结果、错误信息
3. 按结构组织：已完成 / 当前状态 / 下一步
4. 只输出摘要本身，不要解释

新摘要："""


class SessionRunner:
    def __init__(self, session_id: int, session_factory, workspace: str):
        self.session_id = session_id
        self.session_factory = session_factory
        self.workspace = workspace
        self.events: asyncio.Queue = asyncio.Queue()
        self._subscribers = 0  # SSE 订阅者计数（无订阅者时事件直接丢弃，防泄漏）
        self._task: Optional[asyncio.Task] = None
        self._confirm_futures: dict[int, asyncio.Future] = {}
        self._task_seq = 0
        # 会话级 PermissionManager：权限每轮切换（level 更新），变更记录跨任务累积
        self.permissions = PermissionManager(
            level=PermissionLevel.L3, change_sink=self._change_sink
        )

    # ---------- 事件 ----------

    def subscribe(self) -> None:
        """SSE 连接建立时调用。"""
        self._subscribers += 1

    def unsubscribe(self) -> None:
        """SSE 连接断开时调用（防止队列无人消费持续累积）。"""
        self._subscribers = max(0, self._subscribers - 1)

    def emit(self, event: dict) -> None:
        # 无订阅者时直接丢弃（任务后台运行时无人消费，不累积内存）
        if self._subscribers > 0:
            self.events.put_nowait(event)

    async def events_stream(self):
        """SSE 消费者：持续产出事件（跨任务；前端断开时由 StreamingResponse 取消）。"""
        while True:
            event = await self.events.get()
            yield event

    # ---------- 任务运行 ----------

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def run_task(self, content: str, permission_level: int) -> None:
        """启动新任务（权限每轮切换；运行中再启动抛 RuntimeError）。

        每轮加载跨任务历史（最新摘要 + 其后轮次），实现多轮对话记忆。
        """
        if self.is_running():
            raise RuntimeError("任务运行中")
        self._task_seq += 1
        self.permissions.level = PermissionLevel(permission_level)
        history = self._load_history()
        if history:
            history = history[:-1]  # 去掉当前轮的 user（chat 接口已入库）
        agent = Agent(
            permission_level=permission_level,
            permissions=self.permissions,
            confirm_callback=self._make_confirm_callback(),
            change_sink=self._change_sink,
            on_event=self.emit,
            workspace=self.workspace,
        )
        self._task = asyncio.create_task(
            self._run_agent(agent, content, permission_level, history)
        )

    async def _run_agent(
        self, agent: Agent, content: str, permission_level: int, history: list | None
    ) -> None:
        self.emit({"type": "task_start", "task_id": self._task_seq, "permission_level": permission_level})
        try:
            result = await agent.run(content, history=history)
            # 存 assistant 最终回复（对话历史）
            with self.session_factory() as db:
                MessageTable.add(db, self.session_id, "assistant", result, permission_level)
        except Exception as e:
            self.emit({"type": "error", "content": f"{type(e).__name__}: {e}"})
        # 任务结束信号
        self.emit({"type": "task_done", "task_id": self._task_seq})
        # 跨任务摘要：未摘要轮次超阈值时增量合并历史
        self._maybe_summarize()

    # ---------- 跨任务上下文（多轮记忆） ----------

    def _load_history(self) -> list[dict]:
        """加载对话历史：最新摘要（如有）+ 摘要之后的所有 user/assistant。"""
        with self.session_factory() as db:
            summary = MessageTable.get_latest_summary(db, self.session_id)
            after_id = summary.id if summary else 0
            rows = MessageTable.list_after(db, self.session_id, after_id)
        history: list[dict] = []
        if summary is not None:
            history.append({"role": "user", "content": f"[历史摘要] {summary.content}"})
        for row in rows:
            if row.role in ("user", "assistant"):
                history.append({"role": row.role, "content": row.content})
        return history

    def _maybe_summarize(self) -> None:
        """未摘要轮次（summary 之后的 user 消息数）超阈值 → 增量摘要。"""
        with self.session_factory() as db:
            summary = MessageTable.get_latest_summary(db, self.session_id)
            after_id = summary.id if summary else 0
            rows = MessageTable.list_after(db, self.session_id, after_id)
            rounds = sum(1 for r in rows if r.role == "user")
        if rounds <= SUMMARY_TRIGGER_ROUNDS:
            return
        try:
            self._run_summarize(summary, rows)
        except Exception as e:
            self.emit({"type": "error", "content": f"会话摘要失败：{e}"})

    def _run_summarize(self, summary, rows: list) -> None:
        """LLM 增量合并：旧摘要 + 新增轮次 → 新摘要（插入 role='summary' 消息）。"""
        llm = _get_llm()
        old_summary = summary.content if summary else "（无）"
        new_messages = "\n".join(
            f"[{r.role}] {(r.content or '')[:SUMMARY_MSG_PREVIEW]}" for r in rows
        )
        resp = llm.chat(
            [
                {"role": "system", "content": "你是对话历史记录员。"},
                {"role": "user", "content": SUMMARIZE_PROMPT.format(
                    old_summary=old_summary, new_messages=new_messages
                )},
            ],
            temperature=0.2,
        )
        new_summary = (resp.choices[0].message.content or "").strip()
        if not new_summary:
            return
        with self.session_factory() as db:
            MessageTable.add(db, self.session_id, "summary", new_summary, 3)
        self.emit({"type": "message", "content": f"[会话摘要已更新]"})

    # ---------- L1 确认 ----------

    def _make_confirm_callback(self):
        async def confirm(change: FileChange) -> str:
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            self._confirm_futures[change.change_id] = future
            try:
                return await asyncio.wait_for(future, timeout=CONFIRM_TIMEOUT)
            except asyncio.TimeoutError:
                return "rejected"
            finally:
                self._confirm_futures.pop(change.change_id, None)

        return confirm

    def resolve_confirm(self, change_id: int, decision: str) -> bool:
        """REST confirm/reject 接口调用：resolve 挂起的确认 Future。"""
        future = self._confirm_futures.get(change_id)
        if future is None or future.done():
            return False
        future.set_result(decision)
        self.emit({"type": "change_status", "change_id": change_id, "status": "confirmed" if decision == "confirmed" else "rejected"})
        return True

    # ---------- 变更持久化 ----------

    def _change_sink(self, change: FileChange, action: str) -> Optional[int]:
        """写 file_changes 表（同步 SQLAlchemy session）；add 返回数据库 id。"""
        with self.session_factory() as db:
            if action == "add":
                return FileChangeTable.add(
                    db,
                    session_id=self.session_id,
                    file_path=change.file_path,
                    operation=change.operation,
                    old_content=change.old_content,
                    new_content=change.new_content,
                    status=change.status,
                    permission_level=int(change.permission_level),
                )
            if action == "confirm":
                FileChangeTable.update_status(db, change.change_id, "applied", confirmed=True)
            elif action == "merge":
                # 同文件多次修改合并：更新最新内容（保留最早旧内容）
                FileChangeTable.update_content(db, change.change_id, change.new_content, change.operation)
            elif action in ("reject", "revert"):
                # 拒绝/撤销的变更彻底删除（不再出现在变更列表）
                FileChangeTable.delete(db, change.change_id)
        return None


# 摘要用的 LLM 客户端（模块级缓存，复用连接）
_llm: Optional[LLMClient] = None


def _get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm


# 会话运行器注册表（模块级单例容器）
_runners: dict[int, SessionRunner] = {}


def create_runner(session_id: int, session_factory, workspace: str) -> SessionRunner:
    runner = SessionRunner(session_id, session_factory, workspace)
    _runners[session_id] = runner
    return runner


def get_runner(session_id: int) -> Optional[SessionRunner]:
    return _runners.get(session_id)


def remove_runner(session_id: int) -> None:
    _runners.pop(session_id, None)
