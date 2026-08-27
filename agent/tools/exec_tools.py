"""执行类工具：run_command —— 在本地 shell 中运行命令。"""

import subprocess

from ..sandbox import DEFAULT_TIMEOUT, get_workspace, truncate
from .base import Tool


class RunCommandTool(Tool):
    name = "run_command"
    description = (
        "在用户机器的 shell（Windows cmd）中执行一条命令。"
        "常用于运行程序验证结果（如 python game.py）、执行测试、查看环境等。"
        "命令在工作区目录下执行，默认 60 秒超时，输出过长会自动截断。"
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
            proc = subprocess.run(
                command,
                shell=True,
                cwd=get_workspace(),
                capture_output=True,
                text=True,
                errors="replace",  # Windows 下子进程输出为 GBK 时避免解码崩溃
                timeout=timeout,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            if not output.strip():
                output = f"(命令执行成功，退出码 {proc.returncode}，无输出)"
            return {
                "ok": proc.returncode == 0,
                "output": truncate(output),
                "exit_code": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "output": f"命令执行超时（>{timeout} 秒），已终止", "exit_code": -1}
        except Exception as e:
            return {"ok": False, "output": f"命令执行失败：{e}", "exit_code": -1}
