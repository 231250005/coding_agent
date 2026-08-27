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
| **8/28** | 代码 D2 | Agent 引擎核心：策略框架（PlanExecute 顶层 + ReAct 内核）；文件类工具；评审工具 |
| **8/29** | 代码 D3 | 探索类 + 执行类 + git 类工具；上下文管理（token 估算 + 摘要压缩）；错误处理；安全层 |
| **8/30** | 代码 D4 | FastAPI 后端：REST + WebSocket 流式事件、会话持久化、停止机制；晚间前后端联调 |
| **8/31** | 视频/面试 D5 | 用 agent 完成 2~3 个真实任务（视频素材）；录视频；写 README.txt |
| **9/1** | 视频/面试 D6 | 剪视频（≤2min、≤200MB）；打包提交；过一遍"设计决策辩护点" |
| **9/2** | 缓冲 | 截止 24:00 前最后的修改/补交；不再推送仓库 |

## 3. 总体架构

```
浏览器 (Vue 3 前端, 前后端分离)
   │  WebSocket(实时事件流)      REST(会话管理)
FastAPI 服务 ── server/
   ├── 会话持久化 (JSONL)
   └── Agent 引擎 ── agent/
        ├── llm.py        LLM 调用：OpenAI 兼容(通义千问) + 重试 + 流式
        ├── prompts.py    系统提示词：身份/工作流程/工具规范（独立维护）
        ├── context.py    上下文管理：token 估算 + 长对话摘要压缩
        ├── agent.py      编排器：策略循环、终止条件、错误恢复、事件回调
        ├── strategies/   PlanExecute 顶层 + ReAct 执行内核（可插拔）
        ├── tools/        工具注册表 + 本地实现（文件/探索/执行/git/评审）
        └── sandbox.py    安全层：工作目录锁定、超时、输出截断、危险命令防护
通义千问 API（百炼 dashscope compatible-mode, qwen3.7-flash）
```

技术选型理由（面试会问）：Python + FastAPI + openai SDK 快且稳；前端 Vue 3 + Vite 前后端分离，演示效果好。

## 4. 推理框架：Plan-and-Execute 顶层 + ReAct 执行内核

两级结构（任何任务都先规划，子任务按 mode 选择执行内核）：

```
用户任务
   ↓
PlanExecuteStrategy（顶层外壳，恒定）
   ├─ ① 规划：模型生成结构化 JSON 计划（步骤数随任务复杂度自适应：
   │        复杂任务子任务多、简单任务子任务少）
   ├─ ② 子任务循环：逐个执行 → 收集结果摘要 → 模型判断：
   │        a. 继续下一个子任务   b. 修改剩余计划（重规划）   c. 全部完成
   │      每个子任务交给内核执行：
   │        mode=react → ReAct 循环（写代码/改文件/探索/测试执行）
   │        mode=plain → 单次 LLM 回答（方案分析/总结，不需工具）
   └─ ③ 收尾评审：全部步骤完成后，强制以评审者视角对照任务需求自检
           → 发现问题回到对应子任务修复 → 复验 → 通过后才最终输出
```

- **规划 JSON 协议**：`{goal, steps: [{id, task, mode, output}]}`，mode 由模型规划时指定
- **子任务级上下文隔离**：每个子任务独立运行自己的消息历史，完成后只保留结果摘要进全局上下文——长任务不会上下文爆炸
- **评审工具化（关键设计）**：代码质量保障由 `code_review` 工具承担（评审者视角检查文件/git diff，输出问题清单与修复建议）；不设独立"反思框架"——执行性验证（跑测试看结果）已被 ReAct 循环内化，主观评审只需一个评审者视角工具
- **重规划**：子任务失败 → 重试（≤2 次）/ 重规划 / 放弃并向用户报告
- **终止条件（多层）**：步骤全完成（模型确认）/ 子任务数上限 / 单子任务迭代上限 / 全局迭代预算 / 用户手动停止
- 面试辩护点：ReAct 灵活但无目标感（长任务易迷失）；PlanExecute 锚定目标、复杂度自适应、计划可观测（演示核心）；评审工具化使"测试通过≠任务完成"有兜底。三者组合 = 非单一固定工作流

## 5. 工具集（对标 Claude Code，15 个工具，五类）

| 类别 | 工具 | 说明 |
|---|---|---|
| 文件操作 | `read_file` / `write_file` / `edit_file` | edit 用精确替换 + 上下文校验，失败可模糊匹配重试 |
| 代码库探索 | `list_dir` / `grep` / `glob` / `find_symbols` | find_symbols 用 AST 提取函数/类定义位置 |
| 执行与测试 | `run_command` / `run_python` / `run_tests` | 超时 + 输出截断 + 工作目录限定；run_tests 包装 pytest |
| Git 操作 | `git_status` / `git_diff` / `git_commit` / `git_log` | git CLI 子命令白名单 |
| **代码质量** | `code_review` | 评审者视角检查文件/git diff，输出问题清单与修复建议；由 PlanExecute 收尾评审调用，是"测试通过≠任务完成"的兜底 |

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
│   ├── agent.py                  # Agent 编排器：策略调用、终止条件、错误恢复、事件回调
│   ├── strategies/
│   │   ├── __init__.py           # StrategyRegistry（注册+自动选择）
│   │   ├── base.py               # AgentStrategy 抽象基类
│   │   ├── react.py              # ReAct 循环（子任务执行内核）
│   │   └── plan_execute.py       # 顶层外壳：规划→子任务调度→重规划→收尾评审
│   ├── tools/
│   │   ├── __init__.py           # ToolRegistry
│   │   ├── base.py               # Tool 抽象基类
│   │   ├── file_tools.py         # read/write/edit
│   │   ├── explore_tools.py      # list_dir/grep/glob/find_symbols
│   │   ├── exec_tools.py         # run_command/run_python/run_tests
│   │   ├── git_tools.py          # git_status/git_diff/git_commit/git_log
│   │   └── review_tools.py       # code_review：评审者视角检查文件/git diff（内部调 LLM）
│   └── sandbox.py                # 安全层
├── server/                       # FastAPI 服务层
│   ├── __init__.py
│   ├── main.py                   # 创建app、CORS、挂路由
│   ├── agent_runner.py           # asyncio 桥接：agent事件 → WebSocket 推送；停止控制
│   ├── session_store.py          # JSONL 会话持久化
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

**WebSocket** `ws://host/ws/{session_id}`：

- 客户端 → 服务端：`{"type":"chat","content":"..."}`、`{"type":"stop"}`、`{"type":"strategy","name":"plan_execute"}`
- 服务端 → 客户端：
  - `{"type":"thinking","content":"..."}` 模型思考过程
  - `{"type":"tool_call","id":1,"name":"run_command","args":{...}}`
  - `{"type":"tool_result","id":1,"name":"run_command","output":"...","ok":true}`
  - `{"type":"message","content":"最终回复"}` / `{"type":"done","stats":{...}}`（含 token 统计）
  - `{"type":"error","message":"..."}`

前端按事件渲染：thinking 灰色小字、tool_call/tool_result 折叠卡片、message 正文气泡、done 显示统计。

## 8. 功能清单（优先级）

**P0 核心**：PlanExecute 顶层 + ReAct 内核；工具集五类；终止条件（步骤完成/子任务上限/迭代上限/全局预算/用户停止）；错误处理（重试/工具异常回传/输出截断/重规划）

**P1 高分加分**：Web 流式可视化；子任务级上下文隔离 + token 估算/摘要压缩；文件树 + diff 视图；计划展示；收尾评审（code_review）；停止按钮；token 统计；会话持久化

**P2 富余再做**：自动测试循环、git 工具增强、UI 打磨

## 9. 面试准备（设计决策辩护点）

- 为什么用 tool calling 原生接口而不是 prompt 解析 → 可控性、结构化、少幻觉
- 上下文为什么超长要摘要压缩而不是直接截断 → 信息保留 vs 成本
- 为什么终止条件要多层 → 模型判定 + 迭代上限 + 用户中断
- 工具出错为什么回传给模型 → 自我纠错闭环
- 为什么 PlanExecute 顶层 + ReAct 内核（两层而非单循环）→ ReAct 灵活但无目标感；PlanExecute 锚定目标、复杂度自适应、计划可观测
- 为什么评审工具化而非独立反思框架 → 执行性验证（跑测试看结果）已被 ReAct 内化；主观评审只需一个评审者视角工具，框架最少化
- 为什么子任务结果用摘要进全局上下文 → 子任务级上下文隔离，长任务不爆炸
- 为什么工具/策略用注册表模式 → 扩展只加文件不改核心逻辑
- 为什么 agent/ 层不依赖 FastAPI → 可测试性、架构清晰
