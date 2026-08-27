"""安全层：工作区隔离、路径防护、输出截断。

所有工具都限定在"工作区"（WORKSPACE_DIR，默认项目根目录）内操作，
防止模型生成的路径逃逸到工作区之外（如 ../../Windows/...）。
"""

import os
from pathlib import Path

# 输出截断上限（字符数）：防止工具输出撑爆模型上下文
MAX_OUTPUT_CHARS = 8000
# 命令默认超时（秒）
DEFAULT_TIMEOUT = 60
# 单文件读取上限（行数）
MAX_READ_LINES = 500

# 环境变量默认值：未配置时使用项目根目录
DEFAULT_WORKSPACE = str(Path.cwd())


def get_workspace() -> Path:
    """获取 agent 工作区绝对路径（WORKSPACE_DIR 环境变量可覆盖）。"""
    return Path(os.environ.get("WORKSPACE_DIR") or DEFAULT_WORKSPACE).resolve()


def safe_join(rel_path: str) -> Path:
    """把工具传入的相对路径解析到工作区内，防止路径穿越（../ 逃逸）。

    工具只能传相对工作区的路径；越界直接抛异常，由工具层转成失败结果回给模型。
    """
    if not rel_path or not rel_path.strip():
        raise ValueError("路径不能为空")
    workspace = get_workspace()
    target = (workspace / rel_path.strip()).resolve()
    if not target.is_relative_to(workspace):
        raise ValueError(f"路径越界（不允许访问工作区之外）：{rel_path}")
    return target


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    """截断过长的文本，保留头部并提示截断原因。"""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… (输出过长已截断，仅显示前 {limit} 字符)"
