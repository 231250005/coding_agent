"""三级权限系统验证（不调用真实 LLM / API）。

覆盖：
1. L1 软修改：write 不落盘（pending）→ confirm 后落盘 / reject 不落盘
2. L1 read_file 虚拟视图（pending 时读到新内容）
3. L2 直接修改 + 记录 → revert 还原
4. L3 写文件自动 git commit（临时仓库）
5. 工具可见性过滤：L1/L2 的 schema 不含 git 工具

运行：python tests/permissions_check.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_WS = tempfile.mkdtemp(prefix="perm_check_ws_")
os.environ["WORKSPACE_DIR"] = _WS

from agent.permissions import PermissionLevel, PermissionManager
from agent.tools.file_tools import EditFileTool, ReadFileTool, WriteFileTool


def check(name: str, cond: bool, detail: str = ""):
    mark = "✅" if cond else "❌"
    print(f"   {mark} {name}" + (f" | {detail}" if detail else ""))
    if not cond:
        raise AssertionError(f"检查失败：{name}")


def main():
    # ---------- L1 软修改 ----------
    print("=" * 50)
    print("[1] L1 软修改：write 进入 pending，不落盘")
    perm = PermissionManager(PermissionLevel.L1)
    writer = WriteFileTool(permissions=perm)
    r = writer.execute({"path": "game.py", "content": "print('hello')\n"})
    check("返回 pending_change", r.get("pending_change") == 1, f"change_id={r.get('pending_change')}")
    check("文件未落盘", not (Path(_WS) / "game.py").exists())

    print("=" * 50)
    print("[2] L1 read_file 虚拟视图：pending 时读到新内容")
    reader = ReadFileTool(permissions=perm)
    r = reader.execute({"path": "game.py"})
    check("读到虚拟内容", "print('hello')" in r["output"], r["output"].strip()[:60])

    print("=" * 50)
    print("[3] L1 confirm 后真正落盘 / reject 不落盘")
    r = perm.confirm(1)
    check("confirm 消息", "已确认" in r)
    check("文件已落盘", (Path(_WS) / "game.py").exists())
    # 第二个 pending 变更，reject
    r2 = writer.execute({"path": "other.py", "content": "x = 1\n"})
    check("第二个变更 pending", r2.get("pending_change") == 2)
    r = perm.reject(2)
    check("reject 消息", "已拒绝" in r)
    check("文件未落盘", not (Path(_WS) / "other.py").exists())

    print("=" * 50)
    print("[4] L2 直接修改 + 记录，revert 还原")
    perm2 = PermissionManager(PermissionLevel.L2)
    target = Path(_WS) / "demo.py"
    target.write_text("value = 1\n", encoding="utf-8")
    editor = EditFileTool(permissions=perm2)
    r = editor.execute({"path": "demo.py", "old_string": "value = 1", "new_string": "value = 2"})
    check("L2 直接修改成功", r["ok"] and "已修改" in r["output"], r["output"][:50])
    check("文件内容已更新", target.read_text(encoding="utf-8") == "value = 2\n")
    changes = perm2.changes()
    check("变更已记录 applied", len(changes) == 1 and changes[0].status == "applied")
    r = perm2.revert(changes[0].change_id)
    check("revert 消息", "已撤销" in r)
    check("文件已还原", target.read_text(encoding="utf-8") == "value = 1\n")

    print("=" * 50)
    print("[5] 工具可见性过滤：L1/L2 不含 git 工具，L3 包含")
    schemas = [{"function": {"name": "write_file"}},
               {"function": {"name": "git_commit"}},
               {"function": {"name": "run_tests"}}]
    filtered = PermissionManager(PermissionLevel.L1).filter_schemas(schemas)
    names = [s["function"]["name"] for s in filtered]
    check("L1 过滤 git_commit", "git_commit" not in names and "write_file" in names, f"{names}")
    names3 = [s["function"]["name"] for s in PermissionManager(PermissionLevel.L3).filter_schemas(schemas)]
    check("L3 保留 git_commit", "git_commit" in names3)

    print("=" * 50)
    print("[6] L3 任务结束时自动提交（临时仓库）")
    import asyncio as _asyncio
    from agent.agent import Agent
    git_ws = Path(_WS) / "git_repo"
    git_ws.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=git_ws)
    subprocess.run(["git", "config", "user.name", "test"], cwd=git_ws)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=git_ws)
    os.environ["WORKSPACE_DIR"] = str(git_ws)
    # 模拟任务产物（等价于 agent 写完文件后的状态）
    (git_ws / "app.py").write_text("print('hi')\n", encoding="utf-8")
    agent3 = Agent(permission_level=PermissionLevel.L3)
    note = _asyncio.run(agent3.finalize_commit("实现一个简单脚本"))
    check("L3 返回提交说明", "已提交" in note, note)
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=git_ws,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    check("git 历史有提交", "agent 任务完成" in (log.stdout or ""), (log.stdout or "").strip()[:60])
    # L2 不触发提交
    agent2 = Agent(permission_level=PermissionLevel.L2)
    note2 = _asyncio.run(agent2.finalize_commit("x"))
    check("L2 不触发提交", note2 == "")

    shutil.rmtree(_WS, ignore_errors=True)
    print("=" * 50)
    print("✅ 三级权限系统验证全部通过")


if __name__ == "__main__":
    main()
