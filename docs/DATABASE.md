# 数据库迁移约定

本文定义 Study AI 的数据库 schema 变更规则，避免 Alembic 迁移与 `backend/database/migrations.py` 的 first-boot 兜底逻辑分叉。

## 主路径

- 新增表、索引、约束或列时，必须新增 Alembic revision，并实现 `upgrade()` 与 `downgrade()`。
- 本地验证使用：

```bash
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini downgrade -1
python -m alembic -c alembic.ini upgrade head
```

- GitHub Actions 已运行 Alembic 升级和降级检查；不要新增只在 `sync_migrate_db_schema()` 中存在的长期 DDL。

## First-Boot Fallback

`backend/database/migrations.py` 的 `sync_migrate_db_schema()` 只用于以下场景：

- 本地首次启动时创建缺失的基础结构。
- 旧开发库没有完整 Alembic 历史时做兼容补列。
- 保障离线/开发环境在没有手动运行 Alembic 时能启动。

它不是新 schema 的权威来源。新增列如果必须同步加入 fallback，应同时在同一个变更中加入 Alembic revision，并在 PR 说明里解释 fallback 的删除窗口。

## 现有 Fallback 盘点

截至 2026-05，`sync_migrate_db_schema()` 仍包含若干 `_add_col` 兼容路径，主要覆盖：

- `conversations` / `messages` 的类型、状态、归档、任务恢复字段。
- `paper_questions` 的展示、题型、难度、解析和用户隔离字段。
- `papers`、`study_archives`、`questions` 等旧表的 `user_id` 兜底。
- `tasks` 的事件序列、请求、结果、错误、trace 和时间字段。
- `generated_files`、`study_archives` 的用户和更新时间字段。

这些 fallback 应随对应 Alembic revision 稳定后逐步收敛。新增迁移时优先回查这些字段是否已经进入 Alembic，避免继续扩大双轨 DDL。
