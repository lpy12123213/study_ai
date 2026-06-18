# 组卷 & 自学资料 产物质量小改进清单

> 状态：已实现（2026-06-08）
> 创建：2026-06-06
> 目标：从最小粒度提升组卷/自学资料的**产物内容质量**，不与已落地的宏观能力重复
> 来源：精读代码逐条核实（带 file:line 证据），与 `ai-paper-compose-enhancement.md`、`nextstep.csv` 去重

## 背景

组卷与自学资料的**宏观能力**（多源槽位填充、AI 答案补全、自动/人工审核、平衡修正、LaTeX docker 沙盒、agentic 编排、断点续跑）已在 `nextstep/ai-paper-compose-enhancement.md` 与 `nextstep.csv` 落地。本清单聚焦**产物内容质量**的小修小补——让生成的试卷/资料"更准确、更规范、更可信"，每条改动小、风险低，均已读码核实。

---

## 实施清单

- [x] P1-1 组卷：剔除/替换被审核判 reject 的题（默认路径）
- [x] P1-2 组卷：规划后校验分值合计 == 总分
- [x] P2-1 共享：`clip_text` 结构安全截断（复用现成 `_repair_incomplete_markdown`，合并重复定义）
- [x] P2-2 组卷：导出答案卷标注 AI 合成答案（待复核）
- [x] P2-3 组卷：下调知识点去重阈值
- [x] P2-4 自学：空 section 计入审核并触发重写
- [x] P2-5 自学：section_writer prompt 增补公式/例子/类型化硬约束
- [x] P2-6 共享：通用残留检测器（未替换 `{var}`、不平衡 `$`）
- [x] P2-7 组卷：计算/解答题接数值验算（python_scientific_compute）
- [x] P2-8 自学：section_writer 注入学科课标基线（复用 curriculum_context）
- [x] P3 打磨项（见下表）

---

## P1 — 直接影响产物正确性/可信度

### P1-1 组卷：被审核判"拒绝"的题仍然进卷

- **位置**：`backend/generation/paper_compose/auto_review.py:104-151`、`backend/generation/paper_compose/workflow.py:1386-1412`
- **证据**：`review_questions` 对歧义题（`auto_review.py:104-109`）和低分题（`:139-143`）只写 `review_status="rejected"` / `review_action="reject"`，返回里 `"replaced": 0`（`:151`），**自身从不剔除/替换**。默认路径（`requireHumanReview=false`）下 `workflow.py:1412` 把**全部** `selected_questions` 传给 `_build_save_question_dicts`，而该函数（`workflow.py:52-90`）只跳过无 `question_id` 的题，**不按 reject 过滤**。结果：自动审核结论形同虚设，被判歧义/低分的题原样进卷。
- **最小改法**：在 `workflow.py:1412` 之前按 `review_action == "reject"` 过滤问题题；优先用同槽候选替换（复用 `balance._find_replacement` 思路），无候选则剔除并在 SSE summary 标 `dropped`。`require_human_review` 路径维持不变（交人工）。

### P1-2 组卷：分值合计与总分不对账

- **位置**：`backend/generation/paper_compose/auto_planner.py:160-195`、`backend/generation/paper_compose/analysis.py:43-44`
- **证据**：`auto_planner` 规划时给每个槽位生成 `points_each`（`:172-184`），但全流程**没有任何地方校验 `Σ(count × points_each) == total_points`**；`analysis.py:43-44` 只计算平均难度，不做分值合计。AI 规划的分值合计常与请求满分（默认 150）不一致，导致卷面总分错误。
- **最小改法**：规划归一化后增加一步对账——计算合计，与 `total_points` 不符时按比例/向大题摊平差额，或在 SSE summary 给出 `scoreMismatch` 提示供前端展示。

---

## P2 — 性价比高（一处改、常常两条链路受益）

### P2-1 共享：`clip_text` 按字符硬切，破坏公式/表格/代码块结构

- **位置**：`backend/core/text_utils.py:6-19`（另有重复实现于 `backend/core/helpers.py`）
- **证据**：纯 `s[:max_chars].rstrip()+省略号`，**不感知结构**，会把 `$...$` / `$$...$$` / 表格 / ```` ``` ```` 从中间截断后喂给下游 LLM（调用点密集：`source_synthesis.py`、`study_material_generation.py:684` 等）。而 `backend/agent/tools/utils/text_utils.py:339` **已有现成 `_repair_incomplete_markdown`**（含 `_has_unbalanced_inline_math`、未闭合 code fence 修复），却没被截断侧复用。
- **最小改法**：新增 `clip_text_structural`（或给 `clip_text` 加 `repair_markdown=True`）：截断后调用 `_repair_incomplete_markdown` 补回闭合符；优先把喂 LLM 的截断点切过去。顺手合并 `core/text_utils.py` 与 `core/helpers.py` 两份重复定义。

### P2-2 组卷：AI 合成答案在导出答案卷里无"待复核"标注

- **位置**：`backend/generation/paper_compose/answer_synthesis.py:88`；导出器 `exporters/{latex,docx,markdown}.py`
- **证据**：`answer_synthesis` 设 `answer_source="ai_synthesis"`，已存库（`workflow.py:83`）、已出 API（`api/tasks.py:145,155`）。但三个导出器都不读 `answer_source`，**答案卷里 AI 合成答案与爬虫/题库答案完全无区分**，教师无法识别哪些需复核。
- **最小改法**：导出答案/解析段落时，若 `answer_source=="ai_synthesis"` 加一行脚注（如"※ 本题答案由 AI 生成，请复核"）。三个导出器各加一处。

### P2-3 组卷：知识点去重阈值过高，几乎永不触发

- **位置**：`backend/generation/paper_compose/balance.py:200,238-241`
- **证据**：`kp_repeat_threshold = max(2, (len(selected)+1)//2)`，20 题卷=10；`:240` 要求 `seen_repeated_kps[kp] > threshold`（>10）才标 `knowledge_repeat`。即同一知识点要出现 **11 次以上**才换题——正常卷面**永远不触发**，知识点去重实为死代码。
- **最小改法**：把阈值降到合理量级，如 `max(2, ceil(len(selected)/4))`（20 题→5）或设可配上限；同时确认 `:201` 的 `repeated_kps` 集合联动。

### P2-4 自学：空 section / 讲解失败不计入审核，无重写触发

- **位置**：`backend/agent/tools/knowledge/study_archive.py:232-233,306-311`；`backend/agent/tools/analysis/content_review.py:169-195`
- **证据**：空讲解只渲染兜底文案"（讲解为空…）"（`study_archive.py:233`），但 `assemble` 返回值（`:306-311`）只报 `markdown_chars`，**不统计空/兜底 section 数**；`content_review` 的 heuristic `passed=False` 仅在 deep/research 预设"维度覆盖不足"时触发（`:169-174`），**不专门检测空 section**。结果：一半知识点讲解为空也可能"审核通过"。
- **最小改法**：`assemble` 返回 `empty_sections`（兜底/空讲解的知识点列表）；`content_review` 据其在任意预设下置 `passed=False`，写进 issues，交由既有 `revise_markdown` / planner 重写。

### P2-5 自学：section_writer prompt 缺格式/教学硬约束，且不利用已算出的知识点类型

- **位置**：`backend/agent/tools/knowledge/study_material_generation.py:805,816-826`
- **证据**：`knowledge_type` 已算好并传入 payload（`:805`），但 `instructions`（`:816-826`）只约束"正文/无标题/无引用/原创改写"，**没有**"数学表达式一律用 `$...$` / `$$...$$`""定义/定理类至少给 1 个最简例子""按 `knowledge_type` 组织（algorithm 给步骤、theorem 给条件+结论+例子）"等硬约束。
- **最小改法**：在 `instructions` 增补 2-3 条：公式用 LaTeX 包裹；按 `knowledge_type` 给类型化结构要求；definition/theorem 至少配一个例子。纯 prompt 改动，零代码风险。

### P2-6 共享：缺通用残留检测（未替换 `{var}`、不平衡 `$`）

- **位置**：跨链路缺失（grep 确认 `paper_compose` / `question_library` / study_materials 均无此类检测器）
- **证据**：题干/答案入卷前仅做 TeX 转义（`exporters/latex.py`），未检测未替换的 `{variable}`、残留 ```` ```latex ````、孤立 `**` 或被截断（半个公式结尾）；自学资料侧同样无"出库前 lint"。
- **最小改法**：新增轻量 `backend/core/text_lint.py`（检测裸 `{xxx}`、奇数个 `$`、未闭合 code fence、孤立表格行），返回 flags；组卷入卷前、自学资料 assemble 后各调一次，写进 `quality_flags` / review issues（先只观测+标注，不阻断）。

---

## P3 — 较小打磨项（实施时逐条复核）

| 链路 | 位置 | 问题 | 最小改法 |
|------|------|------|----------|
| 组卷 | `auto_review.py:84-89,144-149` | LLM 未配置/审核异常一律 `action="pass"`（出错即放行） | review_error 改标 `needs_human`，不计入 passed |
| 组卷 | `workflow_support.py` `_stem_fingerprint` | 去重仅 md5 精确指纹，漏标点/数字/同义近似重复 | fp 前先 strip 标点、归一化数字串为占位符 |
| 组卷 | `exporters/latex.py`（选项渲染） | 选择题 A/B/C/D 塞在 stem 里，不换行/编号 | 题带 `options` 字段时用 enumerate 环境逐项渲染 |
| 组卷 | `exporters/latex.py`（缺图） | 找不到图片静默跳过，"如图"却无图无占位 | 缺图时输出空白方框占位 |
| 组卷 | `exporters/markdown.py` | stem/answer 含 `\|` 未转义，破坏元信息表格 | 渲染前转义管道符 |
| 组卷 | `exporters/latex.py`（`include_stem=false`） | 无 stem 时输出内部"题目ID：xxx"泄漏到学生卷 | 缺 stem 时输出占位而非 ID |
| 组卷 | `workflow.py:1343` | 补答案上限复用 `maxAiQuestionsPerPaper`(默认20)，大卷缺答案题被静默跳过 | 补答案用独立、更高的上限 |
| 自学 | `knowledge_type_detection.py:46-48` | 关键词匹配把"一元二次方程解法"误判为 theorem（应为 algorithm） | 把 algorithm 关键词（"解法/…的解"）判定提到 theorem 之前 |
| 自学 | 全链路 | 无学段（小学/初中/高中）适配，深浅只由 preset 决定 | 从 options 透传 `grade_band` 进 outline/writer 并加约束 |
| 自学 | `core/text_utils.py` `_sanitize` | 删 markdown 链接保留锚文本，原文 `见(http…)` 留空 `()` | 清理后去掉空括号 |
| 自学 | `knowledge_points.py:128-159` | LLM 不可用时模板兜底只覆盖"射影几何"一个领域 | 泛化兜底模板（可后置） |

---

## 验证方式

- **P1-1 reject 剔除**：扩展 `backend/tests/test_paper_compose_slot_fill.py`——构造被判 ambiguous/低分的题，断言保存的 `q_dicts` 不含该题（或被替换）。
- **P2-1 结构安全截断**：单测对含中段公式/表格/代码块的长文本调用新函数，断言 `$` 成对、code fence 闭合。
- **P2-2 答案标注**：单测分别用三个导出器渲染 `answer_source="ai_synthesis"` 的题，断言输出含脚注。
- **P2-3 知识点阈值**：单测构造 20 题、某知识点重复 6 次，断言触发 `knowledge_repeat` 替换。
- **P2-4 空 section**：单测让某 section 讲解为空，断言 `assemble` 返回 `empty_sections` 非空且 `content_review.passed=False`。
- **P2-5 writer prompt**：跑一次自学资料生成，人工抽检公式是否用 `$...$`、定义/定理是否带例子。
- **P2-6 残留检测**：单测对含 `{var}`、奇数 `$` 的文本断言 flags 命中。
- **整体回归**：现有 `test_paper_compose_*` / `test_study_materials_*` 子集确保不回归。

---

## 建议 PR 拆分

1. **PR1（P1-1）**：组卷 reject 题剔除/替换 + 测试（最高价值，单独发）
2. **PR2（P2-1 + P2-6）**：`clip_text` 结构安全截断（合并重复定义）+ 通用残留检测器
3. **PR3（P2-2 + P2-3）**：AI 答案标注 + 知识点去重阈值
4. **PR4（P2-4 + P2-5）**：空 section 入审 + writer prompt 硬约束
5. **PR5（P3）**：打磨项批量小修
