"""测试闭环工具：run_tests（执行）+ generate_test（生产）。

- generate_test：对目标代码文件生成 pytest 测试样例（内部调 LLM），
  产出 test_<名>.py —— 测试的"生产端"
- run_tests：运行测试并返回结构化结果（通过数/失败数/失败用例明细）；
  支持指定已有测试文件（含用户既有脚本）与自动发现 —— 测试的"执行端"

生产 → 执行 闭环：generate_test 产出 → run_tests 运行 → 失败则修复复跑。
"""

import os
import re
import subprocess
import sys

from ..permissions import PermissionLevel, PermissionManager
from ..sandbox import get_workspace, safe_join, truncate
from .base import Tool

GENERATE_TEST_PROMPT = """你是测试工程师。请为以下 Python 代码生成 pytest 单元测试。

要求：
1. 覆盖正常路径、边界条件、异常路径
2. 使用 pytest 风格（def test_xxx()，普通断言，不要写 main）
3. 不要 mock 被测函数自身；外部依赖（文件/网络）用 monkeypatch 或临时目录隔离
4. 测试应能独立运行（可 import 被测模块：假设测试文件与被测文件同目录，
   必要时用 sys.path 处理导入）
5. 只输出测试代码本身，不要任何解释文字

被测代码（{rel_path}）：
```python
{source}
```"""


class GenerateTestTool(Tool):
    name = "generate_test"
    description = (
        "为指定代码文件生成 pytest 测试样例：分析代码后生成 test_<文件名>.py"
        "（覆盖正常/边界/异常路径）。完成或修改功能代码后应主动调用为代码补测试；"
        "生成后用 run_tests 运行验证。path 必须是相对工作区的相对路径。"
        "keep=false 表示交付型任务的临时验证测试：直接写盘、不写入文件变更记录，"
        "验证后应删除该临时文件。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "目标代码文件（相对工作区路径），如 todo.py",
            },
            "keep": {
                "type": "boolean",
                "description": "是否保留测试文件（默认 true）：true = 测试作为交付物保留，"
                               "走正常权限记录（L1 需确认 / L2 可撤销）；"
                               "false = 交付型任务的临时验证，直接写盘、不写入文件变更记录，验证后删除",
            },
        },
        "required": ["path"],
    }

    def __init__(self, llm=None, permissions: PermissionManager | None = None):
        self.llm = llm
        self.permissions = permissions

    def execute(self, args: dict) -> dict:
        if self.llm is None:
            return {"ok": False, "output": "生成测试工具未注入 LLM 客户端，无法生成测试"}
        try:
            target = safe_join(str(args["path"]))
            if not target.is_file():
                return {"ok": False, "output": f"文件不存在：{args['path']}"}

            rel = target.relative_to(get_workspace()).as_posix()
            # 测试文件路径：test_<basename>.py（同目录）
            test_path = target.parent / f"test_{target.stem}.py"
            if test_path.is_file():
                return {
                    "ok": False,
                    "output": (
                        f"测试文件已存在：{test_path.relative_to(get_workspace()).as_posix()}。"
                        f"如需重新生成请先删除该文件，或先 read_file 查看已有内容再用 edit_file 补充。"
                    ),
                }

            source = target.read_text(encoding="utf-8")
            resp = self.llm.chat(
                [{"role": "system", "content": "你是测试工程师。"},
                 {"role": "user", "content": GENERATE_TEST_PROMPT.format(rel_path=rel, source=source)}],
                temperature=0.2,
            )
            code = self._extract_code(resp.choices[0].message.content or "")
            if "def test_" not in code and "class Test" not in code:
                return {"ok": False, "output": "生成的测试不包含 test 用例，生成失败，请重试"}

            case_count = code.count("def test_")
            test_rel = test_path.relative_to(get_workspace()).as_posix()
            keep = bool(args.get("keep", True))  # 默认保留（测试作为交付物）

            # 权限联动（同 write_file）：L1 软修改等确认 / L2/L3 落盘+记录。
            # keep=false（交付型临时验证）：直接写盘、不进入文件变更记录——
            # 临时测试文件不是交付内容，不应出现在变更面板/确认流程/撤销列表里。
            if self.permissions is not None and keep:
                old_content = test_path.read_text(encoding="utf-8") if test_path.is_file() else ""
                change = self.permissions.add_change(test_rel, "write", old_content, code, test_path)
                if self.permissions.level == PermissionLevel.L1:
                    return {
                        "ok": True,
                        "output": (
                            f"已暂存对 {test_rel} 的修改（等待用户确认，change_id={change.change_id}）。"
                            f"用户确认后才真正写入。"
                        ),
                        "pending_change": change.change_id,
                        "written": False,
                    }
                test_path.write_text(code, encoding="utf-8")
                return {"ok": True, "output": f"已生成测试文件 {test_rel}（{case_count} 个测试用例）"}

            # keep=false 或无权限管理（CLI）：直接写
            test_path.write_text(code, encoding="utf-8")
            if not keep:
                return {
                    "ok": True,
                    "output": (
                        f"已生成临时测试文件 {test_rel}（{case_count} 个测试用例，"
                        f"未写入变更记录）。请用 run_tests 运行验证，验证后删除该临时文件。"
                    ),
                }
            return {
                "ok": True,
                "output": (
                    f"已生成测试文件 {test_rel}（{case_count} 个测试用例），请用 run_tests 运行验证"
                ),
            }
        except Exception as e:
            return {"ok": False, "output": f"生成测试失败：{type(e).__name__}: {e}"}

    @staticmethod
    def _extract_code(text: str) -> str:
        """从 LLM 输出中提取测试代码（容忍 markdown 代码块与说明文字）。"""
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            for i in range(1, len(parts), 2):
                block = parts[i]
                if block.startswith("python"):
                    block = block[6:]
                if "def test_" in block or "class Test" in block:
                    return block.strip()
        return text


class RunTestsTool(Tool):
    name = "run_tests"
    description = (
        "运行测试并返回结构化结果（通过数/失败数/失败用例明细）。"
        "path 指定要运行的测试文件或目录（如 test_todo.py、tests/，"
        "支持用户已有的测试脚本）；省略 path 时自动发现工作区全部测试。"
        "keyword 可只运行名称匹配的用例（pytest -k）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "测试文件或目录（相对工作区），省略则自动发现全部测试",
            },
            "keyword": {
                "type": "string",
                "description": "只运行名称匹配的用例（可选）",
            },
            "timeout": {
                "type": "integer",
                "description": "超时秒数，默认 120，最大 600",
                "minimum": 5,
                "maximum": 600,
            },
        },
    }

    def execute(self, args: dict) -> dict:
        try:
            timeout = int(args.get("timeout") or 120)
            cmd = [sys.executable, "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider"]
            if args.get("path"):
                cmd.append(str(args["path"]))
            if args.get("keyword"):
                cmd += ["-k", str(args["keyword"])]

            env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
            proc = subprocess.run(
                cmd,
                cwd=get_workspace(),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            out = (proc.stdout or "") + (proc.stderr or "")

            # 结构化解析
            m = re.search(r"(\d+) passed", out)
            passed = int(m.group(1)) if m else 0
            m = re.search(r"(\d+) failed", out)
            failed = int(m.group(1)) if m else 0
            m = re.search(r"(\d+) error", out)
            errors = int(m.group(1)) if m else 0
            failed_cases = [line.strip() for line in out.splitlines() if line.strip().startswith("FAILED ")]

            lines = [f"测试结果：{passed} 通过 / {failed} 失败 / {errors} 错误"]
            if failed_cases:
                lines.append("失败用例：")
                lines.extend(failed_cases[:20])
                if len(failed_cases) > 20:
                    lines.append(f"… 共 {len(failed_cases)} 个失败")
            elif not passed and not failed and not errors:
                # 无测试被发现或运行异常，展示原始输出供诊断
                lines.append(f"（未识别到测试结果，原始输出）\n{truncate(out, 1500)}")

            return {
                "ok": proc.returncode == 0,
                "output": truncate("\n".join(lines)),
                "passed": passed,
                "failed": failed,
                "errors": errors,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "output": f"测试执行超时（>{timeout} 秒），已终止", "passed": 0, "failed": 0, "errors": 0}
        except Exception as e:
            return {"ok": False, "output": f"测试执行失败：{type(e).__name__}: {e}", "passed": 0, "failed": 0, "errors": 0}
