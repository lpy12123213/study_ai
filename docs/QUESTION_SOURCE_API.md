# 当前后端 API 文档：任务接口、题库生成与题源边界

本文只描述当前仓库已经实现的后端 API 和内部接口边界。

口径约束：
- 以 `backend/api/router.py`、各 router 文件、schema 和 runner 实现为准。
- 未来 provider 扩展设计不在本文承诺范围内。
- `/api/tasks` 是长任务的 canonical 入口；直连 SSE 入口属于现存接口，不应作为新能力的主接入面。

## 1. 范围

本文聚焦三类内容：

1. 长任务 API：题库抓取、AI 出题、题库评分，以及通用任务状态/流式回放。
2. 题库资源 API：本地题库条目、preview、session、导出题篮。
3. 题源相关集成边界：crawler filters、blueprint、subjects、canvas 中直接依赖 crawler 的入口，以及内部 crawler/provider 契约。

不包含：
- 大学搜题酱、菁优网等未来题源接入方案
- 未发布的 `provider` 选择参数或多 provider 协议
- 站点级抓取细节、登录方案、逆向策略

## 2. API 总览

基础前缀：
- 所有对外接口统一挂在 `/api`
- 顶层聚合入口见 `backend/api/router.py`

与题源/题库直接相关的路由分组：

### Canonical 长任务

- `POST /api/tasks/question-library/crawl`
- `POST /api/tasks/question-library/generate`
- `POST /api/tasks/question-library/score`
- `GET /api/tasks/{task_id}`
- `GET /api/tasks/{task_id}/stream`
- `POST /api/tasks/{task_id}/pause`
- `POST /api/tasks/{task_id}/resume`
- `POST /api/tasks/{task_id}/cancel`
- `POST /api/tasks/{task_id}/retry`

### Question Library 资源接口

- `GET /api/question-library/items`
- `GET /api/question-library/items/{question_id}`
- `POST /api/question-library/items/{question_id}/hide`
- `POST /api/question-library/items/{question_id}/unhide`
- `POST /api/question-library/items/{question_id}/star`
- `POST /api/question-library/items/{question_id}/unstar`
- `POST /api/question-library/items/bulk-delete`
- `POST /api/question-library/items/{question_id}/export-to-basket`
- `GET /api/question-library/tasks/{task_id}`
- `GET /api/question-library/tasks/{task_id}/stream`
- `GET /api/question-library/previews/{preview_id}`
- `GET /api/question-library/previews/latest/pending`
- `GET /api/question-library/sessions`
- `GET /api/question-library/sessions/{session_id}`
- `POST /api/question-library/sessions/{session_id}/stop`
- `POST /api/question-library/sessions/{session_id}/archive`
- `POST /api/question-library/previews/{preview_id}/commit`
- `POST /api/question-library/previews/{preview_id}/discard`
- `POST /api/question-library/sessions/{session_id}/questions/{question_id}/review`
- `POST /api/question-library/sessions/{session_id}/questions/{question_id}/approve`
- `POST /api/question-library/sessions/{session_id}/questions/{question_id}/reject`
- `POST /api/question-library/sessions/{session_id}/questions/{question_id}/confirm`
- `POST /api/question-library/sessions/{session_id}/questions/{question_id}/unconfirm`
- `POST /api/question-library/previews/{preview_id}/regenerate-section`

### 现存直连任务入口

- `POST /api/question-library/crawl`
- `POST /api/question-library/generate`
- `POST /api/question-library/score`

这些入口会直接返回 `text/event-stream`。

### 题源相关集成入口

- `POST /api/available-filters`
- `POST /api/compose-blueprint`
- `GET /api/subjects`
- `GET /api/subjects/{subject_code}/filters`
- `GET /api/subjects/{subject_code}/knowledge-tree`

### Workspace 中直接依赖 crawler 的入口

- `POST /api/canvas/boards/{board_id}/pick-questions`
- `GET /api/canvas/questions/{question_id}/render`

## 3. Canonical 长任务接口

### 3.1 提交题库抓取任务

`POST /api/tasks/question-library/crawl`

用途：
- 按关键词调用 crawler 搜题
- 将命中的题目写入 `question_cache`
- 同步写入当前用户的 `question_library`

请求体字段：

```json
{
  "subject": "高中数学",
  "edu_level": "",
  "query": "函数单调性",
  "difficulty": "",
  "question_type": "",
  "limit": 30,
  "max_pages": 2,
  "min_quality_score": 0,
  "difficulty_value_min": null,
  "difficulty_value_max": null,
  "require_difficulty_value": false,
  "task_id": ""
}
```

响应：

```json
{
  "success": true,
  "taskId": "ql_crawl_xxx"
}
```

### 3.2 提交 AI 出题任务

`POST /api/tasks/question-library/generate`

用途：
- 构造 source pack
- 可选读取自学资料归档
- 可选抓取参考题并做 `reference_analysis`
- 生成 preview/session，等待人工审核后再入库

请求体字段：

```json
{
  "subject": "高中数学",
  "topic": "导数与单调性",
  "difficulty": "",
  "question_type": "",
  "count": 5,
  "use_study_archive": true,
  "use_reference_questions": true,
  "reference_source": "any",
  "reference_year_range": "all",
  "session_id": "",
  "mode": "standard",
  "grade_id": "",
  "textbook_version_id": "",
  "knowledge_point_ids": [],
  "knowledge_points": [],
  "append": false,
  "stream_reasoning": false,
  "task_id": ""
}
```

其中：
- `reference_source` 当前只支持 `any | gaokao | mock | joint`
- `reference_year_range` 当前只支持 `all | 3 | 5`
- `mode` 当前只支持 `standard | infinite`

### 3.3 提交题库评分任务

`POST /api/tasks/question-library/score`

用途：
- 读取当前用户题库中 `origin="crawled"` 的题目
- 用 LLM 对题干进行评分
- 调用 `apply_score_and_hide` 回写分数与隐藏状态

请求体字段：

```json
{
  "subject": "高中数学",
  "limit": 50,
  "only_unscored": true,
  "task_id": ""
}
```

### 3.4 通用任务状态与 SSE

状态接口：
- `GET /api/tasks`
- `GET /api/tasks/{task_id}`

流式回放：
- `GET /api/tasks/{task_id}/stream?after_seq=0`

行为说明：
- 运行中优先从内存态 `task_runtime` 推送事件
- 任务不在内存中时，降级为 DB 回放/轮询
- SSE 心跳为 `ping`
- 客户端应持久化最后一个 `seq`，断线后用 `after_seq` 续流

控制接口：
- `POST /api/tasks/{task_id}/pause`
- `POST /api/tasks/{task_id}/resume`
- `POST /api/tasks/{task_id}/cancel`
- `POST /api/tasks/{task_id}/retry`

当前限制：
- `retry` 目前只覆盖 `paper_compose`、`study_materials`、`deepthink`、`lesson_plan`、`export_*`
- `question_library_*` 任务当前没有通用 retry 分支

## 4. Question Library 资源接口

### 4.1 题库条目

列表：
- `GET /api/question-library/items`

常用查询参数：
- `subject`
- `origin`
- `hidden=0|1|all`
- `q`
- `min_score`
- `sort`
- `order`
- `limit`
- `offset`

详情：
- `GET /api/question-library/items/{question_id}`

返回结构是：
- `library_item`
- `question_cache`

说明：
- `library_item` 是用户维度条目
- `question_cache` 是题目正文缓存

条目状态操作：
- `POST /api/question-library/items/{question_id}/hide`
- `POST /api/question-library/items/{question_id}/unhide`
- `POST /api/question-library/items/{question_id}/star`
- `POST /api/question-library/items/{question_id}/unstar`
- `POST /api/question-library/items/bulk-delete`

### 4.2 Preview 与 Session

Preview：
- `GET /api/question-library/previews/{preview_id}`
- `GET /api/question-library/previews/latest/pending`
- `POST /api/question-library/previews/{preview_id}/commit`
- `POST /api/question-library/previews/{preview_id}/discard`
- `POST /api/question-library/previews/{preview_id}/regenerate-section`

Session：
- `GET /api/question-library/sessions`
- `GET /api/question-library/sessions/{session_id}`
- `POST /api/question-library/sessions/{session_id}/stop`
- `POST /api/question-library/sessions/{session_id}/archive`

题目审核动作：
- `POST /api/question-library/sessions/{session_id}/questions/{question_id}/review`
- `POST /api/question-library/sessions/{session_id}/questions/{question_id}/approve`
- `POST /api/question-library/sessions/{session_id}/questions/{question_id}/reject`
- `POST /api/question-library/sessions/{session_id}/questions/{question_id}/confirm`
- `POST /api/question-library/sessions/{session_id}/questions/{question_id}/unconfirm`

设计语义：
- `generate` 任务先产出 preview/session
- 经人工筛选后，`commit` 才会正式写入本地题库

### 4.3 题库导出题篮

`POST /api/question-library/items/{question_id}/export-to-basket`

当前行为：
- 从 `question_library` 和 `question_cache` 拼出简化题目信息
- 调用当前 crawler 的 `export_to_basket`

当前边界：
- 这是现有实现的一部分
- 但它依赖当前 crawler 的导出能力
- 由于 `backend/crawler/manager.py` 现在固定返回 `ZujuanCrawler`，该接口的实际语义仍然是“导出到当前组卷源题篮”

### 4.4 直连 SSE 入口

- `POST /api/question-library/crawl`
- `POST /api/question-library/generate`
- `POST /api/question-library/score`
- `GET /api/question-library/tasks/{task_id}`
- `GET /api/question-library/tasks/{task_id}/stream`

说明：
- 这些接口仍然有效
- 它们更接近“question-library 专属工作流接口”
- 新能力与长期口径应优先接入 `/api/tasks/*`

## 5. 题源相关集成接口

### 5.1 Filters 与 Blueprint

`POST /api/available-filters`

请求体：

```json
{
  "subject": "高中数学",
  "edu_level": ""
}
```

用途：
- 获取某学科下的筛选项，如年级、教材版本、省份、题型等

`POST /api/compose-blueprint`

请求体核心字段：

```json
{
  "blueprint": [],
  "subject": "高中数学",
  "edu_level": "",
  "learn_grade": "",
  "learn_grade_id": 0,
  "textbook_version": "",
  "elective_mode": "",
  "elective_keywords": [],
  "exclude_elective": false,
  "year": 0,
  "province": "",
  "province_id": -1,
  "paper_type_id": 0,
  "term": 0,
  "order_by": 2,
  "max_pages": 2,
  "per_slot_expand": 3,
  "min_quality_score": 0,
  "dedup_by_stem": true,
  "strict_subject": true,
  "slot_concurrency": 0,
  "slot_delay_s": 0.0,
  "slot_retries": 1
}
```

用途：
- 按多槽位 blueprint 组合题目 ID

### 5.2 Subjects

公开学科列表：
- `GET /api/subjects`

受保护的筛选项接口：
- `GET /api/subjects/{subject_code}/filters`

受保护的知识树接口：
- `GET /api/subjects/{subject_code}/knowledge-tree`

说明：
- `/filters` 返回前端使用的 `grades`、`textbookVersions`、`provinces`、`paperTypes`、`questionTypes`
- `/knowledge-tree` 优先读取 crawler 真正的知识树，失败时降级到内置 fallback
- 当前 `knowledge-tree` 返回里的 `source` 只会是 `zujuan` 或 `fallback`

### 5.3 Canvas 中直接依赖 crawler 的入口

题目挑选：
- `POST /api/canvas/boards/{board_id}/pick-questions`

用途：
- 先通过 `crawler.search_by_keyword` 拉候选
- 再交给 MCP sub-AI selector 选题
- 最后调用 `crawler.get_question_detail` 组装可渲染题目

单题渲染：
- `GET /api/canvas/questions/{question_id}/render`

用途：
- 获取单题详情
- 统一输出清洗后的 `stem_html`

## 6. 当前内部 crawler/provider 边界

### 6.1 `CrawlerInterface`

当前 protocol 在 `backend/crawler/interface.py` 中声明了这些方法：

- `initialize()`
- `close()`
- `search_by_keyword()`
- `batch_get_question_details()`
- `get_question_detail()`
- `get_available_filters()`
- `get_knowledge_tree()`
- `compose_paper_blueprint()`
- `export_to_basket()`

这表示当前系统把 crawler/provider 视为一个“完整题源适配器”，不仅要会搜题，还要会：
- 拉详情
- 给筛选项
- 返回知识树
- 组合 blueprint
- 导出题篮

### 6.2 `get_crawler()` 的当前实现

`backend/crawler/manager.py` 的当前行为：
- 先对 `subject` 做 `resolve_subject`
- 以 `(resolved_subject, edu_level)` 为 key 缓存 crawler
- 用 `_lock + _inflight` 避免并发重复初始化
- 实际创建的实例固定是 `ZujuanCrawler(subject=resolved_subject)`

这意味着：
- 当前实现仍然是 Zujuan-only
- 对外 HTTP API 中还不存在 `provider` 选择参数
- 多 provider 仍属于未来设计，不应写成当前 API 承诺

### 6.3 当前内部不一致点

当前代码存在一个需要知晓但不宜对外承诺的事实：
- `CrawlerInterface` 没声明 `search_by_knowledge`
- 但上层调用方已经在使用这个方法

这说明内部抽象还在收敛中，本文只记录当前事实，不把它升级成稳定公开契约。

## 7. 当前参考题源行为与字段约束

参考题源由 `backend/question_library/reference_crawl.py` 提供。

调用路径：
1. `create_generate_task()` 读取 `use_reference_questions`
2. 若开启，则调用 `collect_reference_questions()`
3. 拉回的题目进入 `analyze_reference_questions()`
4. 分析结果再通过 `enrich_source_pack_with_reference()` 合并进 source pack

### 7.1 参考题抓取流程

`collect_reference_questions()` 的当前步骤：

1. 生成 reference cache key
2. 优先读取 `.local/reference_cache/*.json`
3. 由 `topic + knowledge_points` 构造查询词
4. 调用 `crawler.search_by_keyword(..., parse_content=False)`
5. 对预览结果做约束过滤
6. 再调用 `crawler.batch_get_question_details(...)`
7. 归一化详情结果并写回 reference cache
8. 如果 crawler 侧为空，则从本地 `question_library + question_cache` 做降级补全

### 7.2 当前归一化字段

`_normalize_reference_question()` 当前输出：

```json
{
  "question_id": "",
  "stem": "",
  "answer": "",
  "analysis": "",
  "difficulty": "",
  "question_type": "",
  "knowledge_points": "",
  "source": "",
  "date": "",
  "origin": "crawled",
  "url": ""
}
```

### 7.3 字段约束

硬门槛：
- `question_id`
- `stem`

当前实现会实际消费的字段：
- `answer`
- `analysis`
- `difficulty`
- `question_type`
- `knowledge_points`
- `source`
- `date`
- `url`

过滤相关字段：
- `reference_source` 目前只识别 `any | gaokao | mock | joint`
- `reference_year_range` 目前只识别 `all | 3 | 5`

### 7.4 对外可见的请求字段

虽然参考题抓取是内部流程，但它由 `QuestionLibraryGenerateRequest` 透出这些控制项：
- `use_reference_questions`
- `reference_source`
- `reference_year_range`
- `knowledge_point_ids`
- `knowledge_points`

这些字段属于当前 API 的真实可用项。

## 8. 非目标与待定项

本文明确不承诺以下内容：

- 不承诺未来会支持 `provider` 请求参数
- 不承诺大学搜题酱、菁优网等任何新题源已经接入
- 不承诺 `export_to_basket`、`compose_paper_blueprint` 能自动泛化到任意 provider
- 不承诺当前内部 protocol 已经完全稳定

如果未来要推进多 provider：
- 应另写设计文档
- 不应直接修改本文，把设计假设伪装成当前 API 事实
