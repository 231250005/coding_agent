"""执行类工具：run_command —— 在本地 shell 中运行命令。"""

import os
import subprocess

from ..sandbox import DEFAULT_TIMEOUT, get_workspace, truncate
from .base import Tool


class RunCommandTool(Tool):
    name = "run_command"
    description = (
        "在用户机器的 shell（Windows cmd）中执行一条命令。"
        "常用于运行程序验证结果（如 python game.py）、执行测试、查看环境等。"
        "命令在工作区目录下执行，默认 60 秒超时，输出过长会自动截断。"
        "注意：shell 是 Windows cmd 而不是 bash：管道符直接写 |，不要加 ^ 转义"
        "（错误示例 echo 50^|python game.py 只会打印字符串；正确写法 echo 50|python game.py）。"
        "交互式程序（需要输入的游戏）不要直接运行阻塞，应先用 python -m py_compile 做语法检查，"
        "再用测试脚本传入输入验证。"
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
                "description": "超时秒数，默认 60，最大 300",
                "minimum": 1,
                "maximum": 300,
            },
        },
        "required": ["command"],
    }

    def execute(self, args: dict) -> dict:
        command = str(args.get("command", "")).strip()
        if not command:
            return {"ok": False, "output": "命令不能为空"}
        timeout = int(args.get("timeout") or DEFAULT_TIMEOUT)
        try:
            # 子进程强制 UTF-8 输出并统一按 UTF-8 解码，避免 Windows GBK 乱码
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
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
                "output": truncate(output),
                "exit_code": proc.returncode,
            }
        except Exception as e:
            return {"ok": False, "output": f"命令执行失败：{e}", "exit_code": -1}
