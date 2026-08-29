"""会话运行器：asyncio 桥接 agent 与 Web（SSE 事件流 + L1 确认 + 变更持久化）。

- 每个会话一个 SessionRunner，持有事件队列（SSE 订阅）与变更持久化钩子
- run_task()：创建 Agent（注入 permissions/confirm_callback/change_sink）运行任务
- 权限每轮切换：复用会话级 PermissionManager，仅更新 level（变更记录会话级累积）
- L1 确认：confirm_callback 挂起 Future，由 REST confirm/reject 接口 resolve
"""

import asyncio
from typing import Optional

from agent.agent import Agent
from agent.permissions import FileChange, PermissionLevel, PermissionManager

from .tables.file_changes import FileChangeTable

# L1 确认超时（秒）：用户未确认则自动拒绝，避免 agent 无限挂起
CONFIRM_TIMEOUT = 300


class SessionRunner:
    def __init__(self, session_id: int, session_factory, workspace: str):
        self.session_id = session_id
        self.session_factory = session_factory
        self.workspace = workspace
        self.events: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._confirm_futures: dict[int, asyncio.Future] = {}
        self._task_seq = 0
        # 会话级 PermissionManager：权限每轮切换（level 更新），变更记录跨任务累积
        self.permissions = PermissionManager(
            level=PermissionLevel.L3, change_sink=self._change_sink
        )

    # ---------- 事件 ----------

    def emit(self, event: dict) -> None:
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
        """启动新任务（权限每轮切换；运行中再启动抛 RuntimeError）。"""
        if self.is_running():
            raise RuntimeError("任务运行中")
        self._task_seq += 1
        self.permissions.level = PermissionLevel(permission_level)
        agent = Agent(
            permission_level=permission_level,
            permissions=self.permissions,
            confirm_callback=self._make_confirm_callback(),
            change_sink=self._change_sink,
            on_event=self.emit,
            workspace=self.workspace,
        )
        self._task = asyncio.create_task(self._run_agent(agent, content, permission_level))

    async def _run_agent(self, agent: Agent, content: str, permission_level: int) -> None:
        self.emit({"type": "task_start", "task_id": self._task_seq, "permission_level": permission_level})
        try:
            await agent.run(content)
        except Exception as e:
            self.emit({"type": "error", "content": f"{type(e).__name__}: {e}"})
        # 任务结束信号（iterations/llm_calls 由 agent 的 done 事件携带，这里补收尾）
        self.emit({"type": "task_done", "task_id": self._task_seq})

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
            elif action == "reject":
                FileChangeTable.update_status(db, change.change_id, "rejected")
            elif action == "revert":
                FileChangeTable.update_status(db, change.change_id, "reverted", reverted=True)
        return None


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
