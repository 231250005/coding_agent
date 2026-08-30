"""接口层端到端验证（需要服务已启动：python server/main.py）。

三个场景：
A. L1 确认闭环：chat(L1) → SSE 收到 request_confirmation → confirm → 文件落盘 → applied
B. L2 撤销：chat(L2) 修改文件 → 变更 applied → revert → 文件还原 → reverted
C. L1 拒绝：chat(L1) → request_confirmation → reject → 文件不生成 → rejected

运行：python tests/api_e2e_check.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "http://localhost:8000"


def create_session(workspace: str) -> int:
    r = requests.post(f"{BASE}/api/sessions", json={"workspace": workspace, "title": "E2E测试"})
    assert r.status_code == 200, r.text
    return r.json()["data"]["id"]


def read_events(session_id: int, on_event=None) -> list[str]:
    """读 SSE 直到 task_done；on_event(ev) 可在收到事件时发 REST 请求。"""
    types = []
    with requests.get(f"{BASE}/api/sessions/{session_id}/events", stream=True) as resp:
        resp.encoding = "utf-8"
        for line in resp.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                ev = json.loads(line[6:])
                types.append(ev["type"])
                if on_event:
                    on_event(ev)
                if ev["type"] == "task_done":
                    break
    return types


def chat(session_id: int, content: str, permission_level: int):
    r = requests.post(
        f"{BASE}/api/sessions/{session_id}/chat",
        json={"content": content, "permission_level": permission_level},
    )
    assert r.status_code == 200, r.text


def get_changes(session_id: int) -> list[dict]:
    r = requests.get(f"{BASE}/api/sessions/{session_id}/changes")
    assert r.status_code == 200, r.text
    return r.json()["data"]


def db_status(change_id: int) -> str:
    import pymysql

    conn = pymysql.connect(
        host="localhost", user="root", password="123456",
        database="coding_agent", cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM file_changes WHERE id=%s", (change_id,))
            row = cur.fetchone()
            return row["status"] if row else "?"
    finally:
        conn.close()


def check(name: str, cond: bool, detail: str = ""):
    mark = "✅" if cond else "❌"
    print(f"   {mark} {name}" + (f" | {detail}" if detail else ""))
    if not cond:
        raise AssertionError(f"检查失败：{name}")


def main():
    ws = tempfile.mkdtemp(prefix="api_e2e_ws_")

    # ============ 场景 A：L1 确认闭环 ============
    print("=" * 50)
    print("[A] L1 确认闭环")
    sid = create_session(ws)

    def on_a(ev):
        if ev["type"] == "request_confirmation":
            cid = ev["change_id"]
            print(f"   🔔 request_confirmation: change={cid} file={ev['file_path']}")
            r = requests.post(f"{BASE}/api/changes/{cid}/confirm")
            print(f"   ✅ confirm → {r.json()['data']}")

    chat(sid, "用 Python 写一个 hello.py，内容只有 print('hi')，并用 run_command 运行验证", 1)
    types = read_events(sid, on_a)
    check("SSE 收到 request_confirmation", "request_confirmation" in types)
    check("hello.py 已落盘", os.path.exists(os.path.join(ws, "hello.py")))
    changes = get_changes(sid)
    check("变更已记录且 applied", len(changes) >= 1 and changes[0]["status"] == "applied",
          f"{[(c['file_path'], c['status']) for c in changes]}")
    check("变更含前后对比", "diff" in changes[0] and "+ print('hi')" in changes[0]["diff"])

    # ============ 场景 B：L2 撤销 ============
    print("=" * 50)
    print("[B] L2 修改 + 撤销")
    chat(sid, "把 hello.py 的内容修改为 print('hello world')", 2)
    read_events(sid)
    changes = get_changes(sid)
    target = [c for c in changes if c["file_path"] == "hello.py" and c["status"] == "applied"]
    check("L2 修改产生 applied 变更", len(target) >= 1, f"{len(target)} 条")
    if target:
        before = Path(ws, "hello.py").read_text(encoding="utf-8")
        r = requests.post(f"{BASE}/api/changes/{target[-1]['id']}/revert")
        print(f"   revert → {r.json()['data']}")
        after = Path(ws, "hello.py").read_text(encoding="utf-8")
        check("文件已还原", after != before, f"{before.strip()!r} → {after.strip()!r}")
        check("DB 记录已删除", db_status(target[-1]["id"]) == "?", f"status={db_status(target[-1]['id'])}")
        remaining = get_changes(sid)
        check("变更列表不再含已撤销记录", all(c["id"] != target[-1]["id"] for c in remaining),
              f"剩余 {len(remaining)} 条")

    # ============ 场景 C：L1 拒绝 ============
    print("=" * 50)
    print("[C] L1 拒绝")
    rejected_id = {"id": None}

    def on_c(ev):
        if ev["type"] == "request_confirmation":
            rejected_id["id"] = ev["change_id"]
            print(f"   🔔 request_confirmation: change={ev['change_id']} file={ev['file_path']}")
            r = requests.post(f"{BASE}/api/changes/{ev['change_id']}/reject")
            print(f"   ✅ reject → {r.json()['data']}")

    chat(sid, "再写一个 bye.py，内容只有 print('bye')", 1)
    read_events(sid, on_c)
    check("bye.py 未生成（被拒绝）", not os.path.exists(os.path.join(ws, "bye.py")))
    if rejected_id["id"]:
        check("DB 记录已删除", db_status(rejected_id["id"]) == "?", f"status={db_status(rejected_id['id'])}")

    # 清理
    requests.delete(f"{BASE}/api/sessions/{sid}")
    print("=" * 50)
    print("✅ 接口层端到端验证全部通过")


if __name__ == "__main__":
    main()
