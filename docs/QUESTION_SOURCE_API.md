# 题源与题库 API 边界

本文说明当前题源、crawler、本地题库和相关 API 的真实边界。它用于避免把未来多 provider 设想写成当前能力。

## 当前事实

- 当前 crawler 管理器主要创建 `ZujuanCrawler`。
- 对外 API 目前没有稳定的 `provider` 选择参数。
- 题源能力不仅包括搜索，还包括详情、筛选项、知识树、蓝图组卷和导出题篮。
- 新增长任务应通过 `/api/tasks` 提交。

## 题源相关 HTTP 入口

筛选与学科：

- `POST /api/available-filters`
- `POST /api/compose-blueprint`
- `GET /api/subjects`
- `GET /api/subjects/{subject_code}/filters`
- `GET /api/subjects/{subject_code}/knowledge-tree`

画布中直接依赖题源的入口：

- `POST /api/canvas/boards/{board_id}/pick-questions`
- `GET /api/canvas/questions/{question_id}/render`

题库任务：

- `POST /api/tasks/question-library/crawl`
- `POST /api/tasks/question-library/generate`
- `POST /api/tasks/question-library/score`

## 本地题库资源

题库条目：

- `GET /api/question-library/items`
- `GET /api/question-library/items/{question_id}`
- `POST /api/question-library/items/{question_id}/hide`
- `POST /api/question-library/items/{question_id}/unhide`
- `POST /api/question-library/items/{question_id}/star`
- `POST /api/question-library/items/{question_id}/unstar`
- `POST /api/question-library/items/bulk-delete`
- `POST /api/question-library/items/{question_id}/export-to-basket`

生成 preview 与 session：

- `GET /api/question-library/previews/{preview_id}`
- `GET /api/question-library/previews/latest/pending`
- `POST /api/question-library/previews/{preview_id}/commit`
- `POST /api/question-library/previews/{preview_id}/discard`
- `POST /api/question-library/previews/{preview_id}/regenerate-section`
- `GET /api/question-library/sessions`
- `GET /api/question-library/sessions/{session_id}`
- `POST /api/question-library/sessions/{session_id}/stop`
- `POST /api/question-library/sessions/{session_id}/archive`

人工审核动作：

- `POST /api/question-library/sessions/{session_id}/questions/{question_id}/review`
- `POST /api/question-library/sessions/{session_id}/questions/{question_id}/approve`
- `POST /api/question-library/sessions/{session_id}/questions/{question_id}/reject`
- `POST /api/question-library/sessions/{session_id}/questions/{question_id}/confirm`
- `POST /api/question-library/sessions/{session_id}/questions/{question_id}/unconfirm`

## 题库抓取任务

```http
POST /api/tasks/question-library/crawl
```

典型请求：

```json
{
  "subject": "高中数学",
  "query": "函数单调性",
  "difficulty": "中等",
  "question_type": "选择题",
  "limit": 30,
  "max_pages": 2
}
```

任务会搜索题源、写入题目缓存，并把条目加入当前用户题库。

## AI 出题任务

```http
POST /api/tasks/question-library/generate
```

典型请求：

```json
{
  "subject": "高中数学",
  "topic": "导数与单调性",
  "difficulty": "中等",
  "question_type": "解答题",
  "count": 3,
  "use_study_archive": true,
  "use_reference_questions": true,
  "reference_source": "any",
  "reference_year_range": "all",
  "mode": "standard"
}
```

生成结果先进入 preview/session，用户确认后再正式写入本地题库。

## 题库评分任务

```http
POST /api/tasks/question-library/score
```

典型请求：

```json
{
  "subject": "高中数学",
  "limit": 50,
  "only_unscored": true
}
```

评分用于给抓取题目打质量分，并可配合自动隐藏低分题。

## crawler provider 契约

当前内部接口见 `backend/integrations/crawler/interface.py`，一个完整题源适配器至少需要覆盖：

- 初始化与关闭。
- 关键词搜索。
- 批量详情。
- 单题详情。
- 可用筛选项。
- 知识树。
- 蓝图组卷。
- 导出题篮。

如果新增 provider，需要同时考虑：

- 题目 ID 格式是否全局唯一。
- 筛选项字段如何标准化。
- HTML/公式/图片如何清洗。
- 本地缓存如何区分 provider。
- 导出题篮是否支持，不能支持时如何降级。
- 合规与速率限制。

## 不承诺的内容

当前文档不承诺：

- 已支持任意多题源 provider。
- 已支持通过 API 参数切换 provider。
- 任意 provider 都支持 `compose_paper_blueprint` 或 `export_to_basket`。
- 抓取详情一定包含答案和解析。

新增题源前应先写设计，再落代码和测试。

## 相关文档

- `SEARCH_FILTERS_AND_BLUEPRINTS.md`：筛选项和蓝图组卷。
- `API.md`：题库 HTTP 接口总览。
- `ARCHITECTURE.md`：crawler 在整体架构中的位置。
