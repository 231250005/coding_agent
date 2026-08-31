"""执行类工具：run_command（shell 命令）/ run_python（Python 片段）。

安全：不可逆命令黑名单——递归删除/通配符删除/git 危险/磁盘级操作
在所有权限模式下一律拒绝（可行动错误引导模型改用安全方式）。
"""

import os
import re
import subprocess
import sys

from ..sandbox import DEFAULT_TIMEOUT, get_workspace, truncate, truncate_tail
from .base import Tool

# 不可逆/批量破坏命令黑名单（命中即拒绝，任何权限模式不可绕过）
DANGEROUS_COMMAND_PATTERNS = [
    re.compile(r"\brm\s+-\w*r"),             # rm -rf / rm -r（递归删除）
    re.compile(r"\b(rd|rmdir)\s+/\w*s"),     # rd /s、rmdir /s（递归删除目录）
    re.compile(r"\b(del|erase)\s+/\w*s"),    # del /s、erase /s（递归删除）
    re.compile(r"\b(del|erase|rm|rmdir|rd)\s+.*[*?]"),  # 通配符批量删除
    re.compile(r"\bfor\s+/[rdf]"),           # for 循环动态删除
    re.compile(r"\bfind\s+.*\s-delete"),     # find . -delete
    re.compile(r"\bgit\s+clean\s+-f"),       # git clean -f（删所有未跟踪文件）
    re.compile(r"\bgit\s+reset\s+--hard"),   # git reset --hard（丢弃全部修改）
    re.compile(r"\b(format|mkfs|diskpart)\b"),  # 磁盘级操作
]

DANGEROUS_HINT = (
    "该命令属于不可逆操作（递归/批量/磁盘级删除），已被拒绝——任何权限模式下均不可执行。"
    "如需删除，请指定具体文件路径（如 del file.py）改用安全方式完成。"
)


def _is_dangerous(command: str) -> bool:
    """检测命令是否命中不可逆操作黑名单。"""
    return any(p.search(command) for p in DANGEROUS_COMMAND_PATTERNS)


class RunCommandTool(Tool):
    name = "run_command"
    description = (
        "在用户机器的 shell（Windows cmd）中执行一条命令。"
        "常用于安装依赖（pip install）、查看环境（python --version）等纯命令操作。"
        "注意：不要在用户未要求运行时用本工具运行程序验证；"
        "用户明确要求【运行/打开】程序时用 background=true 启动。"
        "命令在工作区目录下执行，默认 60 秒超时，输出过长会自动截断。"
        "注意：测试执行请用 run_tests 工具，语法检查与代码评审请用 code_review 工具，"
        "不要用本工具做这两件事。"
        "shell 是 Windows cmd 而不是 bash：管道符直接写 |，不要加 ^ 转义"
        "（错误示例 echo 50^|python game.py 只会打印字符串；正确写法 echo 50|python game.py）。"
        "交互式程序（需要输入的游戏）不要直接运行阻塞，用测试脚本传入输入验证。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的完整命令，如 python game.py",
            },
            "timeout": {
                "type": "integer",
                "description": "超时秒数，默认 60，最大 300；background=true 时忽略",
                "minimum": 1,
                "maximum": 300,
            },
            "background": {
                "type": "boolean",
                "description": "true = 后台启动（不等待、不超时终止），适用于用户要求【运行/打开】程序时让窗口常驻；默认 false = 前台执行并等待结果",
            },
        },
        "required": ["command"],
    }

    def execute(self, args: dict) -> dict:
        command = str(args.get("command", "")).strip()
        if not command:
            return {"ok": False, "output": "命令不能为空"}
        # 不可逆操作黑名单：命中直接拒绝（所有权限模式）
        if _is_dangerous(command):
            return {"ok": False, "output": DANGEROUS_HINT, "exit_code": -1}
        timeout = int(args.get("timeout") or DEFAULT_TIMEOUT)
        background = bool(args.get("background", False))
        # 子进程强制 UTF-8 输出并统一按 UTF-8 解码，避免 Windows GBK 乱码
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
        if background:
            # 后台启动：进程持续运行（GUI 窗口常驻可玩），立即返回
            try:
                subprocess.Popen(
                    command,
                    shell=True,
                    cwd=get_workspace(),
                    env=env,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
                return {"ok": True, "output": f"已在后台启动：{command}（窗口/进程持续运行，用户可自行关闭）"}
            except Exception as e:
                return {"ok": False, "output": f"后台启动失败：{e}", "exit_code": -1}
        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=get_workspace(),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",  # 非 Python 程序仍输出 GBK 时不崩溃
            )
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Windows 下 shell=True 只 kill 外层 cmd，子进程会残留；
                # 用 taskkill /T 杀整个进程树，避免僵尸进程占用输入/资源
                subprocess.run(f"taskkill /F /T /PID {proc.pid}", capture_output=True)
                proc.communicate()
                return {"ok": False, "output": f"命令执行超时（>{timeout} 秒），已终止进程树", "exit_code": -1}
            output = (stdout or "") + (stderr or "")
            if not output.strip():
                output = f"(命令执行成功，退出码 {proc.returncode}，无输出)"
            return {
                "ok": proc.returncode == 0,
                "output": truncate_tail(output),  # 保留尾部：错误信息在末尾
                "exit_code": proc.returncode,
            }
        except Exception as e:
            return {"ok": False, "output": f"命令执行失败：{e}", "exit_code": -1}


class RunPythonTool(Tool):
    name = "run_python"
    description = (
        "执行一段 Python 代码（不走 shell，无转义/注入风险）：直接传入代码字符串，"
        "在子进程中运行并返回输出。用于快速验证算法片段、计算结果、测试小函数。"
        "代码在工作区目录下运行，默认 30 秒超时。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "要执行的 Python 代码字符串",
            },
            "timeout": {
                "type": "integer",
                "description": "超时秒数，默认 30，最大 120",
                "minimum": 1,
                "maximum": 120,
            },
        },
        "required": ["code"],
    }

    def execute(self, args: dict) -> dict:
        code = str(args.get("code", "")).strip()
        if not code:
            return {"ok": False, "output": "代码不能为空"}
        timeout = int(args.get("timeout") or 30)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                cwd=get_workspace(),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            if not output.strip():
                output = f"(执行成功，退出码 {proc.returncode}，无输出)"
            return {"ok": proc.returncode == 0, "output": truncate_tail(output), "exit_code": proc.returncode}
        except subprocess.TimeoutExpired:
            return {"ok": False, "output": f"代码执行超时（>{timeout} 秒），已终止", "exit_code": -1}
        except Exception as e:
            return {"ok": False, "output": f"执行失败：{e}", "exit_code": -1}
