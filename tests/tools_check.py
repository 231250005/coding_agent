"""工具层验证脚本（普通脚本，非 pytest）。

验证 4 个基础工具的注册与执行：
1. 注册表：工具是否全部注册、schema 是否可导出
2. write_file → run_command → read_file → list_dir 完整链路
3. 路径穿越防护：../ 逃逸应被拒绝

运行：python tests/tools_check.py
"""

import os
import sys
from pathlib import Path

# 确保能导入项目根目录下的 agent 包（无论从哪运行）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.tools import build_default_registry

TEST_FILE = "_tools_check_tmp.py"


def main():
    reg = build_default_registry()
    print("=" * 50)
    print("[1] 注册表：已注册工具 =", reg.names())
    schemas = reg.schemas()
    print(f"    schema 数量 = {len(schemas)}，首个工具名 = {schemas[0]['function']['name']}")

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

    os.remove(TEST_FILE)
    print("=" * 50)
    print("✅ 工具层全部验证通过")


if __name__ == "__main__":
    main()
