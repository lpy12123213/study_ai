# 仓储层（Repositories）

`backend/database/repositories/` 是数据库访问的唯一入口。本文记录目录拓扑、命名规则与各仓储职责，避免新人在多个语义重叠的文件之间迷路。

## 命名规则

```
backend/database/repositories/<domain>/<scope>.py
```

- `domain`：与 `backend/<domain>/` 顶层领域一致（`system` / `auth` / `workspace` / `generation` / `tasks` / `integrations` / `question` / ...）。
- `scope`：操作的资源单数复数小写（`papers`、`learning_plans`、`share_links`、`question_library`、`generated_files`），不要混用动词或语义复合（曾经的 `exports.py` 把 `share_links` 与 `generated_files` 拼在一起，已删除）。
- 不允许以 `legacy_*`、`*_v2`、`compat_*` 命名长期维持的仓储；这些前/后缀只能作为短期 forwarder。

## System

- `system/tasks.py`：TaskRuntime 的持久化背后端（task + task_events 表），所有长任务的事件流都落到这里。
- `system/share_links.py`：分享链接表。密码哈希走 `backend/core/security/password.py`，不再在仓储里复刻 bcrypt 实现。
- `system/generated_files.py`：生成产物（pdf/md/zip/...）元数据。
- `system/learning_plans.py`：学习计划与子项目。
- `system/audit.py`（如存在）：审计日志查询入口。

> 历史上还有 `system/exports.py`，它是 `share_links.py` + `generated_files.py` 的复制粘贴合并，且无任何调用方。已在 2026-05 删除。

## Question

- `question/question_library.py`：用户题库聚合视图（list / detail / hide / star / bulk delete）。
- `question/question_cache.py`：题目原始内容缓存（按 question_id）。
- `question/gaokao.py`：高考真题与结构化出处的事务导入；出处记录同时作为独立区域的成员资格。
- `question/wrongbook.py`：错题本。

## Workspace

- `workspace/conversations.py`、`workspace/papers.py`、`workspace/study_archives.py`、`workspace/templates.py`、`workspace/blueprints.py`、`workspace/annotations.py`、`workspace/feedback.py`、`workspace/item_meta.py`：用户工作区资源。
- 全部默认按 `user_id` 过滤；新增方法必须把 `user_id` 作为必填参数。

## Generation

- `generation/study_archives.py`、`generation/study_materials_tasks.py`：生成产物（自学资料、教案任务等）持久化。
- 新增 generation 资源（如教案、作文批改、知识视频）按同样规则放到 `generation/<scope>.py`。

## 共享原则

1. 仓储函数返回 `dict` 或 ORM-detached 对象，不要直接返回 SQLAlchemy 实体给上层。
2. 任何仓储函数都必须支持 `session: Optional[AsyncSession] = None` 参数；调用方可传共享 session 做事务，否则仓储自管 session 并 commit。
3. 密码、JWT、token 等敏感处理统一从 `backend/core/security/` 调用，仓储层不直接 import `bcrypt` / `jwt`。
4. 长任务事件写入只能走 `backend/shared/tasks/runtime.py` → `system/tasks.py`，业务代码不直接 INSERT `task_events`。
5. 新增表必须有 alembic 迁移；`backend/database/migrations.py` 里的 sync 兜底只是 first-boot fallback。
