# API文档

## 基础信息

- 基础URL: `http://localhost:8000`
- 内容类型: `application/json`

## 通用错误格式（重要）

后端错误通常返回 JSON（HTTP 4xx/5xx），并尽量遵循统一字段：

```json
{
  "code": "validation_error",
  "message": "validation_error",
  "details": { "field": "reason" },
  "request_id": "req_abc123",
  "detail": { "field": "reason" },
  "error": {
    "code": "validation_error",
    "message": "validation_error",
    "request_id": "req_abc123"
  }
}
```

说明：
- `code/message/request_id` 用于前端展示与排障定位
- 为兼容历史实现，会保留 `detail`（FastAPI 默认字段）与 `error` envelope

常见 `code`（节选，见后端 `backend/api/error_codes.py`）：
- `invalid_or_expired_token`
- `validation_error`
- `paper_create_failed`
- `paper_export_failed`
- `convert_markdown_to_latex_failed`
- `filters_failed`

## 认证（JWT）

Web UI 的「对话」功能需要登录后才能使用。登录成功后，后端返回 JWT token；调用受保护接口时需要携带：

```
Authorization: Bearer <access_token>
```

### 登录

**POST** `/api/auth/login`

**请求体：**
```json
{
  "username": "admin",
  "password": "admin123"
}
```

**响应示例：**
```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "user_id": "1",
  "username": "admin",
  "role": "admin"
}
```

### 获取当前用户

**GET** `/api/auth/me`

**响应示例：**
```json
{
  "user_id": "1",
  "username": "admin",
  "role": "admin"
}
```

### 需要登录的接口（常用）

- `POST /api/chat`（SSE 流式对话）
- `GET /api/conversations` / `POST /api/conversations` / `DELETE /api/conversations/{id}` 等（对话历史）

## 端点列表

### 健康检查

**GET** `/api/health`

返回服务健康状态

**响应示例：**
```json
{
  "status": "healthy",
  "service": "exam-paper-assistant"
}
```

---

## 自学资料（Study Materials）

自学资料生成使用 SSE 流式输出，并支持“任务化 + 刷新续流”：

- 首次发起：`POST /api/study-materials/generate`
- 刷新/断线后续流：`GET /api/study-materials/tasks/{task_id}/stream?after_seq=...`
- 查询任务状态：`GET /api/study-materials/tasks/{task_id}`

### 启动生成（SSE）

**POST** `/api/study-materials/generate`

**请求体：**
```json
{
  "query": "微积分：极限与连续",
  "subject": "高中数学"
}
```

**返回：** `text/event-stream`（每条消息是 `data: {...}\n\n` 的 JSON）

**事件要点：**
- 首个事件为 `task_started`，`data.task_id` 用于续流
- 后续事件包含 `seq`（单调递增），用于断线后从 `after_seq` 继续
- 长时间无新事件时会有 `ping` 心跳，避免“无输出假死”

### 续流/重连（SSE）

**GET** `/api/study-materials/tasks/{task_id}/stream?after_seq={last_seq}`

> `after_seq` 传“客户端已处理的最后一个 seq”，后端只会推送更新的事件，避免重复拼接内容。

---

## 媒体（Media）

用于前端渲染图片/示意图（例如自学资料生成的 SVG）。

### 本地生成媒体（示意图）

**GET** `/api/media/generated/{filename}`

- `filename` 为 `sha256hex.ext`（例如 `b1946ac92492d2347c6235b4d2611184a1d5e0....svg`）
- 当前支持：`.svg/.png/.jpg/.jpeg/.gif/.webp/.bmp/.md/.tex/.pdf/.zip/.docx/.mp4/.srt/.json/.py`

### 远程媒体代理（缓存）

**GET** `/api/media/proxy?url={remote_url}`

将远程图片拉取到后端并缓存于 `.local/media/`，用于稳定渲染（避免跨域/链接失效等问题）。

---

## 知识视频（Knowledge Videos）

知识视频生成通过统一任务接口提交，并通过任务流读取进度：

- 提交：`POST /api/tasks/knowledge-videos/generate`
- 状态：`GET /api/tasks/{task_id}`
- 事件流：`GET /api/tasks/{task_id}/stream?after_seq=0`

**请求体：**
```json
{
  "topic": "导数的几何意义",
  "subject": "高中数学",
  "source_archive_id": 1,
  "duration_seconds": 30,
  "style": "clean",
  "quality": "low",
  "requirements": "突出切线斜率与瞬时变化率"
}
```

完成后 `result` 会包含：

- `video_url` / `video_filename`
- `subtitle_url` / `subtitle_filename`
- `script_url` / `script_filename`
- `metadata_url` / `metadata_filename`

运行依赖：后端需要 Docker，并预先构建 `docker/manim-sandbox` 镜像；默认镜像名为
`study-ai/manim-sandbox:latest`。

---

### 创建试卷

**POST** `/api/papers`

创建新试卷并保存题目编号

**请求体：**
```json
{
  "paper_name": "高一数学期末试卷",
  "question_ids": ["12345", "12346", "12347"]
}
```

**响应示例：**
```json
{
  "success": true,
  "paper_id": 1,
  "message": "试卷 '高一数学期末试卷' 创建成功"
}
```

---

### 获取试卷详情

**GET** `/api/papers/{paper_id}`

获取指定试卷的详细信息

**路径参数：**
- `paper_id` (integer): 试卷ID

**响应示例：**
```json
{
  "paper_id": 1,
  "paper_name": "高一数学期末试卷",
  "created_at": "2025-01-15T10:30:00",
  "questions": [
    {
      "question_id": "12345",
      "order": 1,
      "type": "选择题",
      "difficulty": "中等",
      "knowledge_point": "函数",
      "source_url": "https://zujuan.xkw.com/q/12345"
    }
  ]
}
```

---

### 获取试卷列表

**GET** `/api/papers`

获取所有试卷列表

**查询参数：**
- `limit` (integer, 可选): 返回数量限制，默认50

**响应示例：**
```json
[
  {
    "paper_id": 1,
    "paper_name": "高一数学期末试卷",
    "created_at": "2025-01-15T10:30:00",
    "question_count": 15
  }
]
```

---

### 删除试卷

**DELETE** `/api/papers/{paper_id}`

删除指定试卷

**路径参数：**
- `paper_id` (integer): 试卷ID

**响应示例：**
```json
{
  "success": true,
  "message": "试卷删除成功"
}
```

---

### 获取下载链接

**GET** `/api/papers/{paper_id}/download-link`

生成组卷网题目查看链接

**路径参数：**
- `paper_id` (integer): 试卷ID

**响应示例：**
```json
{
  "success": true,
  "paper_name": "高一数学期末试卷",
  "question_count": 15,
  "question_ids": ["12345", "12346"],
  "question_links": [
    "https://zujuan.xkw.com/q/12345",
    "https://zujuan.xkw.com/q/12346"
  ],
  "instructions": [
    "1. 点击下方链接访问组卷网查看题目",
    "2. 在组卷网网站上登录您的账号",
    "3. 将喜欢的题目加入组卷网的题库",
    "4. 使用组卷网的正规下载功能下载试卷"
  ]
}
```

---

### 导出试卷（Markdown / LaTeX / PDF / DOCX）

**POST** `/api/papers/{paper_id}/export`

将试卷导出为本地文件（写入后端的 `.local/media/generated/`）并返回下载 URL。

**请求体：**
```json
{
  "format": "pdf",
  "includeStem": true,
  "includeAnswer": true,
  "includeAnalysis": true
}
```

字段说明：
- `format`: `markdown` | `latex` | `pdf` | `docx`
- `includeStem/includeAnswer/includeAnalysis`: 控制导出内容是否包含题干/答案/解析

**响应示例（PDF）：**
```json
{
  "success": true,
  "format": "pdf",
  "pdf_url": "/api/media/generated/xxx.pdf",
  "pdf_filename": "试卷.pdf",
  "tex_url": "/api/media/generated/xxx.tex",
  "tex_filename": "试卷.tex",
  "log": "xelatex 编译日志（截断）"
}
```

说明：
- `format=pdf` 时会同时返回 `pdf_url` 和 `tex_url`（便于排查编译问题）
- 当环境没有 LaTeX 引擎时，可能返回 `latex_engine_not_found`

---

## 配图与生成媒体（TikZ/Asymptote）

题库配图与教学示意图属于 best-effort 能力：主流程不会因为配图不可用而失败。

- 默认后端：TikZ/PGF（编译为 `SVG`）
- 受控回退：当 TikZ 不适用或不可用时，回退到 Asymptote（编译为 `SVG`）
- 生成文件落盘到后端 `.local/media/generated/`，并通过 `/api/media/generated/{filename}` 提供访问
- 运行环境缺少工具链时，可能出现（或被跳过）：`tikz_tools_missing` / `asy_tools_missing`

## 一键组卷（AI 生成整张试卷，SSE）

**POST** `/api/papers/generate-full`

根据学科/主题/总分/时长/难度分布，自动规划结构并调用 AI 填充整张试卷，返回 SSE 事件流。

**请求体：**
```json
{
  "taskId": "optional-client-id",
  "subject": "高中数学",
  "topic": "导数与函数",
  "paperName": "导数综合卷（可选）",
  "totalPoints": 150,
  "timeLimit": 120,
  "difficultyDistribution": { "easy": 0.3, "medium": 0.5, "hard": 0.2 },
  "useStudyArchive": true,
  "streamReasoning": false
}
```

**响应：** `text/event-stream`

事件形态（每条为 `data: {...}\n\n` JSON）：
- `type=progress`: `{ "type": "progress", "progress": 10.0 }`
- `type=step`: `{ "type": "step", "step": { "id": "...", "title": "...", "status": "running|completed|failed", ... } }`
- `type=result`: `{ "type": "result", "result": { "paper_id": 1, "paper_name": "...", "question_count": 20, ... } }`
- `type=error`: `{ "type": "error", "error": "paper_save_failed", "data": { "detail": "..." } }`

---

### 记录搜索历史

**POST** `/api/search-history`

记录题目搜索历史

**请求体：**
```json
{
  "search_type": "keyword",
  "search_query": "函数",
  "result_count": 20
}
```

**响应示例：**
```json
{
  "success": true,
  "message": "搜索历史已记录"
}
```

---

## 对话与画布聊天 API

前端“画布式对话”使用以下接口实现：

### 获取对话列表

**GET** `/api/conversations`

**查询参数：**
- `limit` (integer, 可选): 返回数量限制，默认50

**响应示例：**
```json
[
  {
    "id": 1,
    "title": "新对话",
    "created_at": "2025-01-01T10:00:00",
    "updated_at": "2025-01-01T10:05:00"
  }
]
```

---

### 创建对话

**POST** `/api/conversations`

**请求体：**
```json
{
  "title": "新对话"
}
```

**响应示例：**
```json
{
  "id": 123,
  "title": "新对话"
}
```

---

### 更新对话标题

**PATCH** `/api/conversations/{conv_id}`

**请求体：**
```json
{
  "title": "函数专题 - 分支A"
}
```

**响应示例：**
```json
{
  "success": true,
  "conversation": {
    "id": 123,
    "title": "函数专题 - 分支A",
    "created_at": "2025-01-01T10:00:00",
    "updated_at": "2025-01-01T10:06:00"
  }
}
```

---

### 删除对话

**DELETE** `/api/conversations/{conv_id}`

**响应示例：**
```json
{ "success": true }
```

---

### 获取对话消息

**GET** `/api/conversations/{conv_id}/messages`

返回对话信息与该对话所有消息（按时间升序）。

**响应示例：**
```json
{
  "conversation": {
    "id": 123,
    "title": "新对话",
    "created_at": "2025-01-01T10:00:00",
    "updated_at": "2025-01-01T10:05:00"
  },
  "messages": [
    {
      "id": 1,
      "role": "user",
      "content": "帮我组一份函数卷",
      "tool_calls": null,
      "tool_call_id": null,
      "created_at": "2025-01-01T10:00:01"
    }
  ]
}
```

---

### 分叉对话（创建分支）

**POST** `/api/conversations/{conv_id}/fork`

从父对话的某条消息开始分叉，创建一个新对话，并复制父对话从开头到 `message_id`（包含该条消息）的消息前缀。

**请求体：**
```json
{
  "message_id": 12,
  "title": "原对话 - 分支"
}
```

**响应示例：**
```json
{
  "id": 456,
  "title": "原对话 - 分支",
  "parent_conversation_id": 123,
  "forked_from_message_id": 12,
  "copied_message_count": 9,
  "copied_visible_message_count": 6
}
```

说明：
- `copied_visible_message_count` 用于前端画布隐藏“复制的前缀”（避免重复显示），只显示分叉点之后的新消息。

---

### 发送消息（SSE 流式）

**POST** `/api/chat`

**请求体：**
```json
{
  "conversation_id": 123,
  "message": "再来 10 道中等难度选择题",
  "subject": "高中数学"
}
```

**响应：** `text/event-stream`

后端会持续返回形如 `data: {...}\n\n` 的事件流，直到 `data: [DONE]` 结束。每个 `data` 都是 JSON，至少包含 `type` 字段。

常见 `type`：
- `iteration`：多轮工具编排的轮次提示
- `stream_start`：开始输出文本增量
- `text_delta`：模型输出的增量文本
- `assistant`：某一轮 assistant 的聚合信息（可能包含 `tool_calls`）
- `tool_start` / `tool_result`：工具调用过程与结果
- `assistant_final`：本次回复结束（用于落库）
- `error`：错误信息

---

## MCP工具API

以下工具通过MCP协议提供给AI使用：

### search_questions_by_keyword

通过关键词搜索题目

**参数：**
- `keyword` (string, 必需): 搜索关键词
- `subject` (string, 可选): 学科
- `limit` (integer, 可选): 结果数量限制，默认20

**返回：**
```json
{
  "success": true,
  "keyword": "函数",
  "count": 20,
  "questions": [
    {
      "question_id": "12345",
      "question_type": "选择题",
      "difficulty": "中等",
      "knowledge_point": "函数的性质",
      "source_url": "https://zujuan.xkw.com/q/12345"
    }
  ]
}
```

---

### search_questions_by_knowledge

通过知识点搜索题目

**参数：**
- `knowledge_point` (string, 必需): 知识点名称
- `subject` (string, 必需): 学科
- `limit` (integer, 可选): 结果数量限制，默认20

**返回：**
```json
{
  "success": true,
  "knowledge_point": "三角函数",
  "subject": "数学",
  "count": 20,
  "questions": [...]
}
```

---

### filter_questions

根据条件筛选题目

**参数：**
- `question_ids` (array, 必需): 题目编号列表
- `difficulty` (string, 可选): 难度（简单/中等/困难）
- `question_type` (string, 可选): 题型
- `limit` (integer, 可选): 结果数量限制，默认10

**返回：**
```json
{
  "success": true,
  "count": 10,
  "questions": [...]
}
```

---

### get_question_info

获取题目元数据信息

**参数：**
- `question_id` (string, 必需): 题目编号

**返回：**
```json
{
  "success": true,
  "question_id": "12345",
  "question_type": "选择题",
  "difficulty": "中等",
  "knowledge_points": "函数的性质",
  "year": "2024",
  "source": "某某市期末考试",
  "url": "https://zujuan.xkw.com/q/12345"
}
```

---

### create_paper

创建试卷

**参数：**
- `paper_name` (string, 必需): 试卷名称
- `question_ids` (array, 必需): 题目编号列表

**返回：**
```json
{
  "success": true,
  "paper_id": 1,
  "message": "试卷 '高一数学期末试卷' 创建成功"
}
```

---

## 错误响应

所有API端点在出错时返回统一格式：

```json
{
  "detail": "错误描述信息"
}
```

常见HTTP状态码：
- `200` - 成功
- `400` - 请求参数错误
- `404` - 资源不存在
- `500` - 服务器内部错误

## 使用示例

### Python

```python
import httpx

# 创建试卷
async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://localhost:8000/api/papers",
        json={
            "paper_name": "测试试卷",
            "question_ids": ["12345", "12346"]
        }
    )
    print(response.json())
```

### JavaScript

```javascript
// 获取试卷列表
fetch('http://localhost:8000/api/papers')
  .then(response => response.json())
  .then(data => console.log(data));
```

### curl

```bash
# 创建试卷
curl -X POST http://localhost:8000/api/papers \
  -H "Content-Type: application/json" \
  -d '{"paper_name":"测试试卷","question_ids":["12345","12346"]}'
```

## 新增：题目筛选与组卷蓝图

已新增/扩展以下 MCP 能力（用于 AI 侧调用）：

- `get_available_filters`：获取当前学科可用筛选项（年级/教材版本/题型等）
- `compose_paper_blueprint`：按“组卷蓝图”批量检索并组装题目 ID 列表

并在搜索工具中新增支持：

- `learn_grade/learn_grade_id`（年级硬过滤）
- `textbook_version`（教材版本/题库分类）
- `elective_mode/exclude_elective/elective_keywords`（选修过滤三态）
- `dedup_by_stem`（题干去重）
- `min_quality_score`（质量阈值；避免明显缺内容/图片占比过高的题）

详情与示例见：`docs/SEARCH_FILTERS_AND_BLUEPRINTS.md`
