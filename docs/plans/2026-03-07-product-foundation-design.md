# Product Foundation 设计记录

状态：历史记录。

## 背景

该计划用于梳理 Study AI 从单点工具向学习工作台扩展时需要的产品基础：导航、认证、任务中心、设置、工作区内容和导出。

## 当前落点

- 认证：`backend/api/auth.py`，前端登录页。
- 设置：`backend/api/system.py`，`frontend/src/features/settings/`。
- 任务中心：`backend/api/tasks.py`，`frontend/src/pages/tasks/`。
- 工作区内容：对话、试卷、画布、模板、归档、错题、批注。
- 导出：`backend/api/exports.py` 与任务化导出入口。

## 当前原则

- 用户可见长流程都应能在任务中心追踪。
- 设置项要区分全局配置、用户设置和本地开发配置。
- 新页面要放入路由和导航，但不要复制历史页面结构。

## 当前文档

- `../ARCHITECTURE.md`
- `../API.md`
- `../CONFIGURATION.md`
