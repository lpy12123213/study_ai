# API 总览

本文说明 Study AI 当前 HTTP API 的使用口径：认证、错误格式、SSE、统一任务中心和主要资源接口。字段级细节以启动后的 OpenAPI 页面为准：`http://localhost:8000/docs`。

产品功能使用说明见 `USER_GUIDE.md`。接口开发和变更应同时遵循 `DEVELOPMENT.md` 与 `ARCHITECTURE.md`。

## 基础信息

- 本地后端：`http://localhost:8000`
- JSON 请求：`Content-Type: application/json`
- 本地默认用户：未提供 `Authorization` 时，后端使用内置本地管理员用户。
- 流式接口：`text/event-stream`，事件体通常为 `data: {...}\n\n`

## API 约束

- 所有业务接口必须挂载在 `/api` 下。
- 受保护资源必须通过 `require_auth` 或等价鉴权机制保护。
- 长任务提交、状态、事件回放和控制必须以 `/api/tasks` 为 canonical 入口。
- 新接口不得只返回自由文本错误；错误应包含稳定 code 或可稳定映射的 detail。
- 兼容接口可以保留，但不得作为新能力的主入口。

## 认证

当前本地应用不再暴露登录接口。业务接口仍通过 `require_auth` 获取用户上下文；没有 bearer token
或 token 已失效时，后端会回退到内置本地管理员用户。

常用认证接口：

- `GET /api/auth/me`
- `POST /api/auth/register`
- `POST /api/auth/change-password`
- `POST /api/auth/logout`
- `GET /api/auth/users`

## 错误格式

后端会尽量返回稳定的错误字段，同时保留 FastAPI 的 `detail` 兼容字段：

```json
{
  "code": "validation_error",
  "message": "validation_error",
  "details": {},
  "request_id": "req_xxx",
  "detail": {},
  "error": {
    "code": "validation_error",
    "message": "validation_error",
    "request_id": "req_xxx"
  }
}
```

排障时优先记录 `code`、`message` 和 `request_id`。

## 版本与兼容

当前 API 未引入 URL 版本号。兼容性通过以下方式维护：

- 保留必要旧字段，例如 `detail` 和 `error` envelope。
- 新字段应向后兼容添加。
- 删除字段、改名或改变语义前必须同步前端、测试和文档。
- 长任务事件类型和 `seq` 语义视为稳定契约。

## 路由分组

路由汇总入口是 `backend/api/router.py`，当前按领域聚合：

- system：健康检查、配置、指标、搜索历史、仪表盘。
- integrations：题源筛选项、学科、知识树。
- workspace：对话、画布、媒体、试卷、模板、归档、错题、批注、反馈。
- auth：本地用户上下文、用户、密码。
- generation：DeepThink、教案、自学资料、题库、AI 出题、学习计划、知识视频。
- tasks：统一长任务、导出任务、任务回放。

## 健康检查

- `GET /api/health/live`：进程存活。
- `GET /api/health/ready`：依赖与初始化状态。
- `GET /api/health`：综合健康状态。
- `GET /api/metrics`：Prometheus 指标。
- `GET /api/config`：脱敏后的运行配置摘要。

## Canonical 长任务

`/api/tasks` 是所有新增长任务的统一入口。客户端提交任务后拿到 `taskId`，再通过状态接口和 SSE 流回放进度。

提交入口：

- `POST /api/tasks/deepthink`
- `POST /api/tasks/lesson-plans/generate`
- `POST /api/tasks/papers/compose`
- `POST /api/tasks/papers/generate-full`
- `POST /api/tasks/knowledge-videos/generate`
- `POST /api/tasks/study-materials/generate`
- `POST /api/tasks/study-materials/{task_id}/continue`
- `POST /api/tasks/question-library/crawl`
- `POST /api/tasks/question-library/generate`
- `POST /api/tasks/question-library/score`
- `POST /api/tasks/question-evaluate/evaluate`
- `POST /api/tasks/export/papers/{paper_id}`
- `POST /api/tasks/export/study-archives/{archive_id}`

DeepThink、教案、组卷、一键出卷、知识视频、自学资料、AI 出题/评分和好题鉴别属于中型或重型 AI 任务。默认 `AGENT_RUNTIME=codex_runtime` 时，这些 agent 入口由本机 Codex runtime 非交互执行；普通导出、作文批改等非 agent 流程不受影响。任务启动事件会携带 `data.native_agentic=true` 与 `data.agent_run_spec`，用于描述原生 agentic 的 domain、goal、roles、tool_policy、budget、output_contract、resume_state 和 metadata。`agent_run_spec.metadata.runtime` 为 `codex_runtime`，并包含可忽略的 `codex_runtime_version`、`approval_policy` 与 `sandbox_mode`。客户端可忽略新增字段以保持兼容；任务进度仍以既有 SSE 事件继续输出。

状态与控制：

- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `GET /api/tasks/{task_id}/stream?after_seq=0`
- `POST /api/tasks/{task_id}/pause`
- `POST /api/tasks/{task_id}/resume`
- `POST /api/tasks/{task_id}/cancel`
- `POST /api/tasks/{task_id}/retry`

SSE 事件包含递增 `seq`。客户端应保存最后处理过的 `seq`，重连时传入 `after_seq`，避免重复拼接。

任务事件最低要求：

- `taskId`：任务 ID。
- `seq`：当前任务内单调递增。
- `type`：事件类型。
- `data`：结构化事件数据。
- `created_at`：事件时间，使用 ISO 风格字符串。

## 对话

- `GET /api/conversations`
- `POST /api/conversations`
- `PATCH /api/conversations/{conv_id}`
- `DELETE /api/conversations/{conv_id}`
- `GET /api/conversations/{conv_id}/messages`
- `POST /api/conversations/{conv_id}/fork`
- `POST /api/chat`

`POST /api/chat` 返回 SSE，常见事件类型包括 `stream_start`、`text_delta`、`tool_start`、`tool_result`、`assistant_final` 和 `error`。

## 试卷与导出

- `GET /api/papers`
- `POST /api/papers`
- `GET /api/papers/{paper_id}`
- `DELETE /api/papers/{paper_id}`
- `GET /api/papers/{paper_id}/download-link`
- `POST /api/papers/{paper_id}/export`
- `POST /api/papers/compose`
- `POST /api/papers/generate-full`
- `GET /api/exports/files`
- `POST /api/exports/zip`

`/api/tasks/export/papers/{paper_id}` 是任务化导出入口；旧的直连导出接口仍可用于兼容。

导出格式：

- `markdown`
- `latex`
- `pdf`
- `docx`

PDF 依赖本机 LaTeX 引擎，DOCX 优先使用 Pandoc。

## 题源、筛选与蓝图

- `POST /api/available-filters`
- `POST /api/compose-blueprint`
- `GET /api/subjects`
- `GET /api/subjects/{subject_code}/filters`
- `GET /api/subjects/{subject_code}/knowledge-tree`

筛选与蓝图字段见 `SEARCH_FILTERS_AND_BLUEPRINTS.md`。

## OpenAI Function Calling 适配器

主服务通过 integrations domain 暴露适配器路由：

- `POST /api/integrations/openai/search-by-keyword`
- `POST /api/integrations/openai/search-by-knowledge`
- `POST /api/integrations/openai/filter-questions`
- `GET /api/integrations/openai/question-info/{question_id}`
- `POST /api/integrations/openai/create-paper`
- `POST /api/integrations/openai/available-filters`
- `POST /api/integrations/openai/compose-blueprint`
- `GET /api/integrations/openai/papers`
- `GET /api/integrations/openai/papers/{paper_id}`

`backend.core.openai_adapter` 仅保留为独立启动兼容入口，复用同一个 integrations router。

## 本地题库与 AI 出题

资源接口：

- `GET /api/question-library/items`
- `GET /api/question-library/items/{question_id}`
- `POST /api/question-library/items/{question_id}/hide`
- `POST /api/question-library/items/{question_id}/unhide`
- `POST /api/question-library/items/{question_id}/star`
- `POST /api/question-library/items/{question_id}/unstar`
- `POST /api/question-library/items/bulk-delete`
- `POST /api/question-library/items/{question_id}/export-to-basket`

Preview 与 session：

- `GET /api/question-library/previews/{preview_id}`
- `GET /api/question-library/previews/latest/pending`
- `POST /api/question-library/previews/{preview_id}/commit`
- `POST /api/question-library/previews/{preview_id}/discard`
- `POST /api/question-library/previews/{preview_id}/regenerate-section`
- `GET /api/question-library/sessions`
- `GET /api/question-library/sessions/{session_id}`
- `POST /api/question-library/sessions/{session_id}/stop`
- `POST /api/question-library/sessions/{session_id}/archive`

题库的抓取、生成、评分优先使用 `/api/tasks/question-library/*`。

AI 出题任务的 `progress` SSE 事件会携带结构化阶段字段：`stage_id`、`stage_label`、`stage_group`、`stage_order`、`description`、`summary`、`stats` 和可选 `sample`。旧字段 `phase`、`label`、`progress` 保持兼容。

## 自学资料与教案

自学资料：

- `POST /api/tasks/study-materials/generate`
- `POST /api/tasks/study-materials/{task_id}/continue`
- `POST /api/study-materials/convert-markdown-to-latex`
- `POST /api/study-materials/convert-markdown-to-latex/stream`

当 `AGENT_RUNTIME=codex_runtime` 时，自学资料由后端状态机依次执行规划、检索、写作、独立审查、修订和验收。Codex 子进程返回 `completed` 只表示当前阶段结束；只有当前 Markdown 满足 preset 对应的来源覆盖、内容覆盖，并且独立审查通过后，任务才会进入 `completed`。

该流程会追加以下 SSE 事件，同时保留原有事件兼容性：

- `workflow_stage`：当前阶段、最近成功阶段和修订次数。
- `quality_report`：逐知识点的来源覆盖与未通过检查。
- `revision_required`：审查问题和剩余修订次数。
- `recovery_available`：可恢复失败的阶段、错误码和问题列表。

若来源不足、审查持续不通过或修订次数耗尽，任务以可恢复的 `quality_gate_not_met` 失败结束，并保留工作流快照；它不会以部分 Markdown 冒充成功。历史归档只有在草稿哈希、preset、质量策略版本和审查版本均匹配时才能直接复用，否则作为候选草稿重新检索和验收。

教案：

- `GET /api/lesson-plans`
- `POST /api/lesson-plans`
- `GET /api/lesson-plans/{plan_id}`
- `DELETE /api/lesson-plans/{plan_id}`
- `POST /api/tasks/lesson-plans/generate`
- `POST /api/lesson-plans/export`

## 画布、媒体与工作区

画布：

- `GET /api/canvas/boards`
- `POST /api/canvas/boards`
- `GET /api/canvas/boards/{board_id}`
- `PUT /api/canvas/boards/{board_id}`
- `GET /api/canvas/boards/{board_id}/versions`
- `POST /api/canvas/boards/{board_id}/versions`
- `POST /api/canvas/boards/{board_id}/pick-questions`
- `GET /api/canvas/questions/{question_id}/render`

媒体：

- `GET /api/media/generated/{filename}`
- `GET /api/media/proxy?url=...`

媒体代理只允许图片内容类型，远程 SVG 默认被拒绝。

## 兼容接口说明

仓库中仍保留少量领域专属的任务或 SSE 接口，例如 `/api/study-materials/tasks/{task_id}/stream`、`/api/question-library/tasks/{task_id}/stream`。这些接口用于兼容现有前端或旧调用方；新能力应接入 `/api/tasks`。

## 变更规则

- 新增长任务必须写入 `/api/tasks`。
- 新增公开接口需要同步本文。
- 返回字段如果被前端依赖，应补充前端类型和测试。
- 错误码应稳定，避免只返回无法处理的自由文本。
