# AI Generate Studio 设计记录

状态：历史记录，当前能力已落到 AI 出题工作台。

## 背景

该设计用于把 AI 出题从简单表单升级为带任务流、素材上下文、草稿审核和会话历史的工作台。

## 当前落点

- 后端：`backend/question_library/`
- agentic 支撑：`backend/generation/agentic/`
- 前端：`frontend/src/features/aiGenerate/`
- 页面：`frontend/src/pages/ai-generate/`
- 任务：`/api/tasks/question-library/generate`

## 当前流程

1. 用户配置出题任务。
2. 后端收集参考材料和题目上下文。
3. AI 生成草稿。
4. 用户审核、重写、确认或丢弃。
5. 确认后进入本地题库。

## 维护重点

- 生成链路的 prompt 契约要有测试。
- 前端草稿状态不能只存在临时组件状态中。
- 用户确认前不要把 AI 草稿当正式题库条目。
