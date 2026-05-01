# NextStep Backlog 设计记录

状态：历史记录。

## 背景

该计划用于整理项目早期的 backlog、技术债和下一步治理方向。当前仓库已经把运行、配置、API、任务和架构口径收敛到主文档。

## 当前落点

- 架构边界见 `../ARCHITECTURE.md`。
- 开发和验证入口见 `../../README.md`。
- 任务中心口径见 `../API.md`。
- 配置治理见 `../CONFIGURATION.md`。

## 仍然有效的原则

- 新增长任务接入 `/api/tasks`。
- 新增前端复杂功能放入 `frontend/src/features/<domain>/`。
- 配置项同步 `.env.example` 和文档。
- 历史兼容层只能作为薄转发，完成迁移后删除。

## 不再维护的内容

旧 backlog 不作为当前排期承诺。需要继续推进时，应重新拆成具体 issue、PR 或当前文档中的维护项。
