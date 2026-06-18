# 在线做试卷功能 - 实施方案

**优先级**: P1, 新功能/在线做题
**状态**: 已实现（2026-06-01）

本轮落地:
- 后端新增考试会话、作答、结果三张表与仓储层，接入 `/api/exam/*` 路由。
- 前端新增开始答题入口、沉浸式答题页、结果页、答题卡、手写板、计时器、自动保存和交卷闭环。
- 评分服务覆盖客观题确定性批改，主观题支持视觉模型可用时 AI 评分、不可用时文本/启发式降级。
- 验证覆盖 `backend.tests.test_exam_sessions` 与前端生产构建。

2026-06-08 加固:
- 修复答题页 autosave/timer 重复订阅与重复提交风险，切题与会话切换时清理保存状态。
- 客观题/答题回顾统一走 `QuestionContent`/Markdown 渲染，恢复公式、图片和选项展示一致性。
- 手写板按题目隔离画布状态，避免不同题之间笔迹串写或残留。

---

## 问题描述

系统当前覆盖了题目的生成、搜题、组卷、AI批改（作文评估），但学生无法在线做试卷。缺少:
1. 答题卡/机读卡模式让学生作答客观题（单选/多选/填空）
2. 手写板模式让主观题（简答/计算/论述）手写作答
3. 作答后AI自动批改（客观题对比答案、主观题视觉AI评分）
4. 计时/自动保存/交卷/成绩查看的完整考试流程

## 设计决策

| 决策项 | 选择 | 说明 |
|--------|------|------|
| 手写处理 | 直接提交图片给AI批改 | 学生手写保存为图片，AI视觉模型直接识别评分，不经过OCR |
| 计时模式 | 计时+不计时两种 | 支持限时考试（倒计时自动交卷）和不限时练习 |
| 批改流程 | 纯AI自动批改 | 无需教师复核 |
| 自动保存 | 每30秒+切题时保存 | 防止意外关闭丢答案 |

## 题型 → 作答模式映射

| 题型 | 作答模式 | 评分方式 |
|------|----------|----------|
| single_choice | 机读卡（bubble sheet，单选） | 自动对比（字母匹配） |
| multi_choice | 机读卡（bubble sheet，多选） | 自动对比（集合匹配） |
| fill_blank | 文本输入 | 自动对比（归一化字符串匹配） |
| short_answer | 手写板（Canvas） | AI视觉评分 |
| calculation | 手写板（Canvas） | AI视觉评分 |
| essay | 手写板 + 可选文本区 | AI视觉评分 |

---

## 实施步骤

### 一、数据库模型 (`backend/database/schema.py`)

新增3张表，不修改已有 Paper/PaperQuestion 模型:

**ExamSession** - 考试会话:
- `id`, `user_id`, `paper_id`(FK), `paper_name`, `mode`(timed|untimed)
- `time_limit_minutes`(nullable), `started_at`, `submitted_at`, `expires_at`
- `status`(in_progress|submitted|expired), `total_score`, `max_score`
- 索引: (user_id, status), (user_id, paper_id)

**StudentAnswer** - 学生作答:
- `id`, `session_id`(FK), `user_id`, `question_id`, `question_type`, `question_order`
- 客观题: `selected_options`(JSON), `fill_blank_text`
- 主观题: `handwriting_image_path`, `text_answer`(可选补充)
- 评分: `is_correct`(0/1/null), `score`, `max_score`, `grading_json`(AI详细反馈)
- 自动保存: `auto_saved_at`
- 唯一约束: (session_id, question_id)

**ExamResult** - 考试结果:
- `id`, `session_id`(FK, unique), `user_id`
- `total_score`, `max_score`, `score_ratio`
- `objective_correct`, `objective_total`, `subjective_score`, `subjective_max`
- `breakdown_json`(逐题得分), `ai_feedback_json`(总体AI评语)

### 二、后端仓储层 (`backend/database/repositories/exam/`)

仿照 `repositories/question/papers.py` 模式，创建 `exam_sessions.py`:
- `create_exam_session(user_id, paper_id, mode, time_limit)` → ExamSession
- `get_exam_session(user_id, session_id)` → 会话+题目（不含答案）
- `list_user_sessions(user_id, paper_id, limit)` → 历史会话列表
- `save_answer(user_id, session_id, question_id, answer_data)` → upsert
- `batch_save_answers(user_id, session_id, answers)` → 批量保存
- `submit_session(user_id, session_id)` → 标记为 submitted
- `get_session_answers(user_id, session_id)` → 全部答案
- `update_answer_score(user_id, answer_id, score_data)` → 写入评分
- `create_exam_result(user_id, session_id, result_data)` → 创建结果

### 三、后端API端点 (`backend/api/exam.py`)

Router: `/exam` 前缀，全部需要 `require_auth`:

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/exam/sessions` | 开始考试 → 返回 session_id + 题目列表（不含答案） |
| GET | `/exam/sessions/{id}` | 获取会话状态（恢复考试） |
| GET | `/exam/sessions` | 列出历史会话（可按 paper_id 过滤） |
| PUT | `/exam/sessions/{id}/answers/{qid}` | 保存/自动保存单题答案 |
| PUT | `/exam/sessions/{id}/answers/batch` | 批量保存答案 |
| POST | `/exam/sessions/{id}/answers/{qid}/handwriting` | 上传手写图片 |
| POST | `/exam/sessions/{id}/submit` | 交卷 → 触发评分 |
| GET | `/exam/sessions/{id}/result` | 查看成绩 |

Schemas: `backend/api/exam_schemas.py` (Pydantic)
注册: `backend/api/domains/workspace.py` 中 include

**手写图片上传**:
- 限制: MIME PNG/JPG/WebP, max 10MB
- 存储: `.local/media/exam_handwriting/{user_id}/{session_id}/{question_id}_{timestamp}.png`
- 服务: 通过 `/api/media/exam-handwriting/...` 访问

### 四、评分服务 (`backend/generation/exam_grading/`)

**objective.py** - 客观题自动对比:
- 从 PaperQuestion.answer 取正确答案
- single_choice: 字母匹配（如 "B" == "B"）
- multi_choice: 集合匹配（如 {"A","C"} == {"A","C"}）
- fill_blank: 归一化字符串匹配（trim + lowercase + 多答案分隔符）

**subjective.py** - AI视觉评分:
- 读取 handwriting_image 转 base64
- 传给视觉LLM: 题目 + 参考答案 + 手写图片 → 结构化评分 JSON
- 可复用 `generation/essay_evaluation/service.py` 的调用模式
- 模型不支持视觉时回退为纯文本评分
- 输出: `{score, max_score, reasoning, strengths, weaknesses}`

**orchestrator.py** - 评分编排:
1. 加载会话 + 答案 + 试卷题目
2. 客观题: 同步逐题对照 → 写入 is_correct + score
3. 主观题: 异步并行调用AI评分 → 写入 score + grading_json
4. 汇总: 计算总分 → 生成AI总体反馈 → 创建 ExamResult

### 五、前端类型定义 (`frontend/src/types/`)

```typescript
ExamMode = 'timed' | 'untimed'

ExamSession { sessionId, paperId, paperName, mode, timeLimitMinutes,
  startedAt, expiresAt, status, questions: ExamQuestion[] }

ExamQuestion { questionId, order, type, stem, difficulty,
  knowledgePoint, maxScore, options: string[] }

StudentAnswer { questionId, questionType, selectedOptions, fillBlankText,
  handwritingImageUrl, textAnswer, isCorrect, score, maxScore, gradingJson }

ExamResult { sessionId, totalScore, maxScore, scoreRatio,
  objectiveCorrect, objectiveTotal, subjectiveScore, subjectiveMax,
  breakdown: QuestionScoreBreakdown[], aiFeedback }
```

### 六、前端API + Hooks

**`frontend/src/api/exam/client.ts`**（仿照 `api/papers/client.ts`）:
`startExam`, `getExamSession`, `getExamSessions`, `saveAnswer`,
`batchSaveAnswers`, `uploadHandwriting`, `submitExam`, `getExamResult`

**`frontend/src/hooks/useExam.ts`**: TanStack Query hooks（`useExamSession`, `useExamResult`, `useStartExam`, `useSaveAnswer`, `useSubmitExam`）

### 七、Zustand状态管理 (`frontend/src/stores/useExamStore.ts`)

- **状态**: sessionId, questions, currentQuestionIndex, 本地答案缓存(Record<qid, answer>), remainingSeconds, timerColor(green/yellow/red), lastSavedAt, isSaving
- **核心行为**:
  - `tick()`: 每秒递减倒计时 → green(>5min)→yellow(1-5min)→red(<1min+闪烁) → 归零自动提交
  - `autoSave()`: 每30秒 diff dirty答案 → batch_save API
  - `updateAnswer(qid, data)`: 标记已答 + 加入dirty队列
  - `submitExam()`: 先保存 → 调submit API → 跳转结果页
- 计时器以服务器 `expires_at` 为准防客户端漂移

### 八、UI组件

新增 shadcn/ui 基础组件:
- `components/ui/radio-group.tsx` - Radix RadioGroup
- `components/ui/checkbox.tsx` - Radix Checkbox

**机读卡组件** (`features/exam/components/BubbleSheetCard.tsx`):
- 大号可点击选项圆圈（A/B/C/D...），单选/多选模式
- 选中实心填充，未选中空心，hover高亮，focus-ring
- 选项从题干中提取，2x2或4x1响应式布局

**手写板组件** (`features/exam/components/HandwritingBoard.tsx`):
- HTML5 Canvas + pointer events（支持触控笔/手指）
- 工具: 笔（宽2-4px，黑/蓝/红）、橡皮擦、撤销(Ctrl+Z)、重做(Ctrl+Y)、清空
- 笔画数组存储（回看时可恢复），导出: `canvas.toBlob()` → JPEG q85 max 2048px → 上传
- 工具栏: `HandwritingToolbar.tsx`

**计时器** (`features/exam/components/ExamTimer.tsx`):
- HH:MM:SS 倒计时，颜色渐变，最后30秒脉冲闪烁
- 归零时触发 `onTimeExpired` → 自动交卷

**题目导航** (`features/exam/components/QuestionNavigator.tsx`):
- 左侧题号列表: 已答(实心)/未答(空心)/当前(高亮边框)
- 显示进度: "5/20 已答"

**确认弹窗** (`features/exam/components/SubmitConfirmDialog.tsx`):
- 已答/未答统计，未答题红色警告，"确认交卷"/"继续答题"

**答案回顾** (`features/exam/components/AnswerReview.tsx`):
- 客观题: 显示选择的圆圈 + 正确答案（绿对红错）
- 主观题: 显示手写图片 + AI评分理由

### 九、页面

**答题页** (`pages/ExamPage.tsx`, 路由 `/exam/:sessionId`):
```
┌──────────────────────────────────────────────────┐
│ [试卷名]    ⏱ 01:23:45    [交卷]                  │
├────────┬─────────────────────────────────────────┤
│ 题号   │  题目题干（KaTeX渲染）                     │
│ 1 ✓   │                                          │
│ 2 ◉   │  ……作答区（根据题型渲染）……                 │
│ 3 ○   │  single_choice → BubbleSheetCard         │
│ 4 ○   │  essay → HandwritingBoard + TextArea     │
│ ...   │                                          │
│ 20 ○  │  [上一题] [下一题]                        │
├────────┴─────────────────────────────────────────┤
│ 已保存 12:30 · 进度 5/20                          │
└──────────────────────────────────────────────────┘
```
- 布局: `fullscreen` 沉浸式，无侧边栏
- 切题时自动保存当前题答案 + 上传手写图片
- 自动保存每30秒，小指示器显示保存状态
- 计时模式: 到时间自动提交

**结果页** (`pages/ExamResultPage.tsx`, 路由 `/exam/:sessionId/result`):
- 总分/客观分/主观分/AI总评
- 每题可展开: 学生答案 vs 正确答案 + AI评分详评 + 手写图片查看

### 十、入口按钮

- `PaperDetailPage.tsx` 头部加 "开始答题" 按钮 → 选择计时/不计时模式 → 创建会话 → 跳转 `/exam/:sessionId`
- `PapersPage.tsx` 试卷卡片加 "答题" 操作

### 十一、路由注册

`router/routes.config.ts` + `router/index.tsx`:
- `/exam/:sessionId` → fullscreen, sidebar=false, navGroup=hidden
- `/exam/:sessionId/result` → standard layout, sidebar=true

---

## 关键设计细节

1. **手写图片上传时机**: 切题时上传（非每笔），Canvas笔画数组保留在内存以便回看恢复
2. **计时器**: 以服务器 expires_at 为准，每tick计算 `expires_at - Date.now()`，防客户端漂移
3. **视觉模型降级**: 模型不支持图片时回退为纯文本评分
4. **图片压缩**: Canvas导出JPEG q85 max 2048px → 约200-500KB
5. **不修改已有模型**: Paper/PaperQuestion已有answer字段和question_type字段可直接复用

## 需要新建的文件

```
backend/
  database/repositories/exam/__init__.py
  database/repositories/exam/exam_sessions.py
  api/exam.py
  api/exam_schemas.py
  generation/exam_grading/__init__.py
  generation/exam_grading/objective.py
  generation/exam_grading/subjective.py
  generation/exam_grading/orchestrator.py

frontend/src/
  api/exam/client.ts
  hooks/useExam.ts
  stores/useExamStore.ts
  types/exam.ts (或追加到 types/index.ts)
  components/ui/radio-group.tsx
  components/ui/checkbox.tsx
  features/exam/components/BubbleSheetCard.tsx
  features/exam/components/HandwritingBoard.tsx
  features/exam/components/HandwritingToolbar.tsx
  features/exam/components/ExamTimer.tsx
  features/exam/components/QuestionNavigator.tsx
  features/exam/components/SubmitConfirmDialog.tsx
  features/exam/components/AnswerReview.tsx
  pages/ExamPage.tsx
  pages/ExamResultPage.tsx
```

## 需要修改的文件

```
backend/database/schema.py               → 新增3个模型
backend/api/domains/workspace.py          → 注册exam router
backend/api/media.py                      → 新增手写图片服务端点（或直接在exam.py）
frontend/src/pages/PaperDetailPage.tsx    → 加"开始答题"按钮
frontend/src/pages/PapersPage.tsx         → 试卷卡片加"答题"操作
frontend/src/router/routes.config.ts      → 新增2条路由
frontend/src/router/index.tsx             → 注册路由组件
```
