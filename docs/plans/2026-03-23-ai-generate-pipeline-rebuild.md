# AI Generate Pipeline 重建实施记录

状态：历史记录。

## 已落地方向

- 新增 agentic 生成基础设施。
- 补充 prompt contract 测试。
- 题库生成任务接入统一任务中心。
- 前端工作台围绕任务流和草稿审核组织。

## 当前验证重点

- `backend/tests/test_agentic_runtime.py`
- `backend/tests/test_agentic_task_adapter.py`
- `backend/tests/test_agentic_prompt_registry.py`
- `backend/tests/test_question_library_generate.py`
- `frontend/src/features/aiGenerate/__tests__/`

## 后续维护

新增生成阶段时，同步更新：

- prompt registry。
- 任务事件映射。
- 前端任务展示。
- API 或专项文档。
