"""工具注册表：统一管理工具的定义与执行。

- register() 注册工具（注册表模式：新增工具只加一个类 + 一行注册，不改核心循环）
- schemas() 导出所有工具的 JSON schema 给 LLM
- execute() 按工具名执行并返回统一格式结果
"""

from .base import Tool
from .exec_tools import RunCommandTool, RunPythonTool
from .explore_tools import FindSymbolsTool, GlobTool, GrepTool, ListDirTool
from .file_tools import EditFileTool, ReadFileTool, WriteFileTool
from .git_tools import GitCommitTool, GitDiffTool, GitLogTool, GitStatusTool
from .review_tools import CodeReviewTool
from .test_tools import GenerateTestTool, RunTestsTool

__all__ = ["Tool", "ToolRegistry", "build_default_registry"]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def schemas(self) -> list[dict]:
        """所有工具的 OpenAI 函数调用 schema，随每次 LLM 请求发送。"""
        return [tool.to_schema() for tool in self._tools.values()]

    def execute(self, name: str, args: dict) -> dict:
        """执行工具。任何异常都转成失败结果回给模型，不让循环崩溃。"""
        try:
            tool = self._tools[name]
        except KeyError:
            return {"ok": False, "output": f"未知工具：{name}（可用工具：{', '.join(self.names())}）"}
        # 参数校验：缺必填参数时直接回可行动错误，不进入工具执行
        ok, err = tool.validate(args or {})
        if not ok:
            return {"ok": False, "output": err}
        try:
            return tool.execute(args)
        except Exception as e:
            return {"ok": False, "output": f"工具 {name} 执行异常：{e}"}


def build_default_registry(llm=None) -> ToolRegistry:
    """构建默认工具集。后续新增工具在这里注册一行即可。

    llm: 注入给依赖 LLM 的工具（如 code_review 评审工具）。
    """
    registry = ToolRegistry()
    for tool in (
        WriteFileTool(),
        ReadFileTool(),
        EditFileTool(),
        RunCommandTool(),
        RunPythonTool(),
        ListDirTool(),
        GrepTool(),
        GlobTool(),
        FindSymbolsTool(),
        RunTestsTool(),
        GenerateTestTool(llm=llm),
        GitStatusTool(),
        GitDiffTool(),
        GitCommitTool(),
        GitLogTool(),
        CodeReviewTool(llm=llm),
    ):
        registry.register(tool)
    return registry
