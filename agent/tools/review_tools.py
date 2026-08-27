"""代码质量评审工具：code_review —— 以评审者视角审查代码，输出问题清单。

设计定位（见 PLAN §4）：评审本质是一个工具，是"测试通过 ≠ 任务完成"的质量兜底。
- 不设独立"反思框架"：执行性验证（跑测试）已被 ReAct 内化；
  code_review 提供的是"换视角重新审视"的主观评审
- 与文件/执行类工具同级注册，模型在 ReAct 循环中按需自主决定调用（不固定时机）

实现：收集被审内容（指定文件 / git diff / 最近修改的 .py 文件）
→ 先对目标文件做编译器级语法检查（ast.parse，机械可靠）
→ 语法结果作为事实输入，连同代码一起交给评审者视角 prompt
→ 调 LLM → 返回问题清单（语法错误会被列为严重问题）。
"""

import ast
import os
import subprocess
from pathlib import Path

from ..sandbox import get_workspace, safe_join, truncate
from .base import Tool

REVIEW_PROMPT = """你是资深代码评审专家。请以严格的评审者视角审查以下代码，不要赞美，只找问题。

任务需求（用于需求符合性检查）:
{context}

编译器级语法检查结果（这是事实，语法错误必须列为严重问题并要求修复）:
{syntax_result}

审查维度：
1. 语法正确性：如语法检查报告存在错误，直接列为 [严重] 问题并给出修复建议
2. 功能正确性：逻辑错误、边界条件、异常处理是否缺失
3. 需求符合性：对照任务需求逐条检查是否有遗漏或偏差
4. 代码质量：可读性、重复代码、命名、结构
5. 安全性：路径处理、命令执行、输入校验是否有隐患

输出格式（严格遵循）：
- 没有发现问题：只输出「✅ 评审通过：未发现问题」
- 发现问题：逐条列出，每条一行：
  [严重级别] 位置（文件名:行号）: 问题描述 → 修复建议
  严重级别取：严重 / 一般 / 建议

只输出评审结论本身，不要输出任何其他内容。

待审查内容：
{content}
"""


class CodeReviewTool(Tool):
    name = "code_review"
    description = (
        "以评审者视角审查代码质量：先对目标文件做编译器级语法检查，"
        "再审查逻辑/需求/质量/安全，输出问题清单与修复建议。"
        "用于任务收尾阶段确认代码真正达标（测试通过≠任务完成），"
        "也可在实现过程中自主调用自查。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要审查的文件（相对工作区路径）；省略则自动收集 git diff 或最近修改的文件",
            },
            "context": {
                "type": "string",
                "description": "任务需求描述，用于检查需求符合性（可选）",
            },
        },
    }

    def __init__(self, llm=None):
        # 评审需要调用 LLM，构造时注入（由 Agent 组装时传入）
        self.llm = llm

    def execute(self, args: dict) -> dict:
        if self.llm is None:
            return {"ok": False, "output": "评审工具未注入 LLM 客户端，无法执行评审"}
        try:
            files, content = self._collect_content(args.get("path"))
            # 编译器级语法检查（机械可靠），结果作为事实输入评审
            syntax_result = self._syntax_check(files)
            prompt = REVIEW_PROMPT.format(
                context=str(args.get("context") or "（无）"),
                syntax_result=syntax_result,
                content=content,
            )
            resp = self.llm.chat(
                [{"role": "system", "content": "你是资深代码评审专家。"},
                 {"role": "user", "content": prompt}],
                temperature=0.1,
            )
            verdict = resp.choices[0].message.content or "（评审无输出）"
            return {"ok": True, "output": truncate(verdict)}
        except Exception as e:
            return {"ok": False, "output": f"评审失败：{type(e).__name__}: {e}"}

    def _collect_content(self, rel_path: str | None) -> tuple[list[Path], str]:
        """收集待审内容与待审文件列表：指定文件 / git diff / 最近修改的 .py 文件。"""
        ws = get_workspace()
        if rel_path:
            target = safe_join(rel_path)
            if not target.is_file():
                raise FileNotFoundError(f"文件不存在：{rel_path}")
            return [target], f"### 文件 {rel_path}\n```\n{target.read_text(encoding='utf-8')}\n```"

        # 优先收集 git diff（能精确反映本次改动）
        diff = self._git_diff(ws)
        if diff:
            return self._git_changed_py_files(ws), f"### git diff（本次改动）\n```diff\n{diff}\n```"

        # 非 git 仓库：取最近修改的 3 个 .py 文件
        py_files = sorted(
            (p for p in ws.rglob("*.py") if ".git" not in p.parts),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:3]
        if not py_files:
            return [], "（工作区内没有可审查的 Python 文件）"
        parts = []
        for p in py_files:
            rel = p.relative_to(ws).as_posix()
            parts.append(f"### 文件 {rel}\n```\n{p.read_text(encoding='utf-8')}\n```")
        return py_files, "\n\n".join(parts)

    @staticmethod
    def _syntax_check(files: list[Path]) -> str:
        """编译器级语法检查（ast.parse），返回逐文件结果。"""
        if not files:
            return "（无可检查的 Python 文件）"
        lines = []
        for f in files:
            try:
                ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
                lines.append(f"✅ {f.relative_to(get_workspace()).as_posix()}：语法正确")
            except SyntaxError as e:
                loc = f"第 {e.lineno} 行" if e.lineno else "未知位置"
                lines.append(f"❌ {f.relative_to(get_workspace()).as_posix()}：语法错误（{loc}）：{e.msg}")
            except Exception as e:
                lines.append(f"⚠️ {f.relative_to(get_workspace()).as_posix()}：检查失败：{e}")
        return "\n".join(lines)

    @staticmethod
    def _git_changed_py_files(ws) -> list[Path]:
        """从 git diff --name-only 提取本次改动的 .py 文件。"""
        try:
            proc = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=ws,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            if proc.returncode != 0:
                return []
            files = []
            for name in proc.stdout.splitlines():
                if name.endswith(".py"):
                    p = (ws / name).resolve()
                    if p.is_file():
                        files.append(p)
            return files
        except Exception:
            return []

    @staticmethod
    def _git_diff(ws) -> str:
        try:
            proc = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=ws,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            if proc.returncode != 0:
                return ""
            return proc.stdout[:4000]  # diff 截断，防超上下文
        except Exception:
            return ""
