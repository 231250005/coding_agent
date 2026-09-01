# Coding Agent(编程智能体)

个人独立设计并实现的编程智能体:通过与大语言模型交互,自主读写文件、执行命令,完成编程任务——类似简化的 Claude Code / Codex / OpenCode。

**合规声明**:全部代码仅使用 `openai` 客户端库(题目允许的 API 客户端库,OpenAI 兼容模式),未使用任何 agent 框架/SDK(LangChain、AutoGen、OpenAI Agents SDK、Claude Agent SDK 等);所有工具均在**本地**执行(subprocess + 文件系统),不依赖服务端托管的代码执行或文件工具(Code Interpreter、Files API)。对话历史与上下文管理、工具定义与本地执行、模型输出解析、循环终止条件、错误处理等重要逻辑全部自行编写,对应模块见下文各节。

> 本文档覆盖 **Agent 引擎与后端服务**的详细架构与实现(前端为独立 Vue 3 工程,前后端分离,见前端仓库自己的 README)。

---

## 快速开始

需要 Python 3.11+ 与本地 MySQL(库不存在时后端会自动创建)。**前端图形可视化界面是最终使用方式**,步骤如下:

### 1. 配置 `.env`(项目根目录,凭据不入库,`.gitignore` 已排除)

```ini
# 通义千问 API Key(阿里云百炼, OpenAI 兼容模式;也可走系统环境变量)
DASHSCOPE_API_KEY=sk-xxxxx

# 模型名(可选,默认 qwen3.8-max)
QWEN_MODEL=qwen3.8-max

# MySQL(本地默认配置 localhost:3306 root 空密码时这几行可省略)
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=
```

### 2. 启动后端

```bash
python -m server.main     # http://127.0.0.1:8000,健康检查 GET /health;启动时自动建库建表
```

### 3. 启动前端(图形可视化界面)

前端是独立 Vue 3 工程(前后端分离),按前端仓库 README 启动:

```bash
npm install
npm run dev               # http://localhost:5173,/api 自动代理到 127.0.0.1:8000
```

浏览器打开后:选择工作目录 → 创建会话 → 发送任务。agent 的思考过程、工具调用与结果、上下文用量条、L1 确认卡片、文件变更面板(对比/撤销)全部实时渲染。

### CLI(开发调试用,非最终形态)

`python cli.py` —— 不依赖前端与后端,直接在本机运行 agent(启动时选择三级权限),用于开发期调试核心逻辑、录制演示素材;`python smoke_test.py` 验证模型连通性。

---

## 总体架构

```
浏览器 (Vue 3 前端, 独立工程)
   │  SSE 事件流(运行过程实时推送)        REST(会话/变更/工作区管理)
FastAPI 后端 ── server/
   ├── routes/        REST + SSE 接口层
   ├── agent_runner   SessionRunner:事件队列 / L1 确认挂起 / 变更持久化 / 跨任务摘要
   └── db + tables    MySQL:自动建库建表 + 表结构自动同步
        │
Agent 引擎 ── agent/(纯逻辑,不依赖 FastAPI,CLI 可直接复用)
   ├── agent.py        编排器:组装 LLM/工具/策略/权限,预算护栏
   ├── strategies/     ReAct 策略(规范化 tool-calling 循环)
   ├── tools/          工具注册表 + 16 个本地工具(文件/探索/执行/测试/git/评审)
   ├── context.py      上下文管理:token 估算 + usage 锚定 + 两级压缩
   ├── permissions.py  三级权限:工具可见性过滤 + 文件变更记录/确认/撤销
   ├── sandbox.py      安全层:工作区隔离、路径防穿越、输出截断、危险命令拦截
   ├── llm.py          OpenAI 兼容客户端:tool calling / 重试 / 流式
   ├── prompts.py      系统提示词(独立维护)
   └── events.py       统一事件模型(CLI 打印与 SSE 推送共用)
通义千问 API(OpenAI 兼容模式)
```

分层原则:**`agent/` 纯逻辑无框架依赖**(单测好写、架构清晰);**`server/` 只做 IO、SSE 与持久化**;策略与工具用注册表模式,扩展只加文件不改核心逻辑。

---

## Agent 引擎(agent/)

### 1. 主循环:ReAct 策略(`strategies/react.py`)

全局统一 ReAct 单框架(不叠加规划/子任务等附加流程),每步由真实工具结果驱动:

```
1. messages + 工具 schema 发给 LLM
2. 模型返回 tool_calls → 逐个本地执行 → 结果回填为 tool 消息 → 回到 1
3. 模型返回无 tool_calls 的回复 → 即任务最终回复 → 结束
```

**终止条件(多层)**,见 `react.py:53` 循环与 `agent.py:112` 预算护栏:

| 层 | 机制 | 位置 |
|---|---|---|
| 模型完成判定 | 无 tool_calls 的回复即最终回复 | `react.py:186` |
| 最大迭代 | 默认 20 轮(防模型死循环) | `react.py:19` |
| LLM 调用预算 | 单任务 >60 次强制中止(环境变量 `MAX_LLM_CALLS` 可覆盖,防失控烧额度) | `agent.py:112` |

**输出解析与错误处理**(模型输出解析是本题自写重点):

- **`finish_reason == "length"` 截断防护**(`react.py:99`):模型响应达到输出上限时 tool_calls 参数可能残缺,一律判失败回填错误信息,**不执行**(截断的参数执行会带来错误副作用);
- **参数 JSON 解析失败**(`react.py:124`):不静默执行,把"参数不合法,请重新发起完整调用"作为工具结果回给模型,引导自我纠错;
- **未知工具名**:走注册表返回失败结果(不崩溃),附可用工具列表;
- **工具执行异常**:`ToolRegistry.execute` 统一捕获,转成失败结果回给模型(`tools/__init__.py:36`),形成"出错 → 看到错误 → 修复 → 复跑"的自我纠错闭环。

**评审去重与测试轮次控制**(`react.py:202`):`code_review` 按**内容是否变化**去重而非按次数——指定文件时,仅当"文件自上次评审后内容未变化"才被阻断(每次写入/修改后都允许评审一次,同一文件的同一内容不重复评审);不指定 path 时按工作区改动集合(git diff / 最近修改文件快照,与评审工具收集逻辑一致)去重。`run_tests` 保持每任务最多 2 轮,防止"测试→修改→再测试"死循环。

**工具执行在线程池**(`react.py:156`):工具(run_command 等)是同步 subprocess,直接调用会阻塞事件循环、导致任务运行期间 HTTP 请求(如 L1 确认)全部排队;放入 `asyncio.to_thread` 后事件循环保持响应。

### 2. 编排器(`agent.py`)

- **依赖注入组装**:LLM 客户端、工具注册表、策略、权限均可注入(便于测试与替换);`code_review`/`generate_test` 等依赖 LLM 的工具在 `build_default_registry(llm)` 时注入客户端;
- **LLM 预算护栏**(`agent.py:109`):`call_llm` 统一计数,超限抛异常终止任务;
- **三级权限注入**(`agent.py:100`):给 write_file / read_file / edit_file / generate_test 注入 PermissionManager,工具感知权限;
- **AGENTS.md 分级注入**(`agent.py:70`):工作区 `AGENTS.md` 存在时——≤4000 字符全文注入系统提示词(零截断);超长则 `run()` 时异步调 LLM 摘要(线程池执行不阻塞事件循环,失败降级不注入);
- **L3 自动提交**(`agent.py:143`):任务完成时 `finalize_commit` 自动 git commit(仅 L3 且为 git 仓库且有改动,否则静默跳过),提交信息 `agent 任务完成：{任务前 50 字}`;
- **兜底错误处理**(`agent.py:174`):策略运行异常时返回错误信息而非崩溃,并发出 error/done 事件。

### 3. LLM 客户端(`llm.py`)

- 仅使用 `chat.completions` 接口(合规),OpenAI 兼容模式连百炼 `dashscope.aliyuncs.com/compatible-mode/v1`;
- **重试分类**(`llm.py:21`):只重试连接错误、429 限流、5xx 服务端错误;400/401 等不重试(重试只会白等)。指数退避 1s/2s/4s,最多 3 次;
- 单次生成上限 `MAX_TOKENS=16384`,超长输出仍有截断兜底(见策略层 finish_reason 处理)。

### 4. 上下文管理(`context.py`)

题目要求的"对话历史与上下文管理"核心实现:

**Token 估算**(`context.py:33`):无依赖近似估算——CJK 字符 1 字符 ≈ 1 token,其他 4 字符 ≈ 1 token,每消息 +4 元数据开销。

**usage 锚定校准**(`context.py:73`):每次 LLM 响应记录真实的 `usage.prompt_tokens` 作为锚点,之后的增量消息用估算补齐——压缩阈值判断从"纯估算"变为"真实锚点 + 增量估算",触发时机更准。

**两级压缩**(`context.py:103`,默认阈值 100000,环境变量 `MAX_CONTEXT_TOKENS` 可覆盖):

1. **裁剪最旧的 tool 结果**(零成本,`context.py:133`):把可裁剪区(跳过 system 与最近 10 条)中最旧的 tool 消息内容替换为占位符,**保留 tool_call_id 与角色结构**(模型依赖 id 对应关系);
2. **LLM 摘要最早一段对话**(`context.py:151`):把最早一半消息压缩为一条 `[历史摘要]` 消息,保留任务目标/关键动作/产出文件/当前状态。

**保护规则与安全切割点**:

- system 消息永不压缩;最近 `keep_recent=10` 条消息永不压缩;
- **安全切割点**(`context.py:166`):摘要区不得以 tool 消息结束——不劈开"assistant 调用 → tool 结果"的因果对,模型不会看到孤立结果;
- 摘要失败不阻塞主流程(降级返回原消息);压缩统计通过 `context_compressed` 事件推送(释放 token 数)。

### 5. 工具系统(`tools/`)

**注册表模式**(`tools/__init__.py`):每个工具 = JSON schema 定义 + 本地实现,`ToolRegistry` 统一注册、导出 schema、执行。新增工具 = 加一个类 + `build_default_registry` 注册一行。

**16 个工具,五类**:

| 类别 | 工具 | 关键实现 |
|---|---|---|
| 文件操作 | `read_file` / `write_file` / `edit_file` | 带行号读取、`start_line`/`end_line` 分段;edit 用精确子串替换 + 整行容错匹配(行尾空白/\r\n 差异)两层策略,匹配不唯一时报行号并给出可行动建议 |
| 代码库探索 | `list_dir` / `grep` / `glob` / `find_symbols` | find_symbols 用 Python AST 提取函数/类定义位置(语法树级,零误报);grep 自动跳过 .git/缓存/依赖目录 |
| 执行与测试 | `run_command` / `run_python` / `run_tests` / `generate_test` | run_python 不走 shell 无注入风险;run_tests 包装 pytest 返回**结构化结果**(通过/失败/错误数 + 失败用例明细);generate_test 内部调 LLM 生成 pytest 样例,与 run_tests 构成"生产→执行"闭环;`keep` 参数区分交付物测试(默认,走变更记录)与临时验证测试(`keep=false` 直接写盘、不入变更记录) |
| Git 操作 | `git_status` / `git_diff` / `git_commit` / `git_log` | git CLI 子命令白名单,非仓库时返回友好错误供模型判断 |
| 代码质量 | `code_review` | **内建编译器级语法检查**(ast.parse,机械可靠)+ 评审者视角审查(功能正确性 > 需求符合性 > 质量 > 风格),语法错误列严重问题;是"测试通过≠任务完成"的质量兜底,由模型按需自主调用 |

**参数运行时校验**(`tools/base.py:27`):schema 的 required 缺失时直接返回可行动错误(指明缺哪个参数、期望类型与含义),不进入工具执行。

**输出截断统一治理**(`sandbox.py`):`truncate_with_meta` 返回 `(截断后文本, 是否截断, 总字符数)` 元数据——文件内容类**保留头部**(默认 8000 字符),命令输出类**保留尾部**(错误信息 Traceback/FAILED 在末尾,保留尾部模型才能"看到错误");`read_file` 超过 500 行截断并提示缩小 end_line。截断只限制进入上下文的结果,不修改原文件。

### 6. 三级权限系统(`permissions.py`)

核心差异化功能,**两层实现机制**:

1. **工具可见性过滤**(`permissions.py:224`):L1/L2 不暴露 git 四件套——`tool_schemas()` 过滤后的 schema 直接发给模型,**模型无法调用不存在的工具**(比提示词约束更硬);
2. **写操作行为差异**(`file_tools.py`):write/edit/generate_test 感知权限——L1 写操作进 pending 队列**不落盘**,返回 `pending_change` 并暂停循环等待用户确认;L2 直接落盘 + 记录 old/new 内容(可撤销);L3 同 L2 + 任务完成自动 commit。`generate_test` 的 `keep=false` 模式(交付型临时验证测试)例外:直接写盘、不进入变更记录。

| 能力 | L1(软修改) | L2(可撤销) | L3(自动 git) |
|---|---|---|---|
| 写/改文件 | 进 pending 队列,用户确认才落盘;agent 暂停等待 | 直接修改,记录变更可撤销 | 同 L2 + 任务完成自动提交 |
| git 工具 | 不提供 | 不提供 | 提供 |
| 撤销 | 确认前可拒绝(不落盘) | 一键撤销(old_content 还原) | 同 L2 |

细节:

- **同文件多次修改合并**(`permissions.py:96`):同一会话内多次写同一文件合并为一条记录,old_content 保留最早修改前内容、new_content 更新为最新——撤销能还原到最早状态;
- **L1 虚拟内容读取**(`file_tools.py:114`):L1 下 read_file 读取 pending 变更的"虚拟内容"(待确认的新内容),模型感知一致;
- **变更状态机**:pending → applied(确认)/ rejected(拒绝,不落盘);applied → reverted(撤销);
- 内存记录通过 `change_sink` 钩子与数据库 `file_changes` 表对齐(Web 场景),持久化失败不阻塞 agent 运行。

### 7. 安全层(`sandbox.py`)

- **工作区隔离**:所有工具限定在**当前任务的工作区**内(Web 模式为会话指定的工作目录,CLI 默认 `WORKSPACE_DIR`);`safe_join` 把相对路径 resolve 后校验 `is_relative_to(workspace)`,**路径穿越(../)直接拒绝**,由工具层转成失败结果回给模型;
- **任务级工作区隔离**(`sandbox.py:22`):`contextvars.ContextVar` 按 asyncio 任务隔离工作区,Web 场景多会话并发互不干扰;
- **不可逆命令黑名单**(`exec_tools.py:16`):`rm -rf`、`rd/s`、`del/s`、通配符批量删除、`for` 循环动态删除、`find . -delete`、`git clean -f`、`git reset --hard`、磁盘级操作(format/mkfs/diskpart)——**任何权限模式下直接拒绝**,返回可行动错误引导改用安全方式(指定具体文件路径删除);
- **命令超时与进程树终止**(`exec_tools.py:130`):Windows 下 `shell=True` 只 kill 外层 cmd 会残留子进程,超时用 `taskkill /F /T` 杀整个进程树;
- **后台启动**(`exec_tools.py:107`):`background=true` 独立进程组启动(GUI 窗口常驻);`new_console=true` 用 `cmd /c start` 弹出可见命令行窗口供用户交互;
- 子进程强制 `PYTHONIOENCODING=utf-8` 并按 UTF-8 解码(避免 Windows GBK 乱码),`errors="replace"` 非 Python 程序输出 GBK 时不崩溃。

### 8. 事件模型(`events.py`)

CLI 打印与 WebSocket/SSE 推送共用一套事件结构:`thinking`(思考过程)/ `tool_call` / `tool_result` / `message`(最终回复)/ `error` / `done`(迭代与调用统计)/ `request_confirmation`(L1 待确认)/ `context_compressed`(压缩统计)/ `usage`(真实 token 用量)。

### 9. 系统提示词(`prompts.py`)

独立维护,定义身份/工作流程/工具使用规范。核心约束:

- **工具规范性**:只能调用注册表中真实存在的工具;禁止编造工具、禁止声称完成工具集不支持的动作;"只有工具真实返回了结果,才算完成该动作"——防止模型幻觉(编造工具/假完成);
- **工作流程**:写完代码必须 code_review(最多 2 轮),评审通过后严禁再改 [建议] 级问题(防止无限打磨);测试型任务才生成测试文件,交付型任务不生成;仅用户明确要求【运行/打开】时才 background 启动程序;
- **大文件分段写入引导**:预计超过 8000 字符的文件先写骨架、再 edit_file 分段补全(避免单次输出超长被截断导致参数不完整);
- **AGENTS.md 分级注入**(≤4000 字符全文 / 超长 LLM 摘要,见编排器一节)。

### 10. 运行日志(`agent/logger.py`)

每次任务(多轮对话)的完整事件过程按日期归档写入根目录 `log/YYYY-MM-DD.log`(一天一个文件,跨天自动切换;`.gitignore` 已排除 `log/`):

- 每个任务一个日志块:任务内容、会话 ID / 权限级别 / 工作区 / 历史轮数等元信息,加上逐步事件(思考、工具调用参数与结果、L1 确认、上下文压缩、token 用量、最终回复、结束统计);
- 挂接在 `Agent.emit()` 事件流上,CLI 与 Web 两种模式自动全覆盖,无需额外接线;Web 场景多会话并发写入线程安全;
- 同一会话的多轮对话凭日志块内的"会话ID"串联追溯;
- 配置:`AGENT_LOG=0` 关闭(默认开启),`AGENT_LOG_DIR` 可改目录;日志写失败静默降级,不影响 agent 运行。

---

## 后端服务(server/)

### 1. 分层结构

```
server/
├── main.py           FastAPI 入口:lifespan 建库建表、统一错误格式、挂路由、/health
├── db.py             数据库连接管理:自动建库(utf8mb4)、engine/session、初始化编排
├── schema.py         表结构自动同步(以 Model 为唯一事实来源,幂等)
├── agent_runner.py   SessionRunner:SSE 事件队列 / L1 确认 / 跨任务摘要 / 变更持久化
├── tables/           每表一文件的 SQLAlchemy Model:sessions / messages / file_changes
└── routes/           sessions(会话 CRUD)/ chat(任务+SSE+历史)/ changes(变更管理)/ fs(工作区浏览)
```

### 2. 会话运行器(`agent_runner.py`)

每个会话一个 `SessionRunner`,运行期常驻:

- **事件队列 + SSE**(`chat.py:71`):`GET /api/sessions/{id}/events` 返回 `StreamingResponse` 长连接,跨任务持续推送(前端断开时由 CancelledError 停止);**订阅者治理**——无订阅者时事件直接丢弃,防止任务后台运行时队列无人消费持续累积内存;
- **L1 确认挂起 Future**(`agent_runner.py:180`):`confirm_callback` 创建 asyncio Future 挂起 agent,由 REST confirm/reject 接口 `resolve_confirm` 唤醒;**300 秒超时未确认自动拒绝**,agent 不会无限挂起;
- **权限每轮切换**(`agent_runner.py:92`):复用会话级 PermissionManager 仅更新 level,变更记录**会话级累积**(同一会话先后用不同权限产生的变更互不干扰);
- **跨任务摘要(多轮记忆)**(`agent_runner.py:140`):消息只落库 user 任务 + assistant 最终回答;未摘要轮次超过 10 轮(SUMMARY_TRIGGER_ROUNDS)时,调 LLM 把旧摘要与新增轮次**增量合并**为新摘要(role='summary' 入库)。下次任务加载 = 最新摘要 + 其后所有轮次 → 多轮对话零硬截断;
- **变更持久化钩子**(`agent_runner.py:205`):change_sink 把内存变更同步写 `file_changes` 表,数据库 id 与内存 id 对齐(前端拿到的 change_id 即数据库 id,confirm/revert 直接可用)。

### 3. REST 接口一览(15 个,详见 `server/API.md`)

| 方法 | 路径 | 功能 |
|---|---|---|
| POST / GET | `/api/sessions` | 创建 / 列表(置顶优先 + 最近更新) |
| PUT / DELETE | `/api/sessions/{id}/pin` · `/rename` · `DELETE` | 置顶 / 重命名 / 删除(级联清理消息与变更) |
| POST | `/api/sessions/{id}/chat` | 发送任务(每轮带 permission_level;运行中再次发送返回 400) |
| GET | `/api/sessions/{id}/events` | SSE 事件流(实时推送运行过程) |
| GET | `/api/sessions/{id}/messages` | 对话历史(user + assistant,含每轮权限) |
| GET | `/api/sessions/{id}/changes` | 文件变更列表(含前后对比,status 可过滤) |
| POST | `/api/changes/{id}/confirm` · `/reject` · `/revert` | L1 确认落盘 / L1 拒绝 / L2 撤销 |
| POST | `/api/sessions/{id}/changes/confirm-all` | 保存全部(确认全部变更并清空记录) |
| GET | `/api/fs/dirs` · `/api/fs/resolve` | 目录浏览 / 按文件夹名解析绝对路径(前端工作区选择器) |

统一响应格式 `{code, message, data}`;统一错误处理(`main.py:42`):detail 为 dict 时(如撤销冲突 409)展开字段,前端可识别冲突。

### 4. 数据库(MySQL + SQLAlchemy)

- **自动建库**(`db.py:60`):`coding_agent` 库不存在时自动创建(utf8mb4);凭据全部走环境变量;
- **表结构自动同步**(`schema.py`):启动时以 Model 定义为唯一事实来源——新表自动创建、缺失列自动 `ALTER TABLE ADD COLUMN`、缺失索引自动创建、已声明废弃的列自动删除,**只增不减**且幂等,无需版本记录表;
- **三张表**:

| 表 | 说明 |
|---|---|
| `sessions` | 会话:id、title、workspace、is_pinned、created/updated_at |
| `messages` | 对话历史:role(user/assistant/summary)、content、**permission_level**(前端展示"这一轮用的什么权限")、created_at |
| `file_changes` | 三级权限核心数据:session_id、file_path、operation、**old_content/new_content**(撤销与对比的数据基础)、status(pending/applied)、permission_level、confirmed_at/reverted_at |

选择 MySQL 而非 JSONL 的理由:权限管理需要结构化查询(状态流转、按会话检索、同文件合并);ORM + 自动同步让表结构演进零成本。

### 5. 变更管理的关键设计

- **revert 冲突检测**(`changes.py:139`):撤销前对比「文件当前内容」与「该变更的 new_content」——一致才允许撤销;不一致(文件可能被其他会话/人手改过)**不做任何修改**,返回 409 + conflict 识别信息(当前内容/期望内容各前 500 字符),前端据此提示;
- **reject/revert 后记录删除**(`file_changes.py:117`):被拒绝/撤销的变更彻底移除,不再出现在变更列表;
- **confirm-all**:用户认可当前全部变更后删除记录(撤销能力随之放弃),前端"保存全部"按钮;
- 删除会话级联清理 messages 与 file_changes(避免孤儿数据)。

### 6. 工作区浏览(`routes/fs.py`)

`/api/fs/dirs` 返回子目录列表 + 上级目录(供"返回上级"按钮),Windows 返回盘符列表作为根,隐藏目录省略;`/api/fs/resolve` 解决浏览器原生文件夹对话框拿不到绝对路径的问题——按文件夹名在本机搜索绝对路径候选(所有盘符根 + 一级子目录 + 用户主目录,最多 10 个)。

---

## 关键设计决策(答辩要点)

| 决策 | 理由 |
|---|---|
| 用原生 tool calling 而非 prompt 解析工具调用 | 可控性、结构化、少幻觉 |
| ReAct 单框架,不叠加规划/子任务流程 | 简洁可控,每步由真实工具结果驱动;附加流程引入不可控环节 |
| 工具调用必须规范、只允许注册表中的工具 | 防止模型幻觉(编造工具/假完成);L1/L2 过滤 git 工具是比提示词更硬的约束 |
| 上下文超长用"裁剪工具结果 + LLM 摘要"而非硬截断 | 零成本释放 token + 保留任务主线;usage 锚定让触发时机更准 |
| 多层终止条件(模型判定/迭代上限/预算护栏) | 模型判定正常退出,上限兜底死循环,预算护栏防失控烧额度 |
| 工具出错回传给模型 | 自我纠错闭环("看到错误 → 修复 → 复跑") |
| 评审工具化且按需调用 | 执行性验证(跑测试)已被 ReAct 内化;评审时机由模型自主决定,框架只提供能力 |
| 注册表模式(工具/策略) | 扩展只加文件不改核心逻辑 |
| agent/ 层不依赖 FastAPI | 可测试性、架构清晰,CLI 可独立运行 |
| 三级权限 = 工具可见性 + 工具行为两层 | L1/L2 直接过滤 git 工具;写操作行为差异 + file_changes 表统一支撑确认/撤销/冲突检测 |
| 工具执行放线程池 | 任务运行期间事件循环保持响应,L1 确认等 HTTP 请求不被阻塞 |
| 命令错误输出保留尾部 | 错误信息(Traceback/FAILED)在末尾,保留尾部模型才能看到错误 |

---

## 测试

`tests/` 目录下的检查脚本(真实模型调用不是前置条件,可独立运行):

```bash
python tests/p0_check.py             # 核心逻辑冒烟
python tests/react_loop_check.py     # ReAct 循环
python tests/permissions_check.py    # 三级权限
python tests/context_check.py        # 上下文压缩
python tests/tools_check.py          # 工具集
python tests/api_e2e_check.py        # 后端接口 E2E
```

`smoke_test.py` 验证 LLM 连通性(需 API key)。

---

## 项目结构

```
├── agent/                  # 核心引擎(纯逻辑,不依赖 FastAPI)
│   ├── agent.py            # 编排器:组装/预算护栏/权限注入/AGENTS.md 摘要/L3 自动提交
│   ├── llm.py              # OpenAI 兼容客户端:重试分类 + 指数退避
│   ├── prompts.py          # 系统提示词(工具规范性/工作流程)
│   ├── context.py          # 上下文管理:token 估算 + usage 锚定 + 两级压缩
│   ├── events.py           # 统一事件模型
│   ├── logger.py           # 运行日志:按日期归档 log/YYYY-MM-DD.log
│   ├── permissions.py      # 三级权限:可见性过滤 + 变更记录/确认/撤销
│   ├── sandbox.py          # 安全层:工作区隔离/路径防穿越/输出截断
│   ├── strategies/         # ReAct 策略(策略注册表)
│   └── tools/              # 工具注册表 + 16 个本地工具(文件/探索/执行/测试/git/评审)
├── server/                 # FastAPI 服务层
│   ├── main.py             # 应用入口:建库建表/统一错误/挂路由/健康检查
│   ├── db.py               # MySQL 连接管理 + 自动建库
│   ├── schema.py           # 表结构自动同步
│   ├── agent_runner.py     # SessionRunner:SSE/确认挂起/跨任务摘要/变更持久化
│   ├── routes/             # sessions / chat / changes / fs
│   ├── tables/             # sessions / messages / file_changes(每表一文件)
│   └── API.md              # 后端接口文档(含 L1 交互时序)
├── cli.py                  # 命令行入口(调试/演示)
├── smoke_test.py           # LLM 连通性冒烟测试
├── log/                    # 运行日志(按日期自动生成,不入库)
└── tests/                  # 核心逻辑检查脚本
```

前端为独立 Vue 3 工程(前后端分离),对接本仓库 `server/API.md` 中的接口,详见前端仓库 README。
