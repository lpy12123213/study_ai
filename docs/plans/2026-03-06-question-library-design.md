# Question Library 设计记录

状态：历史记录，核心能力已进入当前题库模块。

## 背景

本设计记录最初用于定义本地题库、题源抓取、AI 出题、预览审核和评分流程。

## 当前落点

- API 边界见 `../QUESTION_SOURCE_API.md`。
- 题库路由在 `backend/api/question_library.py`。
- 任务化入口在 `backend/api/tasks.py`。
- 后端业务逻辑在 `backend/question_library/`。
- 前端 UI 在 `frontend/src/features/questionLibrary/` 和 `frontend/src/pages/question-library/`。

## 当前流程

1. 抓取任务写入题目缓存和用户题库。
2. AI 出题任务生成 preview/session。
3. 用户审核后 commit 入库。
4. 评分任务对题目质量打分并可隐藏低分题。

## 维护重点

- 新的题库长任务优先接入 `/api/tasks/question-library/*`。
- 不把未来多题源 provider 写成当前能力。
- 用户可见字段变更需要同步 API 文档和前端类型。
