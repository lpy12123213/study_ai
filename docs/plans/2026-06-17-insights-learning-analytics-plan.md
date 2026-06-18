# 学情分析看板（Learning Analytics） - 实施方案

**优先级**: P1, 新功能/学习闭环
**状态**: 已实现（2026-06-08）
**目标**: 把系统已采集但**从未分析**的学生表现数据（考试成绩、客观/主观构成、按题型正确率、错题掌握度、作文得分、学习活跃度）做成一个独立的「学情分析」看板页，用趋势图/分布图呈现，补上整个产品最明显的短板。

---

## Context / 问题描述

系统内容生产能力很完整，但**学习数据零分析**：

- 唯一的分析面 `backend/api/dashboard.py`（`/dashboard/stats`，71-87 行）**只查 `Task` 与 `GeneratedFile`**，统计的全是任务运维指标（任务数、完成率、平均耗时、导出数）。
- 前端 `frontend/src/pages/DashboardPage.tsx`（路由见 `router/index.tsx:36,148`）甚至带**硬编码占位内容**：「资料来源」列表（235-239 行）和完全静态的「任务时间线」。
- 与此同时，大量学生表现数据已落库却无人聚合：
  - `ExamResult`（schema.py:133-157）：`score_ratio`、`objective_correct/total`、`subjective_score/max`、`breakdown_json`。
  - `StudentAnswer`（100-130）：`question_type`、`is_correct`、`score/max_score`。
  - `WrongQuestion`（593-610）：`subject`、`knowledge_point`、`mastery`(0..100)。
  - `EssayEvaluation`（676-705）：`score_total/score_max`、`essay_type`、`created_at`。
  - `LearningPlanItem`（527-544）：`completed`、`completed_at`、`due_at`。

本方案把这些数据聚合成一个新页面 **「学情分析」(`/insights`)**，与现有任务运维仪表盘并列，互不干扰。

## 关键约束（已核实）

`ExamResult.breakdown_json` 由 `backend/generation/exam_grading/orchestrator.py:68-77` 构造，结构为 `{question_id, question_type, score, max_score, is_correct, grading}` —— **不含 `knowledge_point`**。故：

- **按题型正确率**：可直接从 `StudentAnswer.question_type` + `is_correct` 聚合（v1 采用）。
- **按知识点掌握度**：v1 直接取 `WrongQuestion`（自带 `knowledge_point` + `mastery`）。
- 「考试结果按知识点拆解」需 `question_id → knowledge_point` 关联（经 question cache / paper questions），**列为后续增强，v1 不做**。

## 设计决策

| 决策项 | 选择 | 说明 |
|--------|------|------|
| 页面形态 | **新建独立页** `/insights`「学情分析」 | 不动现有任务运维仪表盘；导航 `navGroup='secondary'`，与「仪表盘」并列 |
| 聚合 SQL 落点 | 新建 `repositories/analytics/insights.py` 薄仓储层 | 跨 exam/essay/wrongbook/plan 多域，单独成包比塞进 `exam/` 清晰；纯只读、可单测 |
| 聚合风格 | 「窗口取行 → Python 聚合」 | 沿用 `dashboard.py:89-135` 既有风格 |
| 时间窗口工具 | 复用 `dashboard.py` 的 `_window`/`_parse_iso_date` | 直接 import；若第三处复用再抽 `backend/api` 共享工具 |
| 接口形态 | 单个组合端点 `GET /insights/overview` | 与 `dashboard/stats` 一致，返回 4 个子区块 |
| `subject` 过滤 | v1 仅作用于错题/作文面板（自带 subject 列） | `ExamSession` 无 subject 列；考试按 subject 过滤列为后续 |
| 图表库 | `recharts` | 与已规划的错题 SRS（`nextstep/wrongbook-srs-mastery-plan.md`）一致；**谁先落地谁加依赖**，互不重复造端点 |
| 与错题 SRS 关系 | 独立实现，知识点面板**深链到 `/wrongbook`** | 不依赖 SRS 是否已建；避免重复 `GET /wrongbook/mastery` |

---

## 实施清单

- [x] 后端：新建 `backend/database/repositories/analytics/insights.py`（4 个只读聚合函数）
- [x] 后端：新建 `backend/api/insights.py`（`/insights/overview` + `/insights/export`）
- [x] 后端：`backend/api/domains/workspace.py` 注册 `insights_router`
- [x] 后端：新建 `backend/tests/test_insights.py`
- [x] 前端：`frontend/package.json` 增加 `recharts`
- [x] 前端：新建 `frontend/src/api/insights.ts`
- [x] 前端：新建 `features/insights/`（hooks + 5 个面板组件）
- [x] 前端：新建 `frontend/src/pages/InsightsPage.tsx`（薄壳）
- [x] 前端：`router/routes.config.ts` + `router/index.tsx` 注册 `/insights` 路由与导航
- [x] 前端：`DashboardPage.tsx` 把硬编码「资料来源」占位（235-239 行）替换为真实「学情速览」小卡，链接到 `/insights`
- [x] 前端：新增 `WrongbookMasteryPanel` 的 Vitest
- [x] 端到端验证（播种 → 打接口 → 看页面 → 构建）

---

## Part 1 — 后端

### 1.1 聚合仓储（新建）`backend/database/repositories/analytics/insights.py`

纯只读函数，签名 `(session, user_id, dt_from, dt_to, subject=None)`，返回 plain dict（窗口取行后 Python 聚合）：

- `exam_insights`：`ExamResult` 关联 `ExamSession`（窗口内、`status='submitted'`）→
  - `trend`：按天聚合 `score_ratio` 均值 `[{date, score_ratio, count}]`
  - `objective` / `subjective`：累加 `objective_correct/total`、`subjective_score/max`
  - `accuracy_by_type`：按 `StudentAnswer.question_type` 分组的 `{correct, total, ratio}`
  - `recent`：最近 N 场 `[{session_id, paper_name, score_ratio, submitted_at}]`
- `essay_insights`：`EssayEvaluation` →`trend`（按天 `score_total/score_max` 均值）、`by_type`（按 `essay_type` 分组均分）。`subject` 命中此处。
- `wrongbook_insights`：`WrongQuestion` →`total`、`mastery_distribution`（桶 0-25/26-50/51-75/76-100 计数）、`weak_points`（按 `knowledge_point` 聚合 `avg_mastery` 升序 top 10）。`subject` 命中此处。
- `activity_insights`：`active_days`（有交卷/作文/计划完成的去重日期数）、`current_streak`（截至今日连续活跃天数）、`plan_completion`（`LearningPlanItem` 关联 `LearningPlan` on `user_id`：`{completed, total, overdue}`）。

> 活跃日定义：当天存在「交卷 `ExamSession.submitted_at`」「作文 `EssayEvaluation.created_at`」或「计划项 `completed_at`」任一即计；streak 为从今天往前的连续活跃天数。

### 1.2 API（新建）`backend/api/insights.py`

仿 `dashboard.py` 结构：`APIRouter(prefix="/insights", tags=["insights"], dependencies=[Depends(require_auth)])`。

- `GET /insights/overview?days=&from=&to=&subject=`：从 `require_auth` 取 `user_id`（空则 401）；`dt_from,dt_to=_window(...)`（import 自 `backend.api.dashboard`）；`async with async_session_maker()` 调 4 个仓储函数；返回 `{from, to, exams{...}, essays{...}, wrongbook{...}, activity{...}}`。
- `GET /insights/export`：调 `overview` → 拍平成 `metric,value` CSV（复用 `dashboard.py:159-181` 模式），文件名 `insights-YYYY-MM-DD.csv`。

### 1.3 注册 `backend/api/domains/workspace.py`

`from backend.api.insights import router as insights_router`（~17 行）+ `router.include_router(insights_router)`（35 行后）。学情分析属 workspace 域，与 `exam_router`(:24)、`wrongbook_router`(:35) 同域。

---

## Part 2 — 前端

### 2.1 依赖 `frontend/package.json`
增加 `recharts`（兼容 React 19）。若错题 SRS 已先加则跳过。

### 2.2 API 层（新建）`frontend/src/api/insights.ts`
`InsightsOverview` + 子类型；`getInsightsOverview(params?)`→`apiClient.get('/insights/overview',{params})`；`downloadInsightsCsv(params?)` 经 `downloadBlob` —— 形状照抄 `api/dashboard.ts`。

### 2.3 功能切片（新建）`frontend/src/features/insights/`
- `hooks/useInsights.ts`：`useQuery({ queryKey:['insights','overview',params], queryFn })`。
- `components/`：
  - `ExamTrendPanel.tsx`：recharts `LineChart`（`score_ratio` 趋势）
  - `AccuracyByTypePanel.tsx`：`BarChart`（按题型正确率）
  - `WrongbookMasteryPanel.tsx`：掌握度分布条 + 薄弱知识点列表（深链 `/wrongbook`）
  - `EssayPanel.tsx`：作文得分趋势 + 按类型
  - `ActivityPanel.tsx`：活跃天数 / 连续天数 / 计划完成度
  - 统一用 shadcn `Card`。

### 2.4 页面（新建）`frontend/src/pages/InsightsPage.tsx`
薄壳：时间窗口选择（7/30/90 天，仿 DashboardPage）+ 导出 CSV `Button` + 渲染 5 个面板。逻辑进 feature 切片（遵循 `frontend/AGENTS.md`）。

### 2.5 路由与导航（3 处修改）
- `router/routes.config.ts`（88 行附近）：`defineRoute({ id:'insights', path:'/insights', label:'学情分析', icon: TrendingUp, layout:'standard', sidebar:true, navGroup:'secondary', command:true })`（`TrendingUp` 从 lucide 引入）。
- `router/index.tsx`：`const InsightsPage = lazy(() => import('@/pages/InsightsPage'))`（~36 行）+ 路由项 `{ path:'insights', element: load(InsightsPage), handle: handle('insights') }`（~148 行）。

### 2.6 仪表盘占位替换 `frontend/src/pages/DashboardPage.tsx`
把硬编码「资料来源」块（235-239 行）替换为真实「学情速览」小卡（如最新成绩比 + 头号薄弱点），链接 `/insights`。

---

## 关键复用点（避免重复造轮子）

- `dashboard.py` 的 `_window` / `_parse_iso_date`（22-44 行）：时间窗口解析，直接 import。
- `dashboard.py` 的 CSV 拍平模式（159-181 行）：`/insights/export` 照搬。
- `api/dashboard.ts`：前端 API client + `downloadBlob` 范式。
- `DashboardPage.tsx`：7/30/90 天切换 + `useQuery` + summary card 布局直接复用。
- `repositories/exam/exam_sessions.py`：`ExamSession/StudentAnswer/ExamResult` 字段读取参考。
- **不重复** `nextstep/wrongbook-srs-mastery-plan.md` 计划的 `GET /wrongbook/mastery`；知识点面板深链错题本即可。

---

## 测试与验证

### 后端
- 新建 `backend/tests/test_insights.py`：`IsolatedAsyncioTestCase` + 临时 sqlite（`create_async_engine` + `Base.metadata.create_all`，仿 `test_exam_sessions.py`）。播种 `ExamSession/ExamResult/StudentAnswer/WrongQuestion/EssayEvaluation/LearningPlanItem` 后断言：trend 按天分桶、`accuracy_by_type` 计数、`mastery_distribution` 分桶、`current_streak` 连续天数。
- 回归：`python -m unittest discover -s backend/tests -p "test_*.py"`。

### 前端
- `frontend/src/features/insights/components/__tests__/WrongbookMasteryPanel.test.tsx`：mock 数据渲染，断言分布条与薄弱点列表。
- `npm run lint` + `npm run build`（含 recharts）。

### 端到端
1. 播种：同一 `user_id` 下建 1 场考试会话+结果、1 条作文评估、1 条错题。
2. `GET /insights/overview?days=30`（带鉴权）→ 4 个子区块有数据；`GET /insights/export` 返回 CSV。
3. 浏览器开 `/insights`：折线/柱状图渲染；`DashboardPage` 的「学情速览」卡能深链过来。

---

## 落地顺序

1. 后端：仓储 `analytics/insights.py` → API `insights.py` → workspace 注册 → 后端测试。
2. 前端：recharts 依赖 → `api/insights.ts` → features 切片 → `InsightsPage` → 路由/导航 → DashboardPage 占位替换 → Vitest。

## 风险与缓解

- **空数据**：新用户各表为空 → 各面板渲染「暂无数据」空态，不报错（聚合函数对空列表返回零值结构）。
- **与错题 SRS 撞依赖/概念**：约定 recharts 谁先加谁负责；知识点掌握度只在错题本算一次，本页深链复用，不另起端点。
- **考试 subject 过滤缺列**：v1 文档化为「subject 仅作用于错题/作文」，避免给出误导性的考试学科筛选。
- **跨 API 模块 import 工具**：`_window` 等暂从 dashboard import；第三处复用时再抽公共工具，避免过早抽象。
