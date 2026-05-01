# Question Library 实施记录

状态：历史记录。

## 已收敛能力

- 本地题库条目列表、详情、隐藏、收藏和批量删除。
- 题源抓取写入本地题库。
- AI 出题 preview/session。
- 人工审核后入库。
- 评分与低分隐藏。

## 当前入口

- `GET /api/question-library/items`
- `POST /api/tasks/question-library/crawl`
- `POST /api/tasks/question-library/generate`
- `POST /api/tasks/question-library/score`

详细列表见 `../QUESTION_SOURCE_API.md`。

## 后续维护

后续题库改动应优先补充：

- 后端单元测试。
- 前端 Vitest 测试。
- API 文档。
- 任务流回放行为验证。
