"""Git 操作类工具：git_status / git_diff / git_commit / git_log。

全部通过 git CLI 子命令白名单实现（固定子命令，参数受限），
cwd 限定在工作区。非 git 仓库时返回友好错误，供模型判断。
"""

import os
import subprocess

from ..sandbox import get_workspace, truncate, truncate_with_meta
from .base import Tool

_GIT_TIMEOUT = 30


def _git(args: list[str], timeout: int = _GIT_TIMEOUT) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        ["git", *args],
        cwd=get_workspace(),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _is_repo(proc: subprocess.CompletedProcess) -> bool:
    """git 命令返回码 128 且输出含 not a git repository → 非仓库。"""
    return not (proc.returncode == 128 and "not a git repository" in (proc.stderr + proc.stdout))


class GitStatusTool(Tool):
    name = "git_status"
    description = (
        "查看工作区 git 状态：哪些文件被修改/新增/删除（简化版 git status --short）。"
        "用于任务开始前了解仓库状态、修改后确认改动。工作区不是 git 仓库时返回提示。"
    )
    parameters = {"type": "object", "properties": {}, }

    def execute(self, args: dict) -> dict:
        try:
            proc = _git(["status", "--short"])
            if not _is_repo(proc):
                return {"ok": False, "output": "当前工作区不是 git 仓库（无 .git 目录）。如需要版本管理请先 git init。"}
            output = (proc.stdout or "").strip()
            if not output:
                return {"ok": True, "output": "工作区干净，无未提交的改动。"}
            lines = output.splitlines()
            summary = f"共 {len(lines)} 处改动："
            raw = summary + "\n" + "\n".join(lines[:40])
            out, truncated, total = truncate_with_meta(raw)
            result = {"ok": True, "output": out}
            if truncated:
                result["truncated"] = True
                result["total_chars"] = total
            return result
        except subprocess.TimeoutExpired:
            return {"ok": False, "output": "git status 执行超时"}
        except Exception as e:
            return {"ok": False, "output": f"git status 执行失败：{e}"}


class GitDiffTool(Tool):
    name = "git_diff"
    description = (
        "查看改动内容（git diff）：返回未提交改动的 +/- 行文本。"
        "path 指定文件时只看该文件。用于评审前了解改了什么、确认改动正确。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "只看指定文件的改动（相对工作区路径，可选）"},
        },
    }

    def execute(self, args: dict) -> dict:
        try:
            target = str(args.get("path") or "")
            # 先确认是 git 仓库
            check = _git(["rev-parse", "--is-inside-work-tree"])
            if check.returncode != 0:
                return {"ok": False, "output": "当前工作区不是 git 仓库。如需要版本管理请先 git init。"}
            # 有 HEAD 则对比 HEAD，否则对比暂存区/工作区
            rev = _git(["rev-parse", "--verify", "HEAD"])
            if rev.returncode == 0:
                cmd = ["diff", "HEAD", "--"] + ([target] if target else [])
            else:
                cmd = ["diff", "--"] + ([target] if target else [])
            proc = _git(cmd)
            output = (proc.stdout or "").strip()
            if not output:
                return {"ok": True, "output": "（无未提交的改动）"}
            out, truncated, total = truncate_with_meta(output)
            result = {"ok": True, "output": out}
            if truncated:
                result["truncated"] = True
                result["total_chars"] = total
            return result
        except subprocess.TimeoutExpired:
            return {"ok": False, "output": "git diff 执行超时"}
        except Exception as e:
            return {"ok": False, "output": f"git diff 执行失败：{e}"}


class GitCommitTool(Tool):
    name = "git_commit"
    description = (
        "提交全部改动到 git（git add -A + git commit）：把当前所有未提交改动打包成一次提交。"
        "message 是提交信息，应简短描述本次改动内容。提交成功后返回 commit 哈希。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "提交信息，简短描述本次改动（如 实现排序功能并添加测试）"},
        },
        "required": ["message"],
    }

    def execute(self, args: dict) -> dict:
        try:
            message = str(args.get("message", "")).strip()
            if not message:
                return {"ok": False, "output": "提交信息不能为空"}
            check = _git(["rev-parse", "--is-inside-work-tree"])
            if check.returncode != 0:
                return {"ok": False, "output": "当前工作区不是 git 仓库。如需要版本管理请先 git init。"}
            _git(["add", "-A"])
            proc = _git(["commit", "-m", message])
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()
                if "nothing to commit" in err:
                    return {"ok": False, "output": "没有可提交的改动（工作区已干净）"}
                return {"ok": False, "output": f"git commit 失败：{err[:300]}"}
            hash_proc = _git(["rev-parse", "--short", "HEAD"])
            commit_hash = (hash_proc.stdout or "").strip()
            return {"ok": True, "output": f"已提交：{commit_hash} - {message}"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "output": "git commit 执行超时"}
        except Exception as e:
            return {"ok": False, "output": f"git commit 执行失败：{e}"}


class GitLogTool(Tool):
    name = "git_log"
    description = "查看提交历史（git log --oneline）：返回最近 N 次提交的 哈希+信息。用于了解仓库演进。"
    parameters = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "显示最近几次提交，默认 20", "minimum": 1, "maximum": 100},
        },
    }

    def execute(self, args: dict) -> dict:
        try:
            limit = min(int(args.get("limit") or 20), 100)
            proc = _git(["log", "--oneline", "--no-color", f"-n{limit}"])
            if not _is_repo(proc):
                return {"ok": False, "output": "当前工作区不是 git 仓库。如需要版本管理请先 git init。"}
            output = (proc.stdout or "").strip()
            if not output:
                return {"ok": True, "output": "仓库还没有任何提交记录。"}
            out, truncated, total = truncate_with_meta(output)
            result = {"ok": True, "output": out}
            if truncated:
                result["truncated"] = True
                result["total_chars"] = total
            return result
        except subprocess.TimeoutExpired:
            return {"ok": False, "output": "git log 执行超时"}
        except Exception as e:
            return {"ok": False, "output": f"git log 执行失败：{e}"}
