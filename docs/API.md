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

DeepThink、教案、组卷、一键出卷、知识视频、AI 出题/评分和好题鉴别属于中型或重型 AI 任务。默认 `AGENT_RUNTIME=codex_runtime` 时，这些 agent 入口由本机 Codex runtime 非交互执行；普通导出、作文批改等非 agent 流程不受影响。自学资料生成默认不走 Codex runtime（见下文 `STUDY_MATERIALS_AGENT_RUNTIME` 说明）。任务启动事件会携带 `data.native_agentic=true` 与 `data.agent_run_spec`，用于描述原生 agentic 的 domain、goal、roles、tool_policy、budget、output_contract、resume_state 和 metadata。`agent_run_spec.metadata.runtime` 为 `codex_runtime`，并包含可忽略的 `codex_runtime_version`、`approval_policy` 与 `sandbox_mode`。客户端可忽略新增字段以保持兼容；任务进度仍以既有 SSE 事件继续输出。

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
- `POST /api/chat/{conversation_id}/cancel`

`POST /api/chat` 返回 SSE，常见事件类型包括 `stream_start`、`text_delta`、`thinking_delta`、`iteration`、`assistant`、`tool_start`、`tool_result`、`assistant_final`、`cancelled` 和 `error`。

补充契约（2026-07-26）：

- 请求体可选 `intent` 字段（如 `confirm_create_paper`）：结构化语义确认。提供时服务端据此确定性判定是否开放完整工具集（历史中需存在可解析的 `<EXAM_PAPER_PLAN>` 方案），完全绕过确认词子串匹配；未提供时沿用确认词匹配（带否定守卫，「不可以 / 不要开始」不再误命中）。
- `tool_start` / `tool_result` 携带 `execution_mode`（`parallel` | `sequential`），在执行前判定并显式声明同轮工具的执行方式。
- `tool_result` 携带服务端权威单工具耗时：`started_at` / `finished_at`（epoch 秒）与 `elapsed_ms`（毫秒）。
- `assistant_final` 达到最大轮数时带 `max_reached: true`。
- `POST /api/chat/{conversation_id}/cancel` 请求取消该会话进行中的生成，返回 `{success, accepted}`；`accepted=true` 仅表示取消信号已发出。实际停止以流内 `cancelled` 事件为准（协作式取消：正在执行的串行写类工具会先完整结束，未开始的工具不再执行；并行只读批会被中断）。取消确认后会落一条说明性 assistant 消息，随后流以 `[DONE]` 结束。

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
- `POST /api/question-library/gaokao/items/manual-import`
- `POST /api/question-library/gaokao/crawl`（SSE）
- `POST /api/tasks/question-library/gaokao-crawl`（规范长任务入口，返回 `taskId`）

`GET /api/question-library/items` 的 `area` 参数用于题库区域隔离：`general`（默认，排除高考真题）、
`gaokao`（只返回带结构化高考出处的题目）、`all`（仓储/管理用途）。高考真题通过
`POST /api/question-library/gaokao/items/manual-import` 批量写入；每题必须携带 `exam_year`、`region`、
`paper_name`，可附试卷版本、题号、原始链接、出处备注和核验状态。列表与详情返回
`library_area` 和 `gaokao_source`，不得仅凭题干或自由文本 `source` 猜测真题身份。

### 高考真题爬取

`POST /api/question-library/gaokao/crawl` 使用 SSE 返回 `step`、`item_saved`、`progress`、`done` 或
`error` 事件。只需要任务句柄时，使用 `POST /api/tasks/question-library/gaokao-crawl`；请求体相同。

```json
{
  "subject": "高中数学",
  "query": "新课标I卷",
  "edu_level": "高中",
  "exam_year": 2024,
  "region": "全国",
  "paper_name": "2024年普通高等学校招生全国统一考试新课标I卷数学",
  "paper_variant": "新课标I卷",
  "source_contains": "新课标I卷",
  "source_url": "https://example.edu/2024-math.pdf",
  "source_note": "依据正式发布试卷核验",
  "verified": true,
  "limit": 30,
  "max_pages": 3
}
```

`exam_year`、`region`、`paper_name` 与 `source_contains` 是必填项。爬虫查询同时携带年份和
`source_contains` 过滤，写库前还会再次检查题源返回的 `source + date`：必须同时包含指定题源标记
和四位年份。缺少出处或不匹配的题目不会进入真题区；全部不匹配时任务以
`gaokao_source_not_matched` 失败，并返回跳过计数。

### 高考真题手动导入

`POST /api/question-library/gaokao/items/manual-import` 接收 1–500 题并在同一事务中写入题干、用户题库
关系和结构化出处。兼容路径 `/api/question-library/gaokao/items/import` 仍可调用，但不再作为新客户端契约。

```json
{
  "items": [
    {
      "question_id": "gaokao-2024-math-1",
      "subject": "高中数学",
      "stem": "题干……",
      "answer": "A",
      "analysis": "解析……",
      "question_type": "单选题",
      "difficulty": "中等",
      "knowledge_points": ["集合"],
      "origin": "media",
      "source": {
        "exam_year": 2024,
        "region": "全国",
        "paper_name": "2024年普通高等学校招生全国统一考试新课标I卷数学",
        "paper_variant": "新课标I卷",
        "question_number": "1",
        "source_url": "https://example.edu/2024-math.pdf",
        "source_note": "依据正式发布试卷核验",
        "verified": true
      }
    }
  ]
}
```

成功响应为 `{"success": true, "upserted": 1, "question_ids": ["gaokao-2024-math-1"]}`。
缺少题干、学科或出处必填字段返回 422；重复题号或仓储级约束错误返回 400。

物理/化学真题的导入约束：题干、答案和解析中的公式必须使用 LaTeX 定界符
`\(...\)` 或 `\[...\]`（化学式可使用 `\ce{...}`）；表格必须使用 LaTeX 的
`array`/`matrix` 环境，不得把 GaokaoHub 的原始私有区字体或乱码直接写入。PDF 文字层无法可靠还原的
公式、结构式和表格，应写入 LaTeX 视觉来源提示，并附现有媒体登记的本地 SVG：
`/api/media/generated/{filename}.svg`（同时保留 `data-source-url` 和 `source_note`），标记为待人工核验。

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

- `POST /api/tasks/study-materials/generate`：canonical 任务提交，返回 `{success, taskId}`。
- `POST /api/tasks/study-materials/{task_id}/continue`：canonical 续作提交，返回 `{success, taskId}`。
- `POST /api/study-materials/generate`：兼容流式入口（POST 即 SSE）。
- `POST /api/study-materials/tasks/{task_id}/continue`：兼容流式续作（POST 即 SSE）。
- `GET /api/study-materials/tasks/{task_id}`：兼容状态视图。
- `GET /api/study-materials/tasks/{task_id}/stream?after_seq=0`：兼容续流/回放。
- `POST /api/study-materials/convert-markdown-to-latex`
- `POST /api/study-materials/convert-markdown-to-latex/stream`

两个 generate 入口共享同一个 options 规范化函数（`build_study_materials_options`）：`requirements` 截断到 600 字符，`max_points` 夹在 1-15，非法/非正值直接丢弃，两个入口行为完全一致。

两个 POST 即流接口在响应头携带 `X-Task-Id`（generate 为新任务 id，continue 为续作任务 id），客户端无需解析事件流即可拿到任务 id，随后用 GET 流重连；浏览器跨源读取依赖 CORS `expose_headers` 已暴露该头。

`convert-markdown-to-latex/stream` 使用与任务流一致的标准信封：每帧 `data: {taskId, seq, type, data}`（`taskId` 为本次转换的合成 id），事件类型包括 `status` / `progress` / `tool_call` / `tool_result` / `done` / `error`；工具执行期间按 `STUDY_MATERIALS_SSE_HEARTBEAT_S`（默认 4 秒）发送 `ping` 心跳（不推进 `seq`，`data` 为 `{status: "running", last_seq}`），流以 `data: [DONE]` 结束。

自学资料归档：

- `GET /api/study-archives?limit=&offset=&base_fingerprint=`
- `GET /api/study-archives/{archive_id}`
- `POST /api/study-archives`
- `POST /api/study-archives/{archive_id}/clone`

`GET /api/study-archives` 返回 `{items, count}`；`base_fingerprint` 按 subject+topic+requirements 的确定性指纹过滤同一主题的归档版本，空串/纯空白视为未传参。

自学资料生成默认（`STUDY_MATERIALS_AGENT_RUNTIME` 留空）走不依赖 Codex CLI 的 legacy AgentCore 路径：由后端 agent 依次执行规划、检索、逐知识点研究、写作、反思自检与导出，事件流为 `status` / `thinking` / `tool_call` / `tool_result` / `subagent_start` / `subagent_end` / `progress` / `done` / `error`，最终 Markdown 与下载链接在 `done.data.material` 中返回。

仅当显式设置 `STUDY_MATERIALS_AGENT_RUNTIME=codex_runtime` 时，自学资料才由 Codex 分阶段工作流执行：后端状态机依次执行规划、检索、写作、独立审查、修订和验收。Codex 子进程返回 `completed` 只表示当前阶段结束；只有当前 Markdown 满足 preset 对应的来源覆盖、内容覆盖，并且独立审查通过后，任务才会进入 `completed`。

该流程会追加以下 SSE 事件，同时保留原有事件兼容性：

- `workflow_stage`：`{stage, last_successful_stage, revision_attempts, research_attempts}`。
- `quality_report`：质量门报告 `{passed, failed_checks, per_knowledge_point, preset, quality_policy_version}`；`per_knowledge_point` 以知识点 id 为键，值为 `{passed, failed_checks, source_count, source_classes}`；验收阶段报告另含 `draft_hash`、`review_schema_version`、`dimension_count`、`lint_flags`。
- `research_retry_required`：检索质量门未过且仍有重试额度，`data` 为 `{point_ids, attempt, remaining_attempts}`。
- `revision_required`：审查问题和剩余修订次数 `{issues, remaining_attempts}`。
- `quality_degraded`：修订次数耗尽但已有成稿时的降级交付，`data` 为 `{issues, revision_attempts}`。
- `recovery_available`：可恢复失败的 `{code, stage, issues, recoverable}`；`code` 包括 `research_tool_outage`（检索工具不可用）、`quality_gate_not_met`（质量门未过）、`invalid_workflow_stage`、`workflow_iteration_limit`。
- `codex_fallback_to_legacy`：Codex 阶段结果缺失且允许回退时显式切换到内置生成流程，`data` 为 `{stage, detail, content}`。

任务流中还可能穿插运维告警事件：`persistence_warning`（快照/归档持久化失败，不再静默；`data` 为 `{target, error}`，`target` 为 `snapshot_load` / `snapshot_persist` / `archive_upsert`）和 `export_failed`（Markdown 导出重试 2 次仍失败，`data` 为 `{target: "markdown_export", error}`；导出失败不再拖垮任务，任务仍以 Markdown 结果完成）。

完成与降级契约：

- `done.data.material` 始终携带 `{topic, subject, markdown, iteration, passed, issues, error}` 与下载链接字段。
- 验收通过时 `material.passed=true` 且 `done.data.acceptance` 为验收记录；降级交付时 `done.data.degraded=true`、`material.passed=false`、`material.issues` 列出未通过项、`acceptance` 为空。
- 降级产物不写验收记录，归档永不被直接复用；同指纹再生成时仅作为候选草稿重新过质量门。

检索来源不足、检索重试额度耗尽，或修订次数耗尽且无成稿时，任务以可恢复的 `quality_gate_not_met` 失败结束并保留工作流快照。历史归档只有在草稿哈希、preset、质量策略版本、审查版本与 options 指纹均匹配、且未超过新鲜度预算（`STUDY_MATERIALS_ARCHIVE_MAX_AGE_S`，默认 14 天，0 表示不做时间过期）时才能直接复用，否则作为候选草稿重新检索和验收。

续作（continue）语义：

- 两个 continue 入口共用同一实现；`mode` 可选 `improve`（默认）、`deepen_research`、`fix_export`、`skip_export`、`resume_failed_stage`、`retry_search`、`replan_from_failure`。
- 未知 `mode` 返回 400，detail 以 `invalid_continue_mode` 为前缀并列出全部可选模式。
- 已完成/失败/取消/暂停的任务均可续作；仅 `running` 状态返回 409 `Task still running`。
- 磁盘快照只是缓存：快照缺失或过期时从 DB 任务行冷重建续作上下文（依次尝试结果载荷、同指纹归档、事件流回放），不再因快照过期返回 404；仅当 DB 行也不存在或无可重建内容时返回 404 `Task not found`，找到续作源但工作记忆为空时返回 400 `Task not resumable`。

兼容状态视图 `GET /api/study-materials/tasks/{task_id}` 返回 `{status, error, first_seq, last_seq, resumable, recovery_available, last_success_step, last_failed_step, last_success_stage, last_failed_stage, per_kp_state, search_summary_by_kp, ...}`。快照缺失时同样回退 DB 构建视图；无快照且无可重建内容时 `resumable=false`（`recovery_available` 仅在任务失败且 `last_failure.recoverable` 非 false 时为 true）。

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
