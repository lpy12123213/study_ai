# 迁移计划

本文记录 Study AI 从历史目录结构迁移到目标领域边界的执行计划。它是 `docs/ARCHITECTURE.md` 的落地清单，不替代代码评审、测试或发布说明。

## 目标边界

后端目标顶层领域：

- `system`：健康检查、配置、指标、日志、运维。
- `auth`：认证、用户、JWT、权限。
- `workspace`：用户工作区内容，包括对话、画布、试卷、归档、模板、批注、反馈。
- `generation`：DeepThink、自学资料、教案、AI 出题、知识视频等生成流程。
- `tasks`：长任务提交、状态、事件、回放、控制。
- `integrations`：crawler、MCP、搜索 provider、外部工具链。
- `shared`：跨领域复用的基础设施。

前端目标结构：

- `frontend/src/features/<domain>/` 承载业务特性。
- `frontend/src/components/`、`frontend/src/hooks/`、`frontend/src/lib/`、`frontend/src/api/`、`frontend/src/types/` 仅保留跨域共享内容。
- 页面文件只负责路由装配，不承载复杂业务逻辑。

## API 路由迁移表

| 当前位置 | 目标领域 | 状态 | 迁移说明 |
| --- | --- | --- | --- |
| `backend/api/system.py` | `system` | 已完成 (2026-04) | 通过 `backend/api/domains/system.py` 挂载，业务逻辑在 `backend/system/`。 |
| `backend/api/auth.py`, `auth_schemas.py` | `auth` | 已完成 (2026-04) | auth domain 已聚合；后续 `backend/auth/` 服务化为长期演进项。 |
| `backend/api/tasks.py` | `tasks` | 已完成 (2026-04) | `/api/tasks` 是长任务 canonical API；新增长任务必须走 `TaskRuntime`。 |
| `backend/api/conversations.py`, `chat.py`, `canvas.py` | `workspace` | 已完成 (2026-04) | 工作区内容 API 已聚合 workspace；业务服务逐步内化到 `backend/workspace/` 仓储层。 |
| `backend/api/papers.py`, `blueprints.py`, `study_archives.py`, `templates.py` | `workspace` | 已完成 (2026-04) | 试卷、蓝图、归档、模板已归 workspace；生成流程只返回任务或结果引用。 |
| `backend/api/annotations.py`, `feedback.py`, `item_meta.py`, `learning_plans.py`, `wrongbook.py` | `workspace` | 已完成 (2026-05) | workspace 聚合稳定；权限、分页和 envelope 约定一致。 |
| `backend/api/study_materials.py`, `lesson_plan.py`, `deepthink.py`, `question_library.py`, `question_evaluate.py` | `generation` | 已完成 (2026-05) | 长流程入口已收敛到 `backend/generation/` 领域 runner。 |
| `backend/api/media.py`, `share_links.py` | `workspace` / `integrations` | 进行中 | 用户生成物归 workspace；外部渲染/导出工具链归 integrations。`backend/api/exports.py` 死代码已移除（2026-05）。 |
| `backend/api/crawler_tools.py`, `subjects.py` | `integrations` | 已完成 (2026-04) | crawler、题源、学科源数据已归 integrations。 |
| `backend/api/schemas.py`, `error_codes.py`, `error_messages.py` | `shared` | 进行中 | 仅保留跨域公共 schema/error；领域 schema 持续放回各 domain。 |

## 后端目录迁移表

| 当前位置 | 目标位置 | 优先级 | 处理方式 |
| --- | --- | --- | --- |
| `backend/generation/` | `backend/generation/` | P0 | 已是目标主路径；新增 agentic runtime、prompt registry、知识视频优先放这里。 |
| `backend/study_materials/` | `backend/generation/study_materials/` | P1 | 先拆 coordinator/resume/snapshot，再移动；保留薄 forwarder 一个发布周期。 |
| `backend/lesson_plan/` | `backend/generation/lesson_plan/` | P1 | 先稳定导出和任务 runner，再迁移。 |
| `backend/question_library/` | `backend/generation/question_library/` | P1 | 先拆 session/scoring/generation 子模块，避免整目录搬迁造成冲突。 |
| `backend/question_evaluate/` | `backend/generation/question_evaluate/` | P1 | 与 question library 共享题目评价类型。 |
| `backend/deepthink/` | `backend/generation/deepthink/` | P1 | 保留当前 API 兼容，内部 runner 迁入 generation。 |
| `backend/paper_compose/` | `backend/generation/paper_compose/` 或 `workspace/papers` | P1 | 组卷编排归 generation；试卷持久化和查询归 workspace。 |
| `backend/chat/` | `backend/workspace/chat/` | P2 | 对话存储归 workspace；LLM 调用仍通过 `backend/llm/`。 |
| `backend/crawler/`, `backend/mcp/` | `backend/integrations/` | P2 | 先建立 adapter 契约，再移动 provider 实现。 |
| `backend/core/` | `backend/shared/` 或领域目录 | P2 | 只保留真正跨域基础设施；业务配置和适配器不得继续堆入 core。 |
| `backend/database/repositories/` | 按 domain 分组 | P2 | 保持仓储层隔离，新增 repository 必须标注归属 domain。 |

## 前端迁移表

| 当前位置 | 目标位置 | 优先级 | 处理方式 |
| --- | --- | --- | --- |
| `frontend/src/features/aiGenerate/` | `features/generation/aiGenerate/` | P1 | 保持现有功能切片，后续统一 generation 命名。 |
| `frontend/src/features/studyMaterials/` | `features/generation/studyMaterials/` | P1 | 页面薄壳保留在 `pages/`，逻辑留在 feature。 |
| `frontend/src/features/lessonPlans/` | `features/generation/lessonPlans/` | P1 | 继续拆 hooks/components，避免路由组件堆状态。 |
| `frontend/src/features/questionLibrary/` | `features/generation/questionLibrary/` | P1 | 列表、审核、任务流分层。 |
| `frontend/src/api/*.ts` | `api/<domain>/{client,types,sse}.ts` | P2 | 保留 `api/<name>.ts` barrel 兼容旧 import。 |
| `frontend/src/types/index.ts` | `types/<domain>.ts` | P2 | 公共类型按 domain 拆分，避免全局 types 重复定义。 |
| `frontend/src/layouts/` | 删除或 thin forwarder | P0 | 删除前必须确认无运行时引用；主路径是 `components/layout/`。 |

## 分批执行

1. 批次 A：路由聚合稳定化。
   - 只允许新增路由挂到 `backend/api/domains/*`。
   - `app.py` 不再直接注册业务 router。
   - 更新 API 文档和路由测试。

2. 批次 B：generation 内部迁移。
   - 先迁移 `study_materials`、`lesson_plan`、`deepthink` 的 runner 层。
   - 保留兼容 import，不新增 `*_v2` 主路径。
   - 每个迁移 PR 必须包含单元测试和一次长任务 smoke。

3. 批次 C：workspace 内容迁移。
   - 试卷、归档、模板、批注、错题本收敛到 workspace。
   - 统一权限、分页、错误 envelope。

4. 批次 D：integrations 迁移。
   - crawler、MCP、搜索 provider 建立 adapter 契约。
   - 外部工具失败必须可观测，不允许静默吞错。

5. 批次 E：前端 feature slice 收敛。
   - 页面文件变成薄路由壳。
   - API 类型按 domain 拆分。
   - 保留兼容 barrel，完成后统一删除。

## 结构规则

新增代码必须遵守：

- 不新增长期 `legacy`、`compat`、`shim`、`*_v2` 主目录。
- 不在 `backend/app.py` 注册新的业务路由。
- 不直接新增到已计划迁移的历史目录，除非是该目录迁移前的维护补丁。
- 新长任务必须使用 `/api/tasks` 和共享 `TaskRuntime`。
- 新前端业务逻辑必须放进 `frontend/src/features/<domain>/`。

CI 已接入结构 lint，默认在 pull request 和主分支 push 时执行：

```text
python scripts/audit/structure_lint.py --strict
```

本地仍可不带 `--strict` 运行同一脚本做迁移前预检。

## 完成判定

迁移项只有同时满足以下条件才可标记完成：

- 代码主路径已经移动或转为薄 forwarder。
- 新增和修改的调用点只引用 canonical 路径。
- 文档、测试、启动脚本与实际入口一致。
- 兼容层有明确删除计划，且不承载业务逻辑。
- 相关检查已在本地或 CI 中验证。


## 迁移结束

批次 A-E 的主路径迁移已经完成（2026-05）。后续维护工作：

- **Forwarder 删除窗口**：`backend/study_materials/`、`backend/lesson_plan/`、`backend/question_library/`、`backend/question_evaluate/`、`backend/deepthink/`、`backend/paper_compose/` 下的薄 forwarder 模块计划在 2026-09 之前清理；新代码不应导入这些路径。
- **结构 lint**：`scripts/audit/structure_lint.py --strict` 已纳入 CI，会阻止新增到已迁移的历史目录。
- **新功能落地约束**：
  - 长任务必须走 `/api/tasks` + `TaskRuntime`；
  - 业务路由挂在 `backend/api/domains/<area>.py`；
  - 前端业务进 `frontend/src/features/<domain>/`，页面只做路由薄壳；
  - 新仓储层文件按 domain 分组，命名 `repositories/<domain>/<scope>.py`。
- **死代码与重复实现**：`backend/database/repositories/system/exports.py` 已删除（2026-05）。后续应避免在 repositories 下复制粘贴跨域实现，统一在 `backend/core/security/` 等共享模块提供单一来源。
