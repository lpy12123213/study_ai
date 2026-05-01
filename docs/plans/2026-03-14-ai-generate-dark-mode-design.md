# AI Generate 深色模式设计记录

状态：历史记录。

## 背景

该记录用于跟踪 AI 出题工作台的深色模式和视觉一致性。当前文档只保留维护原则。

## 维护原则

- 深色模式不应只反转颜色，需要检查边框、阴影、代码块、LaTeX、浮层和状态色。
- 任务流、草稿卡片、审核页和弹窗需要同时验证。
- 新组件应复用已有设计 token 或共享组件，不单独硬编码一套颜色。
- 对比度不足、状态色不可辨认、hover/focus 缺失都应视为缺陷。

## 当前落点

- `frontend/src/features/aiGenerate/`
- `frontend/src/components/`
- `frontend/src/pages/ai-generate/`

如需继续推进，应以当前前端主题系统为准重新开任务。
