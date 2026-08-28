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
