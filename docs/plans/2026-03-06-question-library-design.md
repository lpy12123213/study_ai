# 本地题库（爬取自动入库 + AI 评分优选 + AI 出题）设计

**状态：** 已确认（用户同意方案 2：新增题库表 + 复用 `question_cache`）

## 目标

1. **爬取题目自动保存到本地**：用户在“本地题库”页面触发爬取后，结果自动入库，不需要手动收藏。
2. **本地浏览**：爬取题与 AI 生成题统一在一个列表浏览；AI 题目有明显标识。
3. **AI 评分 + 自动优选**：后台可随时对入库题目进行评分；低分题自动隐藏（默认阈值 70，可配置）。
4. **AI 出题（A/B）**：根据“学科 + 知识点/主题 + 难度 + 题型 + 数量”生成题目；可选择使用该主题的**自学资料（StudyArchive）**作为上下文，提高生成质量；AI 题必须包含解析。

## 非目标（本期不做）

- 不做“刷题记录/错题本/掌握度追踪”（只做题库存储与浏览）。
- 不做组卷网题目答案/解析的自动离线保存（爬取题只存题干与元数据）。
- 不做复杂的向量检索/Embedding（先用结构化抽取 + 规则去重 + LLM 评审）。

## 数据与存储

### 现有：`question_cache`（继续复用）

用途：存题目内容快照（题干/答案/解析/元数据），按 `question_id` 复用，减少重复抓取。

本需求中的写入策略：

- **爬取题**：写 `stem + 元数据`，不写 `answer/analysis`。
- **AI 题**：写 `stem + answer + analysis + 元数据`（`source_url` 为空），并写入 AI 评分结果（可选）。

> 现有代码：`backend/database/schema.py` 的 `QuestionCache` + `backend/database/repositories/question_cache.py` 的 `upsert_question_cache()`

### 新增：`question_library`（题库条目表：按用户维度）

目的：把“题库语义”从“内容缓存”中分离出来，支持：

- 多用户隔离（`user_id`）
- 来源标识（爬取/AI）
- 隐藏/显示
- AI 评分与评审结果持久化

建议字段（SQLite / SQLAlchemy）：

- `id`（Integer PK）
- `user_id`（String(64) index）
- `question_id`（String(50) index）
- `subject`（String(100) index）
- `origin`（String(20)，`crawled|ai`）
- `hidden`（Integer/Boolean，默认 0）
- `ai_score`（Integer，可空）
- `ai_verdict`（String(20)，可空：好题/普通题/差题）
- `ai_dimensions_json`（Text：JSON string，维度打分与说明）
- `ai_summary`（Text：简评）
- `created_at` / `updated_at`

约束：

- 唯一索引：`(user_id, question_id)`，避免同用户重复入库。
- 二级索引：`(user_id, subject, hidden)` + `(user_id, origin)`，便于列表筛选。

实现备注：

- 为了让“upsert”更简单，可以直接把 `(user_id, question_id)` 设为**复合主键**（代替单独的 `id` 主键）；两种方案都可以，按实现便利性选择即可。

### AI 题 `question_id` 规则

爬取题沿用组卷网 `question_id`。

AI 题生成本地 ID（保证长度 <= 50）：

- `ai_<yyyyMMddHHmm>_<uuid8>`（例如：`ai_202603061230_a1b2c3d4`）

## 后端 API 设计（FastAPI）

新增 router：`/api/question-library/*`

### 1) 爬取并入库

`POST /api/question-library/crawl`

输入（示例）：

```json
{
  "subject": "高中数学",
  "edu_level": "高中",
  "query": "函数 单调性",
  "difficulty": "中等",
  "limit": 30,
  "max_pages": 2,
  "min_quality_score": 0
}
```

行为：

1. 调用现有 `ZujuanCrawler.search_by_keyword(parse_content=True)` 获取含 `stem` 的题目列表（预览题干）。
2. 对每题：
   - `upsert_question_cache()`：写入 `stem + 元数据`（不写答案解析）
   - `upsert_question_library_item()`：入库（`origin=crawled`，`hidden=0`，评分字段空）
3. 返回：插入/更新统计 + 最新列表（可分页化，第一版可返回本次入库 items）。

### 2) 题库列表

`GET /api/question-library/items`

查询参数：

- `subject?`
- `origin?=crawled|ai`
- `hidden?=0|1|all`（默认 0）
- `min_score?`（默认：阈值 70 的“优选视图”可由前端实现）
- `q?`（模糊搜索 stem）
- `sort?=updated_at|ai_score` + `order?=desc|asc`
- `limit?` + `offset?`

返回：题库条目 + 题干预览（从 `question_cache.stem` 关联查询）

### 3) 查看题目详情

`GET /api/question-library/items/{question_id}`

返回：

- `library_item`（来源/隐藏/评分）
- `question_cache`（stem；若 AI 题则含 answer/analysis）

### 4) 手动隐藏/取消隐藏

`POST /api/question-library/items/{question_id}/hide`
`POST /api/question-library/items/{question_id}/unhide`

### 5) 手动触发评分（可选）

`POST /api/question-library/score`

用途：当后台没有 `.env` key 时，允许前端带 `X-LLM-API-Key` 触发评分一批（仍然不持久化 key）。

输入：

```json
{"subject":"高中数学","limit":50,"only_unscored":true}
```

## 后台评分（“随时进行”）

在 FastAPI `lifespan` 启动一个后台协程 worker（可用 env 开关控制）：

- `QUESTION_LIBRARY_AUTO_SCORE=1`（默认开/关按你偏好；建议默认关，避免没 key 时刷日志）
- `QUESTION_LIBRARY_HIDE_THRESHOLD=70`（默认 70）
- `QUESTION_LIBRARY_SCORE_BATCH=20`
- `QUESTION_LIBRARY_SCORE_INTERVAL_S=20`

Worker 逻辑：

1. 拉取一批 `origin=crawled` 且 `ai_score is NULL` 的条目（按时间/subject）。
2. 从 `question_cache` 取 stem（必要时补抓，但本期不强制）。
3. 调用 LLM 评分（复用“好题鉴别”的 rubric，输出 JSON：`overall_score/verdict/dimensions/summary`）。
4. 写回 `question_library`：
   - `ai_score/ai_verdict/ai_dimensions_json/ai_summary`
   - 若 `ai_score < threshold`，则 `hidden=1`（自动隐藏）

> 注意：后台 worker 只能用 `.env` 的 key（因为浏览器 header key 只在请求上下文有效）。

## AI 出题：Spec Tree Search 架构

目标：不是“直接出题再修”，而是先搜索“什么题值得出”，把新意放在 `QuestionSpec` 的结构设计上，再把高价值 spec 落成题干。

### 总体：Spec Tree Search

核心思想：

1. 先把 `StudyArchive.markdown` 压成一个紧凑的 `SourcePack`
2. 在 `QuestionSpec` 空间里做分层搜索，而不是直接写题
3. 对高分 spec 才生成正式 Draft
4. Draft 再经过独立求解、歧义检查、质量评审

### 搜索树分层

每道题的 spec 搜索固定 4 层，避免搜索树过深：

1. **Skill Expansion**
   - 先选“要考什么能力”
   - 例如：概念辨析、性质判定、计算推导、条件反推、错误辨认

2. **Reasoning Pattern Expansion**
   - 再选“要走什么推理结构”
   - 例如：单步判断、多步推导、分类讨论、构造反例、参数变化分析

3. **Trap Expansion**
   - 决定“误区/陷阱设计”
   - 例如：忽略定义域、把必要条件当充分条件、符号条件漏讨论、边界点误判

4. **Surface Form Expansion**
   - 最后才决定“题干怎么写”
   - 例如：选择题 / 填空 / 解答；是否带简短情境；是否限制语言风格

### 节点评分函数

每个 spec 节点在扩展时都会打一个中间分，驱动 beam search：

```text
spec_score =
  difficulty_match_weight * difficulty_match
  + novelty_weight * novelty
  + skill_coverage_weight * skill_coverage
  + solvability_weight * solvability
  - ambiguity_penalty * ambiguity_risk
  - template_penalty * template_similarity
```

解释：

- `difficulty_match`：是否贴合目标难度
- `novelty`：相对本地题库/历史模板是否有新意
- `skill_coverage`：是否真正考到了目标能力
- `solvability`：是否可写出清晰唯一答案
- `ambiguity_risk`：是否容易多解/误读
- `template_similarity`：是否太像旧题换皮

### 搜索过程

1. **Knowledge Distiller**
   - 输入：`StudyArchive.markdown` + 学科/主题/难度/题型
   - 输出：
     - `facts[]`
     - `skills[]`
     - `common_mistakes[]`
     - `forbidden_patterns[]`

2. **Root Seeding**
   - 生成若干初始 spec seed（例如 4~6 个）

3. **Beam Expansion**
   - 按 4 层树依次扩展
   - 每层对候选 spec 打分
   - 只保留 top-k 进入下一层

4. **Draft Realization**
   - 对最终保留下来的 spec，才真正生成题干/答案/解析
   - 每个 spec 生成 2 个 Draft 候选即可，控制成本

5. **Independent Solver**
   - 只看 `stem(+options)`，独立解题
   - 若与 Draft 答案不一致，直接淘汰或修复

6. **Ambiguity Checker**
   - 专门尝试找第二种合理解释、第二条解法导致不同答案、边界条件遗漏

7. **Judge**
   - 复用 `question-evaluate` rubric
   - 输出 `overall_score/dimensions/issues/summary`

8. **Repair / Drop**
   - 对轻微问题做一次定向修复
   - `max_repair_rounds=1`，避免无限循环

9. **Final Selector**
   - 做去重 + 多样性控制
   - 避免最后 5 道题都是同一种推理套路

### 默认 preset：`balanced-creative`

第一版不追求特别激进，采用“轻度激进”的配置：

```yaml
search_preset: balanced-creative
depth: 4
beam_width: 6
expand_budget: 54

skill_branch_factor: 3
reasoning_branch_factor: 4
trap_branch_factor: 2
surface_branch_factor: 2

difficulty_match_weight: 0.24
novelty_weight: 0.24
skill_coverage_weight: 0.18
solvability_weight: 0.18
ambiguity_penalty: 0.26
template_penalty: 0.16

judge_pass_score: 80
difficulty_tolerance: 0.22
solver_consensus_n: 2
max_repair_rounds: 1
drafts_per_spec: 2
```

这组参数的意图：

- 比保守版更愿意探索新的推理结构
- 主要把新意放在 `Reasoning Pattern`，而不是奇怪语境包装
- 仍然严控歧义和模板化

### 为什么选这套而不是更重的 evolutionary 方案

- 比纯流水线更“像系统”，因为它先搜索题目结构
- 比进化算法更容易在现有项目里落地
- 参数虽然多，但可以收敛到一个默认 preset，不需要第一版就把所有旋钮暴露给用户

### 模型分工（可配置）

- `draft_model`：便宜/快（负责 Draft 候选多样性）
- `solver_model`：推理强（负责独立求解）
- `judge_model`：稳定（负责评分与问题定位）

默认可先全部用同一个模型（减少配置复杂度），后续再拆分。

### 持久化

AI 题写入：

- `question_cache`：`stem + answer + analysis + subject + difficulty + knowledge_point + quality_score(=judge overall_score)`
- `question_library`：`origin=ai`，`hidden=0`，写入 AI 评分字段

## 前端 UI 设计（React）

不再走 Figma 流程；直接基于现有 React + Tailwind v4 + Radix 体系设计并实现页面。

### 页面定位：全屏 `Question Library Studio`

新增页面：`/question-library`（Header 加入口：本地题库）

该页面不是普通列表页，而是一个高频工作台。它要在同一个视图里承载：

- 爬取入库
- AI 出题
- 本地浏览
- 评分结果回流
- 长任务实时进度

因此前端采用 **Studio** 方案：

- 保留全站 Header
- 隐藏 HistorySidebar
- 取消内容区 `max-width`
- 页面主体自行管理全屏布局与滚动

### 主体布局：三栏 + 底部运行面板

#### 左栏：筛选与任务入口

左栏承担筛选和发起任务：

- `subject`
- `origin = crawled | ai`
- `hidden = visible | hidden | all`
- `min_score`
- `search`
- `sort = updated_at | ai_score`

左栏顶部放两个主按钮：

- `爬取入库`
- `AI 出题`

参数面板：

- `爬取入库`：学科、关键词、难度、数量、页数
- `AI 出题`：学科、主题/知识点、难度、题型、数量、是否使用自学资料

#### 中栏：题目流（Question Feed）

中栏使用卡片流，而不是普通表格。每张卡片显示：

- 题号 / 标题
- 题干预览（2~4 行）
- 来源 Badge：`爬取题` / `AI出题`
- 状态 Badge：`待评分` / `评分中` / `已隐藏`
- `ai_score`
- 更新时间

交互规则：

- 默认只看 `hidden=0`
- 默认按 `ai_score desc, updated_at desc` 排序
- 单击卡片切换右栏详情
- 未评分题标识 `待评分`

#### 右栏：题目详情与操作区

右栏展示选中题目的完整信息：

- 基础信息：来源、学科、难度、更新时间
- `stem` 全文
- 若 `origin=ai`：展示 `answer + analysis`
- AI 评分维度卡片：`dimensions + summary`
- 操作按钮：`隐藏 / 取消隐藏`

差异化要求：

- AI 题使用强识别 Badge（如 `AI出题`）
- 仅 AI 题显示解析区

#### 底部：Run Panel（实时进度）

页面底部新增固定、可展开的运行面板，专门显示长任务进度。

显示三类任务：

- `爬取入库`
- `AI 出题`
- `手动批量评分`

设计原则：

- 无任务时折叠
- 有任务时自动展开
- 支持同时展示多个任务，但优先突出最新运行中的任务
- 任务完成后保留结果摘要

### 实时进度设计

前端复用现有任务体系，而不是另起一套：

- `useSSE`
- `normalizeSseEnvelope`
- `useTaskStore`
- `TaskPanel` 的时间线思路

统一流程：

1. 发起请求
2. 后端创建/确认 `taskId`
3. 前端订阅 SSE
4. 事件写入 `task store`
5. `Run Panel` 实时渲染步骤、进度、状态

#### 爬取入库进度

需要实时展示：

- 当前页 / 总页数
- 当前已抓题数
- 已入库数
- 去重数
- 失败数

推荐阶段：

- `初始化`
- `抓取页面`
- `解析题干`
- `写入题库`
- `完成`

#### AI 出题进度

必须显式展示 `Spec Tree Search` 的关键阶段：

- `SourcePack`
- `Spec Search`
- `Draft Realization`
- `Solver`
- `Judge`
- `Save`

同时展示：

- 总体百分比
- 分阶段日志/步骤
- 已通过校验题数
- 已保存题数

#### 手动评分进度

如果用户手动触发评分，Run Panel 展示：

- 待评分数量
- 已评分数量
- 低分自动隐藏数量

评分结果回流后，中栏题目卡片要立即更新 Badge 与可见性。

### 交互流

#### 页面初始化

- 并行加载筛选条件、题库列表、统计摘要
- 默认进入“未隐藏”视图

#### 爬取入库

- 用户提交爬取参数
- 前端创建/接收 `taskId`
- Run Panel 自动展开
- 中栏可先插入“入库中”占位反馈
- SSE 回流后逐步刷新为真实题目

#### AI 出题

- 用户提交出题参数
- Run Panel 进入分阶段进度显示
- 每成功保存一道 AI 题，就立即插入列表
- 新题自动带 `AI出题` 标识

#### 后台/手动评分

- 评分事件到达后更新卡片
- 若低于阈值并自动隐藏，默认列表中即时移除
- 若用户切到“显示隐藏”，仍然可以看到这些题

### 状态模型

题目项状态：

- `idle`
- `saving`
- `ready`
- `scoring`
- `hidden_low_score`

任务状态：

- `queued`
- `running`
- `completed`
- `failed`
- `partial`

关键原则：

- 任务状态与题目状态分离
- 部分失败时，不回滚已经成功入库的题
- UI 要接受“部分成功”

### 前端组件建议

- `QuestionLibraryPage`
- `questionLibrary/QuestionLibraryStudio`
- `questionLibrary/QuestionFilterPane`
- `questionLibrary/QuestionListPane`
- `questionLibrary/QuestionDetailPane`
- `questionLibrary/RunPanel`
- `questionLibrary/CrawlDialog`
- `questionLibrary/GenerateDialog`
- `questionLibrary/hooks/useQuestionLibrary`
- `questionLibrary/hooks/useQuestionLibraryTasks`

### SSE 事件契约（前端最小集合）

统一归一为以下几类：

- `step`
- `progress`
- `item_saved`
- `result`
- `error`
- `done`

含义：

- `step`：更新时间线
- `progress`：更新百分比与阶段
- `item_saved`：把单题结果实时插入/更新到列表
- `result/done`：结束任务并触发一次全量刷新

## 可靠性与风险

- **没有 `.env` Key 时后台评分无法运行**：提供手动触发评分 API（前端带 header）。
- **爬取题干预览可能缺公式/图片**：本期接受；后续可按需补抓 `get_question_detail(stem_mode=html)` 并保存 `stem_html`（需要扩表）。
- **LLM 生成答案不一致**：Solver 校验 + Refine 迭代是关键控制点。
- **成本**：评分 worker 控制 batch 与 interval；出题 pipeline 先小规模（count<=10）。

## 测试策略

后端（unittest）：

- repository：`question_library` 的 upsert/list/hide + user scoping
- scoring：对“评分输出 JSON → 入库 → 自动隐藏”的流程做 mock（patch `chat_completion_text`）
- generation：对“生成输出 schema 校验 + 入库”做 mock（不做真实 LLM）

前端：

- 先不加 e2e，至少保证 `npm run build` 通过
- 手动 smoke：验证 `爬取入库` / `AI 出题` 时 Run Panel 能实时刷新步骤与进度
