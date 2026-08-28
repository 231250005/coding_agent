# 推免考核项目 · 编程智能体（Coding Agent）规划文档

> 目标：个人独立设计并实现一个编程智能体（coding agent），类似简化的 Claude Code / Codex / OpenCode / DeepSeek Harness。
> 截止时间：**2026 年 9 月 2 日 24:00（北京时间）**
> 技术栈：Python 3.11 + FastAPI + openai SDK（OpenAI 兼容模式接通义千问）+ Vue 3 前端（前后端分离）

---

## 1. 题目要求与合规红线（对照检查）

| 要求 | 对策 | 状态 |
|---|---|---|
| 自主读写文件、执行命令完成编程任务 | Agent 主循环 + 本地工具集（全部自写） | |
| 禁止 agent 框架/SDK（LangChain、AutoGen、Claude Agent SDK 等） | 只用 `openai` 客户端库（属于允许的 API 客户端库） | |
| 禁止 API 服务端托管的代码执行/文件工具（Code Interpreter、Files API） | 工具全部本地 `subprocess` + 文件系统实现 | |
| 重要逻辑自行编写：上下文管理、工具定义与执行、输出解析、终止条件、错误处理 | 对应模块：`context.py` / `tools/` / `agent.py` / `strategies/` | |
| API key 走环境变量或未入库配置文件 | `.env` + `.gitignore`（.env 不入库，视频不露 key） | |
| 新建公开仓库、完整提交历史、截止后不再推送 | 新仓库需在今天创建（当前 remote 的仓库 404 不存在） | |
| README.txt ≤1000 汉字 + 2 分钟视频（mp4 ≤200MB） | Day 5~6 完成，打包 `赵贤远.zip` 提交 | |

## 2. 排期（6 天）

| 日期 | 阶段 | 内容 |
|---|---|---|
| **8/27 晚** | 代码 D1 | 新建公开 git 仓库；项目骨架；`llm.py` 接通 qwen3.7-flash 的 tool calling；工具注册表框架 |
| **8/28** | 代码 D2 | Agent 引擎核心：ReAct 单框架 + 规范化工具调用；文件类工具；评审工具 |
| **8/29** | 代码 D3 | 探索类 + 执行类 + git 类工具；上下文管理（token 估算 + 摘要压缩）；错误处理；安全层 |
| **8/30** | 代码 D4 | FastAPI 后端：REST + WebSocket 流式事件、SQLite 持久化（5 张表）、停止机制；**三级权限系统**（软修改确认/撤销/自动 git）；晚间前后端联调 |
| **8/31** | 视频/面试 D5 | 用 agent 完成 2~3 个真实任务（视频素材）；录视频；写 README.txt |
| **9/1** | 视频/面试 D6 | 剪视频（≤2min、≤200MB）；打包提交；过一遍"设计决策辩护点" |
| **9/2** | 缓冲 | 截止 24:00 前最后的修改/补交；不再推送仓库 |

## 3. 总体架构

```
浏览器 (Vue 3 前端, 前后端分离)
   │  WebSocket(实时事件流)      REST(会话管理)
FastAPI 服务 ── server/
   ├── 会话持久化 (SQLite)
   └── Agent 引擎 ── agent/
        ├── llm.py        LLM 调用：OpenAI 兼容(通义千问) + 重试 + 流式
        ├── prompts.py    系统提示词：身份/工作流程/工具规范（独立维护）
        ├── context.py    上下文管理：token 估算 + 长对话摘要压缩
        ├── agent.py      编排器：策略循环、终止条件、错误恢复、事件回调
        ├── strategies/   ReAct（规范化 tool-calling 循环）
        ├── tools/        工具注册表 + 本地实现（文件/探索/执行/git/评审）
        ├── sandbox.py    安全层：工作目录锁定、超时、输出截断、危险命令防护
        └── permissions.py 权限层：三级权限（软修改确认/可撤销/自动 git）
通义千问 API（百炼 dashscope compatible-mode, qwen3.7-flash）
```

技术选型理由（面试会问）：Python + FastAPI + openai SDK 快且稳；前端 Vue 3 + Vite 前后端分离，演示效果好。

## 4. 推理框架：ReAct（规范化 tool-calling 循环）

全局统一采用 ReAct 单框架，不做规划/子任务等附加流程——简单、可控、每步都由真实工具结果驱动。

```
用户任务
   ↓
ReAct 循环（每步规范化）：
  文字简述意图 → 调用一个现有工具 → 观察真实结果 → 循环
   ↓
终止条件：模型无工具调用（输出最终回复）/ 最大迭代 20 / 预算上限 / 用户停止
```

- **每步规范（由系统提示词强制）**：只能调用注册表中真实存在的工具；
  禁止编造工具或假装完成工具集不支持的动作（如"生成测试代码"需由对应工具支持）；
  需要测试时用现有工具组合完成（write_file 写测试脚本 + run_command 运行）；
  语法检查由 code_review 内建（编译器级，不设独立工具）
- **评审工具化**：`code_review` 与文件/执行类工具同级注册，模型在需要时（实现完成、
  测试通过后）按需自主调用；不设独立"反思框架"——执行性验证（跑测试看结果）
  已被 ReAct 循环内化
- **终止条件（多层）**：模型完成判定 / 最大迭代 20 / LLM 调用预算 60 / 用户手动停止
- 面试辩护点：ReAct 单框架简洁可控，每一步都基于真实工具结果决策；
  工具规范性约束防止模型幻觉（编造工具/假完成）

## 5. 工具集（对标 Claude Code，16 个工具，五类）

| 类别 | 工具 | 说明 |
|---|---|---|
| 文件操作 | `read_file` / `write_file` / `edit_file` | edit 用精确替换 + 上下文校验，失败可模糊匹配重试 |
| 代码库探索 | `list_dir` / `grep` / `glob` / `find_symbols` | find_symbols 用 AST 提取函数/类定义位置 |
| 执行与测试 | `run_command` / `run_python` / `run_tests` / `generate_test` | 超时 + 输出截断 + 工作目录限定；run_tests 包装 pytest 返回结构化结果（支持指定已有测试文件与自动发现）；generate_test 对目标代码文件生成测试样例（内部调 LLM，产出 `test_*.py`，与 run_tests 配合"生产→执行"） |
| Git 操作 | `git_status` / `git_diff` / `git_commit` / `git_log` | git CLI 子命令白名单 |
| **代码质量** | `code_review` | 内建**编译器级语法检查**（ast.parse，机械可靠）+ 评审者视角审查逻辑/需求/质量/安全，输出问题清单与修复建议；语法错误列为严重问题；模型在需要时（实现完成/测试通过后）按需自主调用，是"测试通过≠任务完成"的兜底。**不设独立 check_syntax 工具**（语法检查已并入评审） |

每个工具 = JSON schema 定义 + 本地实现，统一走 `ToolRegistry` 注册。

## 6. 后端项目结构

```
coding-agent/
├── agent/                        # 核心引擎（不依赖 FastAPI，可独立跑 CLI）
│   ├── __init__.py
│   ├── llm.py                    # 通义千问(OpenAI兼容)客户端：tool calling/流式/重试
│   ├── prompts.py                # 系统提示词：身份/工作流程/工具使用规范（独立维护）
│   ├── context.py                # 上下文管理：token估算、超长摘要压缩、裁剪
│   ├── events.py                 # AgentEvent 事件模型（thinking/tool_call/tool_result/final/stats）
│   ├── permissions.py            # 三级权限：工具可见性过滤 + 文件变更记录/确认/撤销
│   ├── agent.py                  # Agent 编排器：策略调用、终止条件、错误恢复、事件回调
│   ├── strategies/
│   │   ├── __init__.py           # StrategyRegistry（注册+自动选择）
│   │   ├── base.py               # AgentStrategy 抽象基类
│   │   └── react.py              # ReAct 循环（规范化 tool-calling）
│   ├── tools/
│   │   ├── __init__.py           # ToolRegistry
│   │   ├── base.py               # Tool 抽象基类
│   │   ├── file_tools.py         # read/write/edit
│   │   ├── explore_tools.py      # list_dir/grep/glob/find_symbols
│   │   ├── exec_tools.py         # run_command/run_python
│   │   ├── test_tools.py         # run_tests（pytest 结构化结果）/ generate_test（内部调 LLM 生成测试）
│   │   ├── git_tools.py          # git_status/git_diff/git_commit/git_log
│   │   └── review_tools.py       # code_review：评审者视角检查文件/git diff（内部调 LLM）
│   └── sandbox.py                # 安全层
├── server/                       # FastAPI 服务层
│   ├── __init__.py
│   ├── main.py                   # 创建app、CORS、挂路由
│   ├── agent_runner.py           # asyncio 桥接：agent事件 → WebSocket 推送；停止控制
│   ├── session_store.py          # SQLite 持久化：sessions/messages/file_changes/git_actions/events
│   └── routes/
│       ├── sessions.py           # 会话 CRUD
│       └── ws.py                 # WebSocket 终端
├── cli.py                        # 命令行模式（调试、视频备选演示）
├── tests/                        # 核心逻辑少量单元测试
├── smoke_test.py                 # 大模型连通性冒烟测试
├── .env.example                  # DASHSCOPE_API_KEY / QWEN_MODEL / WORKSPACE_DIR
├── .gitignore
├── PLAN.md                       # 本文档
└── web/                          # Vue 3 前端（独立工程，前后端分离）
```

分层原则：`agent/` 纯逻辑无框架依赖（单测好写、架构清晰）；`server/` 只做 IO 和 WebSocket；策略和工具注册表模式 → 扩展只加文件不改逻辑。

## 7. 前后端接口协议

**REST**：`POST /api/sessions`（新建）、`GET /api/sessions`、`GET /api/sessions/{id}`、`DELETE /api/sessions/{id}`、`GET /api/workspace/tree?depth=3`、`GET /api/workspace/file?path=...`

**权限相关 REST**：`GET /api/sessions/{id}/changes?status=pending`（变更列表）、`POST /api/changes/{id}/confirm`（L1 确认应用）、`POST /api/changes/{id}/reject`（L1 拒绝）、`POST /api/changes/{id}/revert`（L2 撤销）、`PUT /api/sessions/{id}/permission`（切换权限级别）、`GET /api/sessions/{id}/git-actions`（git 提交记录）

**WebSocket** `ws://host/ws/{session_id}`：

- 客户端 → 服务端：`{"type":"chat","content":"..."}`、`{"type":"stop"}`、`{"type":"strategy","name":"react"}`、`{"type":"confirm_change","change_id":1,"action":"confirm|reject"}`、`{"type":"revert_change","change_id":1}`
- 服务端 → 客户端：
  - `{"type":"thinking","content":"..."}` 模型思考过程
  - `{"type":"tool_call","id":1,"name":"run_command","args":{...}}`
  - `{"type":"tool_result","id":1,"name":"run_command","output":"...","ok":true}`
  - `{"type":"request_confirmation","change_id":1,"file_path":"...","operation":"write","diff":"..."}` L1 待确认变更（agent 暂停等待）
  - `{"type":"change_status","change_id":1,"status":"confirmed|rejected|reverted"}`
  - `{"type":"git_commit","commit_hash":"...","message":"..."}` L3 自动提交记录
  - `{"type":"message","content":"最终回复"}` / `{"type":"done","stats":{...}}`（含 token 统计）
  - `{"type":"error","message":"..."}`

前端按事件渲染：thinking 灰色小字、tool_call/tool_result 折叠卡片、request_confirmation 弹出确认面板、message 正文气泡、done 显示统计。

## 8. 权限管理（三级，核心差异化功能）

| 能力 | L1（最低） | L2（中级） | L3（最高） |
|---|---|---|---|
| 写/改文件 | **软修改**：变更进 pending 队列，**用户确认后才真正落盘**；agent 暂停等待 | 直接修改，记录变更**可撤销**（还原 old_content） | 同 L2 |
| 撤销能力 | 确认前可拒绝（不落盘） | 确认后一键撤销 | 同 L2 |
| git 操作工具 | **不提供**（工具列表过滤掉） | **不提供** | 提供；任务执行中写/改文件成功后**自动 git commit**（如有仓库） |
| 只读/执行/评审/测试工具 | 全部正常 | 全部正常 | 全部正常 |

**实现机制（三层）**：
1. **工具可见性过滤**（`agent/permissions.py`）：按权限级别过滤工具列表——L1/L2 不注册 git 四件套，模型无法调用
2. **文件操作行为差异**：write/edit 工具感知权限——L1 写入 `file_changes(pending)` 不落盘，返回"等待确认"；L2 直接落盘 + 记录 `file_changes(applied)`（含 old/new 供撤销）
3. **L1 确认机制**：ReAct 循环检测到 pending 变更 → 发 `request_confirmation` 事件 → WebSocket 推给前端 → 用户确认/拒绝 → 确认则应用变更并恢复循环

**L3 自动 commit**：write/edit 工具执行成功后自动触发 git commit（框架层钩子），`git_actions` 表记录每次提交。

**数据表**（SQLite）：`sessions` / `messages` / `file_changes`（pending→confirmed/reverted，L1/L2 共用）/ `git_actions` / `events`

## 9. 功能清单（优先级）

**P0 核心**：ReAct 规范化循环；工具集五类；终止条件（模型完成判定/迭代上限/预算上限/用户停止）；错误处理（重试/工具异常回传/输出截断）

**P1 高分加分**：Web 流式可视化；token 估算/摘要压缩（context.py）；文件树 + diff 视图；评审工具（code_review，模型按需调用）；LLM 调用预算护栏；停止按钮；token 统计；会话持久化（SQLite）；**三级权限系统**（软修改确认/撤销/自动 git）

**P2 富余再做**：自动测试循环、git 工具增强、UI 打磨

## 10. 面试准备（设计决策辩护点）

- 为什么用 tool calling 原生接口而不是 prompt 解析 → 可控性、结构化、少幻觉
- 上下文为什么超长要摘要压缩而不是直接截断 → 信息保留 vs 成本
- 为什么终止条件要多层 → 模型判定 + 迭代上限 + 用户中断
- 工具出错为什么回传给模型 → 自我纠错闭环
- 为什么 ReAct 单框架（不叠加规划/子任务流程）→ 简洁可控、每步由真实工具结果驱动；附加流程会引入不可控环节（如重规划重复劳动）
- 为什么每步工具调用必须规范、只允许注册表中的工具 → 防止模型幻觉（编造工具/假完成），工具集扩展后能力自然增强
- 为什么评审工具化且按需调用 → 执行性验证已被 ReAct 内化；评审时机由模型自主决定（实现完成/测试通过后自查），框架只提供能力不规定时机
- 为什么工具/策略用注册表模式 → 扩展只加文件不改核心逻辑
- 为什么 agent/ 层不依赖 FastAPI → 可测试性、架构清晰
- 为什么三级权限（软修改/可撤销/自动 git）→ 权限 = 工具可见性 + 工具行为两层实现：L1/L2 直接过滤 git 工具（模型无法调用），写操作行为差异 + file_changes 表统一支撑确认与撤销
- 为什么 SQLite 而非 JSONL → 权限管理需要结构化查询（状态流转/按会话检索），SQLite 零依赖单文件
