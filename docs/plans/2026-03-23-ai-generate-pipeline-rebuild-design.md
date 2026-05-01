# AI Generate Pipeline 重建设计记录

状态：历史记录，当前主线已向 agentic runtime 和任务中心收敛。

## 背景

该设计用于解决 AI 出题链路阶段分散、prompt 难追踪、任务状态难恢复的问题。

## 当前落点

- `backend/generation/agentic/`：类型、runtime、tooling、prompt contracts。
- `backend/question_library/`：题库生成领域逻辑。
- `backend/tasks/`：任务提交和 runner。
- `backend/shared/tasks/`：统一任务运行时。
- `backend/tests/test_agentic_*`：agentic 相关测试。

## 当前原则

- prompt 集中注册并测试。
- 任务事件结构稳定，前端可回放。
- 领域 runner 只负责业务流程，不另建任务基础设施。
- 生成、审查、修订和入库阶段要能单独定位失败原因。

## 不再维护的内容

旧 pipeline 名称、临时状态字段和非任务中心入口不作为新功能承诺。
