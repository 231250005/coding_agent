# Coding Agent 后端接口文档

> 版本：v1.0 ｜ 基础 URL：`http://127.0.0.1:8000`
> 数据格式：JSON（UTF-8）｜ SSE 事件流用于运行中的实时输出

---

## 1. 通用约定

### 1.1 响应格式

所有 REST 接口统一返回：

```json
{
  "code": 0,          // 0 = 成功；非 0 = 业务错误
  "message": "ok",    // 成功为 "ok"，失败为错误说明
  "data": { }         // 业务数据（成功时存在）
}
```

| HTTP 状态码 | 含义 |
|---|---|
| 200 | 成功 |
| 400 | 参数错误（缺失/非法） |
| 404 | 资源不存在（会话/变更不存在） |
| 500 | 服务器内部错误 |

### 1.2 三级权限语义（核心）

| 权限 | 行为 |
|---|---|
| **L1（1）** | 每一步写/改文件时：**不落盘**，通过 SSE 推送 `request_confirmation`（内嵌对话流），用户确认后才保存并继续下一步；未确认前 agent 暂停 |
| **L2（2）** | 自动运行完所有步骤，保留每个新增/修改文件的前后对比（old/new），前端可对比、撤销 |
| **L3（3）** | L2 基础上，任务运行完成后如有 git 仓库自动提交（一次提交全部改动） |

- 权限是**每轮对话**的属性：每次 `chat` 请求携带 `permission_level`
- 文件变更记录**会话级累积**，同一会话先后用不同权限产生的变更互不干扰

### 1.3 会话说明

- 会话可**置顶**（is_pinned）与**重命名**（title），列表按"置顶优先 + 最近更新"排序
- 任务默认执行到完成（不提供中断接口）；agent 内置迭代上限与预算护栏兜底

---

## 2. 接口总览

| # | 方法 | 路径 | 功能 |
|---|---|---|---|
| 1 | POST | `/api/sessions` | 创建会话 |
| 2 | GET | `/api/sessions` | 会话列表（置顶优先 + 最近更新） |
| 3 | PUT | `/api/sessions/{id}/pin` | 切换置顶 |
| 4 | PUT | `/api/sessions/{id}/rename` | 重命名会话 |
| 5 | DELETE | `/api/sessions/{id}` | 删除会话 |
| 6 | POST | `/api/sessions/{id}/chat` | 发送任务（每轮带权限，触发 SSE 运行） |
| 7 | GET | `/api/sessions/{id}/events` | SSE 事件流（运行中实时输出） |
| 8 | GET | `/api/sessions/{id}/messages` | 对话历史 |
| 9 | GET | `/api/sessions/{id}/changes` | 文件变更列表（含前后对比） |
| 10 | POST | `/api/changes/{change_id}/confirm` | L1 确认应用变更 |
| 11 | POST | `/api/changes/{change_id}/reject` | L1 拒绝变更 |
| 12 | POST | `/api/changes/{change_id}/revert` | L2 撤销已应用变更 |

---

## 3. 接口详情

### 3.1 创建会话

`POST /api/sessions`

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| workspace | string | 是 | agent 工作目录（绝对路径） |
| title | string | 否 | 会话标题（缺省为空，可用首条任务自动填充） |

**请求示例**
```json
{
  "workspace": "D:/coding_agent/coding_agent",
  "title": "俄罗斯方块开发"
}
```

**响应示例（200）**
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "id": 1,
    "title": "俄罗斯方块开发",
    "workspace": "D:/coding_agent/coding_agent",
    "is_pinned": false,
    "created_at": "2026-08-28 22:00:00",
    "updated_at": "2026-08-28 22:00:00"
  }
}
```

---

### 3.2 会话列表

`GET /api/sessions`

**说明**：按"置顶优先 + 最近更新"排序返回。

**响应示例（200）**
```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "id": 2,
      "title": "待办事项工具",
      "workspace": "D:/coding_agent/coding_agent",
      "is_pinned": true,
      "updated_at": "2026-08-28 22:10:00"
    },
    {
      "id": 1,
      "title": "俄罗斯方块开发",
      "workspace": "D:/coding_agent/coding_agent",
      "is_pinned": false,
      "updated_at": "2026-08-28 22:05:00"
    }
  ]
}
```

---

### 3.3 切换置顶

`PUT /api/sessions/{id}/pin`

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| is_pinned | boolean | 是 | true = 置顶，false = 取消置顶 |

**请求示例**
```json
{ "is_pinned": true }
```

**响应示例（200）**
```json
{
  "code": 0,
  "message": "ok",
  "data": { "id": 1, "is_pinned": true }
}
```

**错误**：404 `{"code": 404, "message": "会话不存在：1"}`

---

### 3.4 重命名会话

`PUT /api/sessions/{id}/rename`

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| title | string | 是 | 新的会话标题 |

**请求示例**
```json
{ "title": "俄罗斯方块（pygame 版）" }
```

**响应示例（200）**
```json
{
  "code": 0,
  "message": "ok",
  "data": { "id": 1, "title": "俄罗斯方块（pygame 版）" }
}
```

**错误**：404 `{"code": 404, "message": "会话不存在：1"}`

---

### 3.5 删除会话

`DELETE /api/sessions/{id}`

**响应示例（200）**
```json
{ "code": 0, "message": "ok", "data": null }
```

---

### 3.6 发送任务（每轮对话，带权限）

`POST /api/sessions/{id}/chat`

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| content | string | 是 | 用户任务（如"帮我写一个俄罗斯方块小游戏"） |
| permission_level | int | 是 | 1 / 2 / 3（本轮任务使用的权限） |

**请求示例**
```json
{
  "content": "用 Python 写一个俄罗斯方块小游戏，保存为 tetris.py",
  "permission_level": 2
}
```

**响应示例（200）**（任务已开始，实时输出走 SSE）
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "session_id": 1,
    "task_id": 5,
    "permission_level": 2,
    "status": "running"
  }
}
```

**注意**：
- 同一会话同时只能运行一个任务；运行中再次 chat 返回 400 `{"message": "任务运行中"}`
- 本轮任务结束后，会话历史中的该条 user 消息会记录 `permission_level`（前端展示"L2 任务"）
- 任务默认执行到完成（agent 内置迭代上限与预算护栏兜底，无需中断）

---

### 3.7 SSE 事件流（运行中实时输出）

`GET /api/sessions/{id}/events`

**说明**：SSE 长连接，服务端持续推送事件；任务结束推送 `task_done` 后连接关闭。
客户端解析：每行 `data: <json>`，JSON 含 `type` 字段。

**事件类型一览**

| type | 说明 | 关键字段 |
|---|---|---|
| `task_start` | 任务开始 | task_id, permission_level |
| `thinking` | 模型思考过程 | content |
| `tool_call` | 工具调用开始 | name, args |
| `tool_result` | 工具结果 | name, ok, output |
| `usage` | 每轮 LLM 用量 | llm_calls, context_tokens, prompt_tokens, completion_tokens |
| `context_compressed` | 上下文已压缩 | released, truncated, summarized |
| `request_confirmation` | **L1 待确认**（agent 暂停） | change_id, file_path, operation, diff |
| `change_status` | 变更状态变化 | change_id, status |
| `message` | 任务最终回答 | content |
| `task_done` | 任务结束 | iterations, llm_calls |
| `error` | 错误 | content |

**事件示例（L1 任务片段）**
```
data: {"type":"thinking","content":"我来写一个猜数字游戏，先创建文件"}

data: {"type":"tool_call","name":"write_file","args":"{\"path\": \"game.py\", ...}"}

data: {"type":"tool_result","name":"write_file","ok":true,"output":"已暂存对 game.py 的修改（等待用户确认，change_id=1）"}

data: {"type":"request_confirmation","change_id":1,"file_path":"game.py","operation":"write","diff":"- (空文件)\n+ import random\n+ ..."}

data: {"type":"change_status","change_id":1,"status":"confirmed"}

data: {"type":"message","content":"游戏已完成，文件 game.py（50 行）..."}

data: {"type":"task_done","iterations":8,"llm_calls":10}
```

---

### 3.8 对话历史

`GET /api/sessions/{id}/messages`

**响应示例（200）**
```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "id": 1,
      "role": "user",
      "content": "用 Python 写一个俄罗斯方块小游戏",
      "permission_level": 2,
      "created_at": "2026-08-28 22:01:00"
    },
    {
      "id": 2,
      "role": "assistant",
      "content": "游戏已完成，文件 tetris.py（350 行），运行 python tetris.py 即可游玩",
      "permission_level": 2,
      "created_at": "2026-08-28 22:03:00"
    }
  ]
}
```

**注意**：只包含 user 任务与 assistant 最终回答（过程事件运行中经 SSE 展示，不落库）。

---

### 3.9 文件变更列表（权限核心）

`GET /api/sessions/{id}/changes?status=applied`

**查询参数**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| status | string | 否 | 过滤：pending / applied / rejected / reverted；缺省返回全部 |

**响应示例（200）**
```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "id": 3,
      "file_path": "tetris.py",
      "operation": "write",
      "status": "applied",
      "permission_level": 2,
      "old_content": "",
      "new_content": "import pygame\n...",
      "diff": "+ import pygame\n+ ...",       // 前后对比（unified diff 或简化预览）
      "created_at": "2026-08-28 22:02:00",
      "confirmed_at": null,
      "reverted_at": null
    }
  ]
}
```

**注意**：
- `old_content` / `new_content`：撤销与对比的数据基础（前端 diff 视图直接使用）
- L1 确认后的变更状态为 `applied`（确认已发生在对话流中），与 L2 一样可撤销

---

### 3.10 L1 确认应用

`POST /api/changes/{change_id}/confirm`

**说明**：L1 流程中，用户在对话流的确认卡片点击"确认"后调用；变更真正落盘，agent 继续下一步。

**响应示例（200）**
```json
{
  "code": 0,
  "message": "ok",
  "data": { "change_id": 1, "status": "applied" }
}
```

**错误**：
- 404：变更不存在
- 400：`{"code": 400, "message": "变更 1 当前状态为 confirmed，无法确认"}`（非 pending 状态）

---

### 3.11 L1 拒绝

`POST /api/changes/{change_id}/reject`

**说明**：用户点击"拒绝"，变更不落盘，agent 继续下一步（跳过该修改）。

**响应示例（200）**
```json
{
  "code": 0,
  "message": "ok",
  "data": { "change_id": 1, "status": "rejected" }
}
```

---

### 3.12 撤销已应用变更（L2 / 面板撤销）

`POST /api/changes/{change_id}/revert`

**说明**：把文件还原为该变更前的 old_content（仅对 `applied` 状态生效）。

**响应示例（200）**
```json
{
  "code": 0,
  "message": "ok",
  "data": { "change_id": 3, "status": "reverted" }
}
```

**错误**：400 `{"code": 400, "message": "变更 3 当前状态为 reverted，无法撤销"}`

---

### 3.13 目录浏览（前端工作区选择器）★ 待后端实现

`GET /api/fs/dirs?path=...`

**说明**：前端「选择工作目录」弹窗的目录树浏览接口。返回指定绝对路径下的**子目录列表**；`path` 缺省或为空时返回可选根（Windows 为盘符列表）。

**请求示例**
```
GET /api/fs/dirs?path=D:/coding_agent
```

**响应示例（200）**
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "path": "D:/coding_agent",
    "parent": "D:/",
    "dirs": [
      { "name": "coding_agent", "path": "D:/coding_agent/coding_agent" },
      { "name": "pi", "path": "D:/coding_agent/pi" }
    ]
  }
}
```

**根请求（path 缺省）**
```
GET /api/fs/dirs
```
- Windows：`data.dirs = [{ "name": "C:", "path": "C:/" }, { "name": "D:", "path": "D:/" }, ...]`，`parent = ""`
- Linux / macOS：`data.dirs = [{ "name": "/", "path": "/" }]`，`parent = ""`

**错误**
- 400：目录不存在或无法访问 → `{"code": 400, "message": "目录不存在或无法访问: D:/xxx"}`

**实现要求**
- 仅返回目录，不返回文件；目录名按名称排序
- 路径统一使用**正斜杠**（Windows 同样返回 `D:/xxx` 形式），与创建会话接口的 workspace 格式一致
- `parent` 为当前目录的上级（根目录时返回空字符串 `""`），前端据此渲染「返回上级」按钮
- 隐藏目录（以 `.` 开头或以 `$` 结尾）可省略，保持列表干净

### 3.14 按文件夹名解析绝对路径（前端原生选择器配套）★ 待后端实现

`GET /api/fs/resolve?name=<文件夹名>`

**说明**：前端工作区选择使用**系统原生文件夹对话框**（浏览器安全限制拿不到绝对路径，只能拿到文件夹名）。选完后前端调用本接口，后端在本机搜索同名文件夹并返回其**绝对路径候选列表**。

**请求示例**
```
GET /api/fs/resolve?name=coding_agent
```

**响应示例（200）**
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "name": "coding_agent",
    "matches": [
      "D:/coding_agent/coding_agent",
      "C:/Users/86139/projects/coding_agent"
    ]
  }
}
```

**搜索范围建议（Windows）**
- 所有盘符的根目录及其**一级子目录**（`D:/`、`D:/coding_agent` 等）
- 用户主目录（`C:/Users/<name>`）
- 名字匹配不区分大小写（Windows 语义）；隐藏/系统目录可跳过

**约定**
- 找不到：`matches` 返回空数组 `[]`（**不报错**），前端据此降级提示
- 最多返回 10 个候选，按路径字符串排序
- 路径统一使用**正斜杠**（`D:/xxx` 形式），与创建会话接口的 workspace 格式一致

**错误**
- 仅参数缺失时 400：`{"code": 400, "message": "缺少 name 参数"}`

---

## 4. 完整交互时序示例（L1 任务）

```
前端                                  后端
  │ POST /api/sessions                │ 创建会话
  │ ───────────────────────────────▶  │
  │ GET /api/sessions/{id}/events     │ SSE 连接建立
  │ ───────────────────────────────▶  │
  │ POST /api/sessions/{id}/chat      │
  │  {"content":"写一个游戏","permission_level":1}
  │ ───────────────────────────────▶  │ agent 开始运行
  │ ◀─── SSE: thinking                │
  │ ◀─── SSE: tool_call(write_file)   │
  │ ◀─── SSE: request_confirmation    │ ① agent 暂停等待
  │ POST /api/changes/1/confirm       │ ② 用户点"确认"
  │ ───────────────────────────────▶  │ ③ 落盘 + agent 继续
  │ ◀─── SSE: change_status(applied)  │
  │ ◀─── SSE: thinking / tool_call…   │
  │ ◀─── SSE: message / task_done     │ 任务完成
```

## 5. 与前端（Vue）的对接要点

| 前端组件 | 使用的接口 |
|---|---|
| 会话列表 / 新建（选权限） | `POST/GET/DELETE /api/sessions` |
| 聊天区（对话流 + 工具卡片 + 用量条） | `GET events`（SSE）+ `POST chat` |
| **L1 确认卡片**（内嵌对话流：diff + 确认/拒绝） | SSE `request_confirmation` + `POST confirm/reject` |
| **变更面板**（列表 + 对比 + 撤销按钮） | `GET changes` + `POST revert` |
| 历史对话（刷新后） | `GET messages` |

## 6. 前端对接示例（JavaScript / Vue 3）

### 6.1 总体时序（每次发消息前先连 SSE）

```javascript
// 1. 先连 SSE（保证不丢事件），再发任务 —— 顺序不能反
const es = connectEvents(sessionId, handlers);
await sendChat(sessionId, "写一个俄罗斯方块", 2);
```

### 6.2 SSE 连接与事件分发

```javascript
// EventSource 原生支持断线自动重连（浏览器内置），无需自己实现
function connectEvents(sessionId, handlers) {
  const es = new EventSource(`/api/sessions/${sessionId}/events`);
  es.onmessage = (event) => {
    const ev = JSON.parse(event.data);          // 每行 data: <json>
    const handler = handlers[ev.type];
    if (handler) handler(ev);
  };
  es.onerror = () => { /* 断线自动重连，无需处理 */ };
  return es;                                     // 组件卸载时调用 es.close()
}

// 事件处理器（按 type 分发到 UI 渲染）
const handlers = {
  thinking:  ev => appendMessage('thinking', ev.content),      // 灰色思考文字
  tool_call: ev => appendToolCard(ev.id, ev.name, ev.args),    // 工具卡片（折叠）
  tool_result: ev => updateToolCard(ev.id, ev.ok, ev.output),  // 更新卡片结果
  usage: ev => updateUsageBar(ev.context_tokens, ev.llm_calls),// 用量条
  request_confirmation: ev => showConfirmCard(ev),             // L1 确认卡片
  change_status: ev => updateChangeStatus(ev.change_id, ev.status),
  message: ev => appendMessage('assistant', ev.content),       // 最终回答
  task_done: ev => taskFinished(ev),                           // 任务结束
  error: ev => showError(ev.content),
};
```

### 6.3 发送任务（带权限）

```javascript
async function sendChat(sessionId, content, permissionLevel) {
  const r = await fetch(`/api/sessions/${sessionId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, permission_level: permissionLevel }),  // 1/2/3
  });
  const data = await r.json();
  if (data.code !== 0) showError(data.message);  // 如 "任务运行中"
}
```

### 6.4 L1 确认卡片（内嵌对话流）

```javascript
// SSE 收到 request_confirmation 时调用 —— 在对话流中插入确认卡片（不是弹窗）
function showConfirmCard(ev) {
  // ev = {type, change_id, file_path, operation, diff}
  const card = {
    file: ev.file_path,
    diff: ev.diff,                    // "- 旧行 / + 新行"，直接 <pre> 渲染
    onConfirm: async () => {
      await fetch(`/api/changes/${ev.change_id}/confirm`, { method: 'POST' });
      // 后端会落盘并让 agent 继续，后续事件继续从 SSE 流出
    },
    onReject: async () => {
      await fetch(`/api/changes/${ev.change_id}/reject`, { method: 'POST' });
    },
  };
  // pushConfirmCard(card)  —— 渲染到消息流末尾（agent 在等，界面可显示"等待确认"）
}
```

### 6.5 变更面板（L2 撤销 / diff 对比）

```javascript
// 打开会话时加载变更列表
async function loadChanges(sessionId) {
  const r = await fetch(`/api/sessions/${sessionId}/changes`);  // ?status=applied 可过滤
  const { data } = await r.json();          // data[].{id, file_path, operation, status, diff, ...}
  return data;
}

// 撤销按钮（仅 status === 'applied' 的变更）
async function revertChange(changeId) {
  const r = await fetch(`/api/changes/${changeId}/revert`, { method: 'POST' });
  const { data } = await r.json();          // {change_id, status: 'reverted'}
  refreshChanges();                          // 刷新面板（该行变 reverted 置灰）
}
```

### 6.6 刷新恢复（重开页面）

```javascript
// 1. 会话列表（置顶优先）
const sessions = (await (await fetch('/api/sessions')).json()).data;
// 2. 打开某会话 → 加载对话历史（user + assistant，含每轮权限）
const messages = (await (await fetch(`/api/sessions/${id}/messages`)).json()).data;
//    messages[].{role, content, permission_level} —— 直接渲染聊天区
// 3. 加载变更面板
const changes = await loadChanges(id);
// 4. 连接 SSE 等待下一次任务
```

### 6.7 Vue 组件划分建议

```
<SessionList>    会话列表 + 新建（权限选择器 L1/L2/L3）+ 置顶/重命名
<ChatWindow>     消息流（thinking/tool 卡片/确认卡片/回答）+ 输入框
<UsageBar>       上下文 token 进度条（usage 事件）+ 调用次数
<ConfirmCard>    L1 确认（diff 预览 + 确认/拒绝按钮）—— 消息流内嵌
<ChangePanel>    变更列表（el-table）+ 对比对话框 + 撤销按钮
```

> 示例为原生 fetch + EventSource，可直接照搬或用 axios / 封装成 composable。
