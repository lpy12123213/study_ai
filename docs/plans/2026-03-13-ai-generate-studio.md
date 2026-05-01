# AI Generate Studio 实施记录

状态：历史记录。

## 已实现方向

- AI 出题工作台。
- 任务流展示。
- 上下文栏与素材组织。
- 生成草稿卡片。
- 审核页。
- 会话恢复和历史面板。

## 当前代码

- `frontend/src/features/aiGenerate/`
- `frontend/src/pages/ai-generate/`
- `backend/question_library/`
- `backend/generation/agentic/`

## 后续维护

- 新增交互要补充 Vitest。
- 任务错误需要用用户可理解的文案映射。
- LaTeX 和题目结构变更要同时影响预览、审核和入库。
