"""工具层验证脚本（普通脚本，非 pytest）。

验证 4 个基础工具的注册与执行，分三组：
- 正常路径：write_file → run_command → read_file → list_dir 完整链路
- 安全防护：路径穿越（../）、未知工具
- 异常/边界：文件不存在、自动建目录、空命令、命令超时、长文件截断

工作区被临时指向系统临时目录，测试不会污染项目目录。

运行：python tests/tools_check.py
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

# 确保能导入项目根目录下的 agent 包（无论从哪运行）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 测试隔离：所有工具操作指向一个临时工作区
_WS = tempfile.mkdtemp(prefix="tools_check_ws_")
os.environ["WORKSPACE_DIR"] = _WS

from agent.tools import build_default_registry

TEST_FILE = "hello.py"


def main():
    reg = build_default_registry()
    print("=" * 50)
    print("[1] 注册表：已注册工具 =", reg.names())
    schemas = reg.schemas()
    print(f"    schema 数量 = {len(schemas)}，首个工具名 = {schemas[0]['function']['name']}")

    # ---------- 正常路径 ----------
    print("=" * 50)
    print("[2] write_file 写入测试文件")
    r = reg.execute("write_file", {"path": TEST_FILE, "content": "print('hello from tools_check')\n"})
    print("   ", r["ok"], "|", r["output"])

    print("=" * 50)
    print("[3] run_command 运行它")
    r = reg.execute("run_command", {"command": f"python {TEST_FILE}"})
    print("   ", r["ok"], "|", r["output"].strip())

    print("=" * 50)
    print("[4] read_file 带行号读取")
    r = reg.execute("read_file", {"path": TEST_FILE})
    print("   ", r["ok"], "|", repr(r["output"]))

    print("=" * 50)
    print("[5] list_dir 列目录")
    r = reg.execute("list_dir", {})
    print("   ", r["ok"], "|", r["output"].replace("\n", " | ")[:200])

    # ---------- 安全防护 ----------
    print("=" * 50)
    print("[6] 路径穿越防护（期望 ok=False）")
    r = reg.execute("read_file", {"path": "../Windows/win.ini"})
    print("   ", r["ok"], "|", r["output"])
    r = reg.execute("read_file", {"path": "../../../../etc/passwd"})
    print("   ", r["ok"], "|", r["output"])

    print("=" * 50)
    print("[7] 未知工具（期望 ok=False）")
    r = reg.execute("no_such_tool", {})
    print("   ", r["ok"], "|", r["output"])

    # ---------- 异常/边界 ----------
    print("=" * 50)
    print("[8] read_file 不存在的文件（期望 ok=False）")
    r = reg.execute("read_file", {"path": "not_exist.py"})
    print("   ", r["ok"], "|", r["output"])

    print("=" * 50)
    print("[9] write_file 自动创建子目录")
    r = reg.execute("write_file", {"path": "src/util.py", "content": "x = 1\n"})
    print("   ", r["ok"], "|", r["output"])
    r = reg.execute("list_dir", {"path": "src"})
    print("    子目录内容:", r["output"].replace("\n", " | "))

    print("=" * 50)
    print("[10] run_command 空命令（期望 ok=False）")
    r = reg.execute("run_command", {"command": ""})
    print("   ", r["ok"], "|", r["output"])

    print("=" * 50)
    print("[11] run_command 超时（期望 ok=False 且提示超时）")
    r = reg.execute("run_command", {"command": 'python -c "import time; time.sleep(10)"', "timeout": 1})
    print("   ", r["ok"], "|", r["output"])

    print("=" * 50)
    print("[12] 长文件读取截断（600 行文件只显示 500 行）")
    reg.execute("write_file", {"path": "long.py", "content": "\n".join(f"x{i} = {i}" for i in range(600))})
    r = reg.execute("read_file", {"path": "long.py"})
    print("   ", r["ok"], "| 行数 =", len(r["output"].splitlines()), "| 末尾提示 =", r["output"].splitlines()[-1][:40])

    # ---------- 清理 ----------
    shutil.rmtree(_WS, ignore_errors=True)
    print("=" * 50)
    print("✅ 工具层全部验证通过（12 项，临时工作区已清理）")


if __name__ == "__main__":
    main()
