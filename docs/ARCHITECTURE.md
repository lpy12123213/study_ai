# 架构说明

本文描述 Study AI 的当前架构和目标边界。它用于指导新增功能落位、重构判断和文档维护，不替代代码级 API 文档。

Study AI 是一个本地优先的学习与出题工作台。系统由浏览器前端、FastAPI 后端、SQLite 存储、题源 crawler、LLM provider、MCP stdio server 和统一任务运行时组成。

## 当前运行架构

```text
Browser
  |
  | HTTP / SSE
  v
FastAPI backend
  |
  | SQLAlchemy
  v
SQLite + local files

MCP client
  |
  | stdio / MCP
  v
backend.mcp.stdio_server
  |
  | crawler / database / LLM tools
  v
Study AI backend modules
```

前端开发时通常由 Vite 独立服务；同源部署时，后端可以托管 `frontend/dist`。

## 架构原则

- 单一主路径：同一能力只能有一个 canonical 入口。
- 任务统一：所有新长任务必须使用 `/api/tasks` 和共享 `TaskRuntime`。
- 数据最小化：默认只持久化必要元数据，敏感内容必须显式开启。
- 领域隔离：业务逻辑不得随意跨目录调用内部细节，跨域能力放入 shared 或明确接口层。
- 可观测：长流程必须输出结构化事件或稳定日志。
- 可替换：外部 provider 适配必须通过明确边界接入，不在业务层散落 provider 判断。

## 代码入口

- 后端应用入口：`backend/app.py`
- API 聚合入口：`backend/api/router.py`
- 前端入口：`frontend/src/main.tsx`
- 前端路由：`frontend/src/App.tsx`，并逐步向 `frontend/src/router/` 收敛
- MCP 入口：`python -m backend.mcp.stdio_server`
- 启动器：`scripts/start.py`

## 后端领域边界

目标边界：

- `system`：健康检查、配置、指标、日志、运维。
- `auth`：认证、用户、JWT、权限。
- `workspace`：对话、画布、试卷、归档、模板、批注、反馈等用户工作区内容。
- `generation`：DeepThink、自学资料、教案、AI 出题、知识视频等生成流程。
- `tasks`：长任务提交、状态、事件、回放、控制。
- `integrations`：crawler、MCP、搜索 provider、外部工具链。
- `shared`：跨领域复用的纯基础设施。

当前代码仍保留历史目录，但新增代码应向上述边界收敛。不要把 `*_v2`、`legacy`、`compat`、`shim` 当长期主路径；兼容层只能是薄转发，并且应有删除计划。

## 非目标

当前架构不承诺：

- 已完成多题源 provider 泛化。
- 已提供官方容器化生产部署入口。
- 已将所有历史目录迁移到目标边界。
- 已支持云端多租户生产级隔离。

这些能力如需推进，必须先形成设计、边界和测试计划。

## API 聚合

`backend/api/router.py` 把所有 `/api/*` 路由按领域挂载：

- `backend/api/domains/system.py`
- `backend/api/domains/integrations.py`
- `backend/api/domains/workspace.py`
- `backend/api/domains/auth.py`
- `backend/api/domains/generation.py`
- `backend/api/domains/tasks.py`

新增路由优先放进对应领域聚合文件，不要直接在 `app.py` 零散注册。

## 任务运行时

`/api/tasks` 是长任务 canonical API。核心实现：

- `backend/shared/tasks/runtime.py`
- `backend/shared/tasks/store.py`
- `backend/tasks/submit.py`
- `backend/tasks/runners.py`
- `backend/api/tasks.py`

任务状态和事件会写入数据库，内存 runtime 负责实时执行和短期 SSE 推送。服务重启后，状态接口和流式接口仍可以从数据库回放已有事件。

事件约定：

- `taskId`：任务 ID。
- `seq`：递增序号，用于断线续流。
- `type`：`step`、`progress`、`result`、`error`、`ping` 等。
- `data`：事件载荷。

新增长任务应接入 `TaskRuntime`，而不是新增一套内存任务池。

## 数据层

数据库相关代码：

- `backend/database/schema.py`
- `backend/database/engine.py`
- `backend/database/migrations.py`
- `backend/database/repositories/`

默认存储是 SQLite，本地文件在 `.local/` 下。仓库目标是通过仓库层隔离数据访问，避免业务代码直接散落 SQL。

默认合规口径是“元数据优先、内容最小化”：

- 试卷默认保存题目 ID 和必要元数据。
- 题干、答案、解析是否保存由 `PAPER_STORE_*` 配置控制。
- 本地抓取内容、生成物和数据库不要提交到 Git。

## 题源与 crawler

当前 crawler 主路径：

- `backend/integrations/crawler/interface.py`
- `backend/integrations/crawler/manager.py`
- `backend/integrations/crawler/zujuan/`

当前实现仍以 ZujuanCrawler 为主。对外 API 里不要承诺任意 provider 已经可用；多题源属于后续扩展，需要单独设计 provider 契约、缓存、合规和导出行为。

## 生成链路

主要生成域：

- `backend/agent/`：通用 agent、工具调用、反思、规划。
- `backend/generation/agentic/`：结构化 agentic runtime、prompt registry、任务适配。
- `backend/generation/study_materials/`：自学资料编排。
- `backend/generation/lesson_plan/`：教案生成与导出。
- `backend/generation/question_library/`：AI 出题、参考分析、评分、预览审核。
- `backend/generation/paper_compose/`：蓝图组卷、一键组卷、导出。
- `backend/generation/deepthink/`：深度解题。
- `backend/generation/knowledge_video/`：知识视频生成。

prompt 应集中维护并有测试覆盖，避免在业务代码里分散硬编码。

中型和重型 AI 长任务必须声明原生 `AgentRunSpec`。当前覆盖 DeepThink、教案、组卷、一键出卷、知识视频、自学资料、AI 出题/评分和好题鉴别；任务启动事件暴露 `agent_run_spec`，现有领域 runner 继续输出兼容 SSE 事件。

## 前端边界

目标结构是 feature slice：

```text
frontend/src/features/<domain>/
|-- components/
|-- hooks/
|-- api/
|-- types.ts
`-- __tests__/
```

跨业务复用内容放在：

- `frontend/src/components/`
- `frontend/src/hooks/`
- `frontend/src/lib/`
- `frontend/src/api/`
- `frontend/src/types/`

页面文件应负责路由装配，不承载复杂业务逻辑。

## 关键数据流

长任务生成：

```text
Frontend submit
  -> POST /api/tasks/<type>
  -> TaskRuntime creates DB row + starter event
  -> domain runner emits step/progress/result events
  -> frontend listens /api/tasks/{taskId}/stream
  -> refresh reconnects with after_seq
```

MCP 组卷：

```text
MCP client
  -> call tool search/blueprint/review/create_paper
  -> backend.mcp tools
  -> crawler + database + LLM provider
  -> JSON result to client
```

试卷导出：

```text
Paper metadata
  -> export renderer
  -> Markdown / LaTeX
  -> optional xelatex / pandoc
  -> generated media file
  -> /api/media/generated/{filename}
```

## 维护规则

- 新的长任务必须进入 `/api/tasks`。
- 新 API 必须挂在对应 domain router。
- 新配置项要更新 `.env.example` 和 `docs/CONFIGURATION.md`。
- 新前端功能优先放入 `features/<domain>`。
- 改变用户行为、部署方式、工具链要求时同步更新文档。
- 改变架构主路径时必须同步本文，并移除过期路径说明。

## 相关文档

- `DEVELOPMENT.md`：具体开发流程。
- `API.md`：HTTP 接口和任务中心。
- `QUESTION_SOURCE_API.md`：题源和题库边界。
- `CONFIGURATION.md`：配置加载和环境变量。
