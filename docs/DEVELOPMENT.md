# 开发指南

本文定义 Study AI 的开发环境、代码组织、变更流程和最低验证标准。所有代码变更应遵循本文；涉及质量门禁时同时遵循 `QUALITY_AND_RELEASE.md`。

## 开发基线

- 代码风格以 `.editorconfig`、`pyproject.toml`、前端 ESLint 和 TypeScript 配置为准。
- 后端测试框架为 `unittest`。
- 前端测试框架为 Vitest，端到端测试使用 Playwright。
- 新增长任务必须接入 `/api/tasks` 和 `TaskRuntime`。
- 新复杂前端功能必须采用 feature slice 组织。

## 本地环境

推荐从仓库根目录运行：

```bat
start.bat setup
start.bat dev
```

Linux / macOS：

```bash
./start.sh setup
./start.sh dev
```

手动后端：

```bash
python -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m uvicorn backend.app:app --reload --port 8000
```

手动前端：

```bash
cd frontend
npm install
npm run dev
```

## 代码组织

后端：

- `backend/api/`：HTTP 路由和 schema。
- `backend/core/`：设置、日志、安全、通用基础设施。
- `backend/database/`：schema、迁移、仓库层。
- `backend/shared/`：跨域共享能力。
- `backend/tasks/`：长任务提交和 runner。
- `backend/generation/`：生成 runtime 和知识视频。
- `backend/question_library/`：题库和 AI 出题。
- `backend/study_materials/`：自学资料。
- `backend/lesson_plan/`：教案。
- `backend/paper_compose/`：组卷和导出。
- `backend/crawler/`：题源适配。
- `backend/mcp/`：MCP 工具服务。

前端：

- `frontend/src/features/<domain>/`：复杂业务功能。
- `frontend/src/pages/`：路由页面装配。
- `frontend/src/api/`：API client。
- `frontend/src/components/`：跨页面组件。
- `frontend/src/hooks/`：共享 hooks。
- `frontend/src/lib/`：通用工具。

## 布局变体

页面必须明确选择一种布局语义，避免在 `ManusLayout` 中继续追加散落的 `pathname.startsWith(...)` 判断。

当前 `frontend/src/components/layout/ManusLayout.tsx` 已存在 4 类行为：

| layout | 侧边栏 | 顶栏 | 内容宽度 | 滚动责任 | 适用页面 |
| --- | --- | --- | --- | --- | --- |
| `standard` | 显示 | 显示 | 跟随用户内容宽度设置 | Layout 统一滚动 | chat、papers、settings 等普通工作台页 |
| `wide` | 显示 | 显示 | 全宽 | 页面或 Layout 按需滚动 | blueprint、lesson-plans、deepthink 等大画布页 |
| `studio` | 隐藏 | 显示 | 全宽 | 页面自行管理内部滚动 | question-library、ai-generate 等沉浸式工作区 |
| `fullscreen` | 隐藏 | 隐藏 | 全屏 | 页面完全自管 | canvas 等全屏交互页 |

新增页面的决策顺序：

1. 需要占满整个浏览器且不显示顶栏，选 `fullscreen`。
2. 需要顶栏但不需要历史侧栏，选 `studio`。
3. 需要侧栏且主体需要全宽，选 `wide`。
4. 其他页面选 `standard`。

目标形态是在路由配置中声明布局，而不是在布局组件内写路径判断。迁移到 `ROUTE_CONFIG` 时，每个路由至少标注：

```ts
{
  path: '/study-materials',
  label: '自学资料',
  layout: 'wide',
  sidebar: true,
}
```

`Header`、`CommandPalette`、`ManusLayout` 和面包屑应从同一份路由配置派生导航、标题、布局和侧边栏行为。

## 架构约束

后端新增能力必须选择明确领域：

- 系统能力归入 system。
- 认证和用户权限归入 auth。
- 对话、画布、试卷、归档、模板等用户内容归入 workspace。
- 内容生成、AI 出题、自学资料、教案和知识视频归入 generation。
- 长任务提交、状态、事件和回放归入 tasks。
- 外部服务、题源、MCP 和搜索 provider 归入 integrations。
- 跨领域基础设施归入 shared。

不得新增长期主路径：

- `*_v2`
- `legacy`
- `compat`
- `shim`

临时兼容层必须是薄转发，并在迁移完成后删除。

## 新增后端 API

1. 在 `backend/api/<domain>.py` 或现有 router 中实现接口。
2. 在 `backend/api/domains/<domain>.py` 聚合。
3. 需要 schema 时放在对应 `*_schemas.py`。
4. 数据访问走 `backend/database/repositories/`。
5. 更新 `docs/API.md`。

新增长任务时：

1. 在 `backend/tasks/submit.py` 增加提交函数。
2. 在 `backend/tasks/runners.py` 增加 runner。
3. 通过 `backend/shared/tasks/TaskRuntime` 发事件。
4. 在 `backend/api/tasks.py` 暴露提交入口。
5. 前端通过 `/api/tasks/{taskId}/stream` 监听。

禁止为新长任务新增独立任务池。

## 新增前端功能

复杂功能放入：

```text
frontend/src/features/<domain>/
```

页面文件只装配：

```text
frontend/src/pages/<domain>/<Page>.tsx
```

新增路由时同步：

- `frontend/src/App.tsx`
- 导航或命令面板，如适用
- 相关测试

## 测试

后端：

```bash
python -m unittest discover -s backend/tests -p "test_*.py"
```

前端：

```bash
cd frontend
npm run lint
npm run build
npm run test
```

综合检查：

```bash
start.bat doctor
```

文档-only 改动至少运行：

```bash
git diff --check
```

## Definition of Done

功能或修复完成前必须满足：

- 实现范围与需求一致，无无关重构。
- 关键路径有自动化测试或明确人工验证。
- 错误路径可观测，前端有可理解反馈。
- 新增配置、接口、任务事件或用户行为已同步文档。
- 本地检查命令已运行，并在交付说明中说明结果。

文档-only 变更必须满足：

- 链接可解析。
- 命令、路径和接口名称与当前仓库一致。
- 没有真实密钥、Cookie 或个人本地数据。
- `git diff --check` 通过。

## 配置变更

新增环境变量时同步：

- `.env.example`
- `docs/CONFIGURATION.md`
- 需要时更新 `backend/core/settings.py`
- 需要时更新 `/api/config` 摘要

密钥和 Cookie 不允许写入代码、测试快照或文档。

## Prompt 和生成链路

生成相关 prompt 应集中维护，并补测试覆盖：

- prompt registry。
- prompt contract。
- 关键工具输入输出。
- 任务事件。

不要把长 prompt 分散硬编码在 UI 组件里。

## 文档变更

用户可见行为变化：

- 更新 `docs/USER_GUIDE.md`。

API 或任务事件变化：

- 更新 `docs/API.md`。

架构边界变化：

- 更新 `docs/ARCHITECTURE.md`。

部署依赖变化：

- 更新 `docs/DEPLOYMENT.md`。

## Git 注意事项

- 不要提交 `.env`、数据库、生成物、抓取内容、node_modules、venv。
- 不要改写历史，除非明确要求。
- 不要还原与当前任务无关的用户改动。
- 提交信息使用 Conventional Commits。

## 相关文档

- `ARCHITECTURE.md`：边界和数据流。
- `API.md`：接口与任务中心。
- `CONFIGURATION.md`：配置项维护。
- `QUALITY_AND_RELEASE.md`：质量门禁和发布检查。
