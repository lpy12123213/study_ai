# 本地题库全文检索（Question Library FTS） - 实施方案

**优先级**: P1, 增强/检索闭环
**状态**: 已实现（2026-06-08）
**目标**: 给本地题库建 FTS5 并纳入全局搜索，让用户能检索自己最常维护的题库（题干/答案/解析）。

## Context / 问题描述
全局搜索 `search_fulltext`（`repositories/system/search.py:43-223`）默认只覆盖 `{conversation, paper, study_archive}`（63 行）；HTTP 入口 `GET /search`（`backend/api/system.py:253-274`，无独立 `api/search.py`）。题库是用户最常维护的内容，却无 FTS。

## 关键事实（已核实）
- FTS 范式集中在 `migrations.py:246-411`（`sync_migrate_db_schema` 内，`exec_driver_sql` 裸 DDL，`CREATE ... IF NOT EXISTS` 守卫，缺 FTS5 静默跳过）。代表 `paper_questions_fts`（259-357）：UNINDEXED 元数据列 + 1 个 indexed `content` 列；**手动 rowid（非 `content=`）**；AFTER INSERT/DELETE/UPDATE 三触发器；`tokenize='unicode61 remove_diacritics 2'`（**无 jieba/ICU，CJK 按单字切分**）；backfill 由 `_fts_has_any(...)` 守卫。
- 数据模型：题面文本在**全局** `QuestionCache`（`schema.py:266-291`，PK `question_id`，含 `stem/answer/analysis/subject/knowledge_point`）；归属在**按用户** `QuestionLibraryItem`（`schema.py:305-338`，复合 PK `(user_id, question_id)`，含 `hidden/starred/origin`）。→ FTS 索引 `question_cache` 文本、按 `question_library` 归属 + 过滤。
- 迁移走 `migrations.py`（`engine.py:117-118` 先 `create_all` 再跑它），**非 Alembic**；幂等由 `IF NOT EXISTS` + `_fts_has_any` 保证（`test_task_duration_aggregates.py:215` 跑两遍验证）。
- 结果行形状（仿 paper 块）：`type / 深链 ref / title / snippet(<fts>, <content列序>, '','','…',18) / score=bm25`；前端 `SearchPage` 用 ``/`` 高亮。

## 设计决策
| 决策项 | 选择 | 说明 |
|--------|------|------|
| FTS 表 | 新建 `question_library_fts` | UNINDEXED `user_id, question_id, subject, knowledge_point, hidden` + indexed `content` |
| rowid | 不用 `content_rowid`（复合 PK 无单一 int id） | 触发器按 `(user_id, question_id)` 列匹配增删 |
| content | `stem‖\n‖answer‖\n‖analysis`（子查询取自 `question_cache`） | 同 paper 范式拼接 |
| tokenizer | `unicode61 remove_diacritics 2` | 与现有一致，CJK 单字 |
| 触发器 | `question_library` AFTER INSERT/UPDATE/DELETE + `question_cache` AFTER UPDATE | 后者解决「cache 晚于 library 更新」的内容陈旧 |
| 过滤隐藏 | 存 `hidden` 列，默认 `hidden=0` | dispatch 自包含 |

## 实施清单
- [x] `migrations.py`（FTS 块内）：新增 `question_library_fts` 虚表 + 3+1 触发器 + `_fts_has_any` 守卫的 backfill（join `question_library ⋈ question_cache`）
- [x] `repositories/system/search.py`：63 行默认集加 `"question"`；新增 `if "question" in want:` FTS 查询块（`WHERE user_id=:user_id AND hidden=0`）+ LIKE 兜底块；结果行 `{type:'question', question_id, title, snippet, score}`
- [x] `backend/api/system.py:256`：`types` 文档串补 `question`
- [x] 前端 `frontend/src/api/search.ts`：`SearchResult` 联合类型加 `question` 变体 + `question_id`
- [x] 前端 `SearchPage.tsx`：`typeLabel` 加「题目」；`openResult` 加 `question → /question-library?focus=<question_id>`；输入框 placeholder 补「题库」
- [x] 前端 `QuestionLibraryPage.tsx`：识别 `?focus=<qid>` 打开该题详情（小改）
- [x] 测试 `backend/tests/test_question_library_fts.py`：播种 cache+library→跑迁移→按题干 token 命中、隐藏不出、更新 cache 后内容刷新、迁移跑两遍幂等

## 验证
1. 播种一题（cache + library item）→ `GET /search?q=<题干token>&types=question`（带鉴权）→ 命中且 snippet 高亮。
2. 隐藏该题 → 不再出现；改 `question_cache.analysis` → 再搜内容已更新。
3. `SearchPage` 搜索显示「题目」类结果 → 点击跳 `/question-library` 并聚焦该题。

## 风险
- CJK 单字切分召回偏宽：与现有 FTS 行为一致，查询构造器已按 CJK run 加引号短语匹配，保持一致即可。
- 复合 PK 无 int rowid：触发器按 `(user_id, question_id)` 删/插，避免 rowid 错配。
- `question_cache` 与 `question_library` 时序：加 cache AFTER UPDATE 触发器消除陈旧。
