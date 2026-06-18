# 错题本：间隔重复复习(SRS) + 知识点掌握度可视化 - 实施方案

**优先级**: P1, 新功能/学习闭环
**状态**: 已实现（2026-06-08）

本轮落地:
- 后端给 `wrong_questions` 表补 5 个 SRS 调度列，新增 SM-2 纯算法模块 `backend/core/srs.py`，
  并在现有 `/wrongbook` 路由下加「复习队列 / 复习评分 / 掌握度聚合」三个端点。
- 前端引入 recharts，将错题本页改为「错题列表 / 今日复习 / 掌握度」三段切换，新增
  `features/wrongbook/` 切片承载复习会话与掌握度雷达图。
- Dashboard 侧栏已接入「今日待复习 N」入口，并支持 `/wrongbook?tab=review` 直达复习分段。
- 不改动考试批改流程；错题仍仅手动入库。
- 验证覆盖 `backend.tests.test_srs`、错题本仓储测试、Dashboard/Wrongbook 入口回归与前端生产构建。

---

## 问题描述

系统内容生产能力完整（自学资料、组卷、AI 出题、作文批改、知识视频等），但「学习闭环」缺最后一块：
`WrongQuestion` 表早已埋好 `knowledge_point`(索引) 和 `mastery`(0..100, 索引) 两个字段，
却**没有任何服务端逻辑**——

1. `mastery` 全靠前端编辑框手填，错题本只是一个静态列表；
2. **没有复习调度**（无 `next_review`/`interval`/`ease_factor`），无法安排「该复习哪些题」；
3. 没有把掌握度按知识点聚合出来的视图，定位不了薄弱环节。

本方案把错题本从「列表」升级为「科学复习系统」：用 SM-2 间隔重复为每道错题安排复习时间并提供
「今日复习」队列；按知识点聚合掌握度并用雷达图/薄弱点列表呈现，支持对薄弱知识点一键出练习卷。

## 设计决策

| 决策项 | 选择 | 说明 |
|--------|------|------|
| 错题入库方式 | 仅手动添加 | **不改考试批改流程**；错题仅通过试卷详情页/错题本手动加入。掌握度与 SRS 仅覆盖手动收藏的错题 |
| 复习算法 | SM-2 | 经典间隔重复，纯函数实现，4 档评分（忘记/模糊/记得/简单） |
| SRS 作用范围 | 仅 `WrongQuestion` | 不扩展到全部答题记录 |
| 知识点分组 | `knowledge_point` 字符串精确分组 | free-text，仅做 trim/空白归一，暂不做同义词归并 |
| 掌握度更新 | 复习评分时自动调整 | 忘记 -20 / 模糊 +5 / 记得 +15 / 简单 +25，clamp 0..100，保留手动覆盖 |
| 可视化图表库 | recharts | 兼容 React 19 + Radix + Tailwind，后续仪表盘可复用 |
| SRS 字段存储 | 直接加列到 `wrong_questions` | 该表已是 per-(user,question) 且有唯一约束，无需新表 |

## 评分档 → SM-2 映射

| 评分（前端） | rating | SM-2 质量分 q | 掌握度增量 |
|------|------|------|------|
| 忘记 | again | 2 | -20 |
| 模糊 | hard  | 3 | +5  |
| 记得 | good  | 4 | +15 |
| 简单 | easy  | 5 | +25 |

---

## Part 1 — SRS 复习引擎（后端）

### 1.1 迁移 `0006_wrongbook_srs.py`（新建）
`backend/database/alembic/versions/0006_wrongbook_srs.py`，`down_revision = "0005_exam_sessions"`。
沿用 0005 的幂等风格（`sa.inspect`），新增一个 `_column_exists` 守卫，给 `wrong_questions` 加列：
- `ease_factor` Float, `server_default="2.5"`
- `interval_days` Integer, `server_default="0"`
- `repetitions` Integer, `server_default="0"`
- `next_review_at` DateTime, nullable
- `last_reviewed_at` DateTime, nullable

新增索引：`ix_wrong_questions_next_review`(`next_review_at`) 与复合
`ix_wrong_questions_user_next_review`(`user_id`,`next_review_at`)（驱动「到期队列」查询）。
`downgrade()` 反向 drop 列/索引。

### 1.2 ORM 模型
`backend/database/schema.py` 的 `WrongQuestion`（约 593-610 行）补上以上 5 个列定义，与迁移保持一致。

### 1.3 SM-2 纯算法模块（新建）
`backend/core/srs.py`（与已有 `backend/core/subjects.py` 同级，core 放跨域纯逻辑）。

```
RATING_QUALITY = {"again": 2, "hard": 3, "good": 4, "easy": 5}
MASTERY_DELTA  = {"again": -20, "hard": 5, "good": 15, "easy": 25}
```

`schedule_review(*, rating, ease_factor, interval_days, repetitions, now) -> dict`：
- q<3：`repetitions=0`、`interval=1`；否则 reps 0→1、1→6、其余 `round(interval*ease)`，`repetitions+=1`
- `ease_factor = max(1.3, ease + (0.1 - (5-q)*(0.08 + (5-q)*0.02)))`
- 返回 `{ease_factor, interval_days, repetitions, next_review_at=now+interval天}`
- 掌握度增量另算：`new_mastery = clamp(mastery + MASTERY_DELTA[rating], 0, 100)`

### 1.4 仓储扩展
`backend/database/repositories/content/wrongbook.py`：
- `_row_to_dict`：补输出 SRS 字段（`ease_factor`/`interval_days`/`repetitions`/
  `next_review_at`/`last_reviewed_at` 的 isoformat）。
- `upsert_wrong_question`（新建分支）：初始化 `ease_factor=2.5`、`interval_days=0`、
  `repetitions=0`、`next_review_at=now`（新错题立即可复习）。
- 新增 `list_due_reviews(*, user_id, subject=None, limit=50, now=None)`：查
  `next_review_at IS NULL OR <= now`，按 `next_review_at` 升序；再用现有
  `get_question_cache(question_ids=[...])`（`repositories/question/question_cache.py:52`）
  富化题干/答案/选项，便于前端直接渲染复习卡。
- 新增 `record_review(*, user_id, question_id, rating)`：载入行 → 调 `core.srs.schedule_review`
  + 掌握度更新 → 写回 `next_review_at`/`last_reviewed_at=now` → 返回更新后 dict。
- 新增 `aggregate_mastery_by_knowledge_point(*, user_id, subject=None)`：按 dashboard 的
  「取行后 Python 聚合」风格，分组出 `subjects[]` 与 `knowledge_points[]`，各含
  `count / avg_mastery / min_mastery / due_count`。

### 1.5 API 端点
`backend/api/wrongbook.py`（沿用现有 router，无需新文件）：
- `GET /wrongbook/review/queue?subject=&limit=` → `{items:[卡片+SRS+题目内容], due_count, total}`
- `POST /wrongbook/review/{question_id}`，body `{rating: again|hard|good|easy}`（校验取值）→
  `{success, item, next_review_at}`
- `GET /wrongbook/mastery?subject=` → `{subjects:[...], knowledge_points:[...]}`

---

## Part 2 — 前端

### 2.1 依赖
`frontend/package.json` 增加 `recharts`（兼容 React 19）。

### 2.2 API 层
`frontend/src/api/wrongbook.ts`：
- `WrongQuestion` 类型补 SRS 字段（`next_review_at?`/`interval_days?`/`ease_factor?`/
  `repetitions?`/`last_reviewed_at?`）。
- 新增 `getReviewQueue(params)`、`recordReview(questionId, rating)`、
  `getMastery(params)` 三个函数并挂到 `wrongbookApi`。

### 2.3 功能切片（新建，遵循 frontend/AGENTS.md「页面薄、逻辑进 features/」）
`frontend/src/features/wrongbook/`：
- `hooks/useReviewQueue.ts`、`hooks/useMastery.ts`（TanStack Query，queryKey
  `['wrongbook','review',subject]` / `['wrongbook','mastery',subject]`，仿
  `features/generation/questionLibrary/hooks/useQuestionLibrary.ts`）。
- `components/ReviewSession.tsx`：展示当前到期卡（题干 + 用户备注）→「显示答案」揭示 →
  4 个评分按钮（忘记/模糊/记得/简单 → again/hard/good/easy）→ `recordReview` 后推进下一张；
  顶部进度 n/总数，结束态。会话内卡片索引用本地 `useState` 即可（无需 Zustand）。
- `components/MasteryPanel.tsx`：学科下拉 + recharts `RadarChart`（各知识点 `avg_mastery`）
  + 「薄弱知识点」列表（按 `avg_mastery` 升序），每项复用现有
  `wrongbookApi.createPracticePaper({ knowledge_point })` 一键生成练习卷。

### 2.4 页面改造
`frontend/src/pages/WrongbookPage.tsx` 改为薄壳 + 分段切换：**错题列表 | 今日复习 | 掌握度**。
- 「错题列表」沿用现有列表/编辑/生成练习卷逻辑。
- 「今日复习」挂 `ReviewSession`，标题处显示到期数徽标（来自 review/queue 的 `due_count`）。
- 「掌握度」挂 `MasteryPanel`。

### 2.5（可选）仪表盘入口
`frontend/src/pages/DashboardPage.tsx` 侧栏加一张「今日待复习 N」小卡，链接到错题本复习页。
非必需，可作为收尾增强。

---

## 关键复用点（避免重复造轮子）
- `get_question_cache`（`repositories/question/question_cache.py:52`）：按 id 批量取题干/答案，
  富化复习卡。
- `createPracticePaper` / `POST /wrongbook/practice`（已存在）：薄弱知识点直接出练习卷。
- dashboard 的「select 取行 → Python dict 聚合」风格用于掌握度聚合。
- 前端 axios 单例 + `useQuery/useMutation` 既有范式；新页走既有「分段切换」而非新增路由。

## 已实现时确认的小点
- 复习卡题干渲染：queue 接口已带 `question` 内容；前端用现有
  `@/components/shared/Markdown` 渲染，答案默认折叠。

---

## 测试与验证

### 后端
1. `alembic upgrade head` 应成功新增 5 列与索引（SQLite 本地库）。
2. 新增 `backend/tests/test_srs.py`：覆盖 `schedule_review` 的 again 重置、good 序列
   (1→6→6*ease)、ease 下限 1.3、掌握度 clamp。
3. 仓储测试：`record_review("good")` 后 `next_review_at` 前移约 1 天、`mastery+15`；
   `list_due_reviews` 只返回到期项。
4. 手测：`POST /wrongbook` 建错题 → `GET /wrongbook/review/queue` 应立即到期 →
   `POST /wrongbook/review/{id}{"rating":"good"}` → 再查队列该题已不在 → `GET /wrongbook/mastery`
   该知识点 `avg_mastery` 上升。

### 前端
1. `npm run lint` 与 `npm run build` 通过（含 recharts）。
2. Vitest：`ReviewSession` 评分推进逻辑（含队列空/结束态）。
3. 浏览器跑通：错题本三个分段切换；今日复习评分后卡片推进、徽标递减；掌握度雷达图渲染、
   薄弱点一键生成练习卷跳转 `/papers/:id`。

## 落地顺序
1. 后端：迁移 → 模型 → `core/srs.py` → 仓储 → 端点 → 后端测试。
2. 前端：依赖 → api → features 切片 → 页面分段 →（可选）仪表盘卡 → 前端测试。
