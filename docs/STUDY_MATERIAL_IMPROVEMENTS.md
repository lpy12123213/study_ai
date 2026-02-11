# 自学材料生成：问题清单与改进路线图

> 基线样例：`study_archives/微积分_20260209_113100.md`（2026-02-09 生成）
>
> 编码提示：本文件为 UTF-8（无 BOM）。在 Windows PowerShell 5.1 下直接 `Get-Content` 可能乱码，请使用：`Get-Content -Encoding UTF8 docs\STUDY_MATERIAL_IMPROVEMENTS.md`

本文基于一次“微积分”自学档案的生成结果，梳理当前链路的主要质量问题，并给出按优先级排序的落地建议（包含：定位点、可选方案、验收标准）。

> 状态说明：本文是“路线图/问题清单”，其中“当前实现/根因定位”以基线样例生成时的行为为参考。后续如有代码落地，会在对应章节用“已实现/现状更新”补充说明。

---

## 0. 当前生成链路（便于定位代码）

生成链路由 **Plan → Tools → Assemble → Review/Revise** 组成，核心代码位置如下：

- 规划（决定调用哪些工具）：`backend/agent/planner.py`
- 执行（各工具实现）：`backend/agent/executor.py`
- 对外接口（流式输出）：`backend/api/study_materials.py`
- 产物拼装：`Executor._tool_assemble_study_archive()`（最终 Markdown）

关键工具（常见顺序，工具名与实现函数同名）：

1. `split_knowledge_points`：主题 → 知识点列表（`Executor._tool_split_knowledge_points`）
2. `web_search_knowledge`：知识点 → 搜索结果 URL/摘要（`Executor._tool_web_search_knowledge`）
3. `browse_web_pages`（可选）：抓取 URL → 正文抽取（`Executor._tool_browse_web_pages`）
4. `wikipedia_search` / `mediawiki_search`（可选）：百科摘要（`Executor._tool_wikipedia_search` / `Executor._tool_mediawiki_search`）
5. `stackexchange_search` / `github_search`（可选）：问答/仓库检索（`Executor._tool_stackexchange_search` / `Executor._tool_github_search`）
6. `search_questions_by_knowledge`（可选）：题库检索（例题/练习）（`Executor._tool_search_questions_by_knowledge`）
   - 默认关闭（先专注概念与理解）：`STUDY_MATERIALS_ENABLE_QUESTIONS=0`
   - 需要题库时开启：`STUDY_MATERIALS_ENABLE_QUESTIONS=1`
7. `aggregate_knowledge`：聚合上面所有结果（`Executor._tool_aggregate_knowledge`）
8. `generate_study_material`：生成概念讲解（可选：示意图）（`Executor._tool_generate_study_material`）
9. `assemble_study_archive`：拼装最终 Markdown（`Executor._tool_assemble_study_archive`）
10. `review_content` / `revise_markdown`：审查与可选修订（`Executor._tool_review_content` / `Executor._tool_revise_markdown`）

补充（内部工具/能力）：

- `draw_svg_diagram`：生成 SVG 示意图并落盘到 `.local/media/generated/`（`Executor._tool_draw_svg_diagram` + `backend/core/svg_diagram.py`）
- `GET /api/media/generated/{filename}`：渲染用的本地生成媒体访问入口（`backend/api/media.py`）

> 额外检索工具默认可能被关闭：`backend/agent/planner.py` 会根据 `STUDY_MATERIALS_ENABLE_EXTRA_TOOLS=1` 决定是否启用百科/网页正文/StackExchange/GitHub 等工具。排查“为什么没抓网页/没搜百科”时先看这个开关。

---

## 1. 目标（建议验收指标）

建议把“看起来更好”落成可测指标，避免只凭主观感觉迭代：

- **可读性**：最终 Markdown 中不应出现大段乱码/碎片文本（尤其是 PDF 公式提取导致的噪声）。
- **覆盖率**：每个知识点至少包含：
  - 讲解（定义/直观理解/关键点/常见误区/小结）
  - （如适用）1 张简洁示意图：帮助理解结构/关系（例如几何、函数图像、集合关系等）
  - （可选）题库例题/练习题：目前默认关闭，待概念质量稳定后再启用
- **引用质量**：每个知识点至少 2 个可用来源（标题 + 链接 + 简述），并能看出可靠性（如：教材/高校/百科/高票问答）。
- **稳定性**：LLM 输出不应中途截断；若截断，应自动续写或降级输出（但保证句子完整、结构完整）。

---

## 2. 优先级总览（建议落地顺序）

| 优先级 | 方向 | 为什么现在做 | 影响范围 | 主要落点 |
|---|---|---|---|---|
| P0 | PDF 解析与降级 | 当前直接“污染正文”，可读性崩溃 | 极高 | `Executor._tool_browse_web_pages()` |
| P0 | 网页正文提取/去噪 | UI 噪音大量掺入正文 | 高 | `Executor._tool_browse_web_pages()` |
| P1 | 绘图/示意图生成 | 几何/函数等主题缺少直观支撑 | 高 | `Executor._tool_draw_svg_diagram()` + `Executor._tool_generate_study_material()` |
| P1 | LLM 截断续写 | 影响内容完整性与可信度 | 高 | `Executor._call_llm_text()` 及生成/修订步骤 |
| P2 | 百科检索命中率 | 影响“概念锚点”与术语统一 | 中 | `Executor._tool_wikipedia_search()` / `Executor._tool_mediawiki_search()` |
| P2 | 知识点拆分粒度 | 影响检索精度与 token 压力 | 中 | `Executor._tool_split_knowledge_points()` |
| P2 | 数学公式标准化 | 影响可读性与一致性 | 中 | 组装/后处理 |
| P3 | 引用格式与可信度 | 提升材料可用性 | 低 | 组装/后处理 |
| P3 | 学习路径/前置关系 | 提升学习体验 | 低 | 组装/生成 |

---

## 零、工程体验问题：慢 / 卡住 / 刷新丢进度（P0 / High）

**现象**：

- 生成速度慢：知识点（SubAgent）逐个串行执行，整体耗时随着知识点数线性增长。
- 偶发“卡住不动”：长工具调用期间 SSE 无任何输出，前端体验像“挂起”，也不利于定位问题。
- 刷新丢进度：浏览器刷新后，步骤/进度丢失，且无法继续接收同一个生成任务的后续输出。

**现状更新（已实现）**：

1. **SubAgent 并行**：`backend/agent/core.py` 的 `foreach_knowledge_point` block 已支持并行执行（按知识点并行，单个知识点内部仍按研究链路串行）。
   - 并发上限：`STUDY_MATERIALS_SUBAGENT_CONCURRENCY`（默认 3）。
2. **任务化 + 可重连**：后端把“自学资料生成”改为 Task 模式，支持刷新后重连并从 `after_seq` 续流。
   - `POST /api/study-materials/generate`：启动任务并直接 SSE 流式返回（首个事件为 `task_started`，包含 `task_id`）。
   - `GET /api/study-materials/tasks/{task_id}/stream?after_seq=...`：续流/重连。
   - `GET /api/study-materials/tasks/{task_id}`：查询任务状态（running/completed/failed）与序号范围。
3. **SSE 心跳（避免“无输出假死”）**：当后端暂时没有新事件时，会周期性发送 `ping` 事件保持连接活性。
   - 心跳间隔：`STUDY_MATERIALS_SSE_HEARTBEAT_S`（默认 4 秒）。
4. **工具级超时（避免无限等待）**：每个工具调用新增超时保护，超时会返回结构化失败结果而不是一直挂住。
   - 超时：`STUDY_MATERIALS_STEP_TIMEOUT_S`（默认 240 秒）。
5. **公式渲染（前端）**：自学资料页面已启用 Markdown + LaTeX 渲染（`remark-math` + `rehype-katex`），并引入 KaTeX 样式，公式展示更一致。
6. **网搜切换为 Metaso（报告型摘要）**：`web_search_knowledge` 优先使用 Metaso API，并可返回 `summary` 作为报告型梳理文本（更少“百科 UI 噪音”）。
   - 配置：`METASO_API_KEY`（兼容别名 `METASO_API`）、`METASO_BASE_URL`、`METASO_TIMEOUT`（见 `.env.example`）
7. **示意图（SVG）**：`generate_study_material` 会尝试为每个知识点生成一张简洁示意图（SVG），并通过 `/api/media/generated/...` 提供给前端渲染。

**建议验收**：

- 同一个自学资料生成过程中刷新页面，仍能继续看到后续步骤与输出（不丢、不重复）。
- 并行开启后，多个知识点的总耗时明显下降（同时不会因为并发过高触发明显的 429/限流）。
- 长工具调用期间，前端至少每隔数秒能收到 `ping`，用户不会误以为卡死。

---

## 一、PDF 公式提取严重损坏（P0 / Critical）

**现象**：从 PDF 课件中提取的数学公式变成不可读的碎片文本。例如样例中“极限与连续”部分引用的北师大课件（`math0.bnu.edu.cn`），提取结果出现：

```
Dy = f x - f x0
e d d
- <
f x f x
x x
```

原始内容应为 ε-δ 语言的连续性定义，但 PDF 中的公式常以矢量图形/特殊编码存储，直接把 PDF 当 HTML 做 `get_text()` 会彻底失真。

**根因定位**（当前实现）：

**现状更新（已实现）**：

- `Executor._tool_browse_web_pages()` 内部 `_fetch_one()` 已会识别 PDF（URL 以 `.pdf` 结尾或 `content-type: application/pdf`），并直接降级为“标记失败 + 保留链接/元信息”，避免把碎片文本写入正文。
- 这能有效止血“公式碎片污染正文”，但也意味着 PDF 正文目前不会被纳入材料内容（若需要使用 PDF 内容，仍需引入专用解析/（可选）OCR）。

**改进方向**（建议分阶段）：

1. **短期止血（强烈建议先做）**：在 `_fetch_one()` 中识别 PDF（`content-type: application/pdf` 或 URL 以 `.pdf` 结尾），直接降级为“只保留链接 + 标题 + 简述”，不要把碎片文本写入正文。（**已实现**：目前会跳过 PDF，避免污染正文）
2. **中期可用**：为 PDF 引入专用解析库提取文字层（优先）：
   - PyMuPDF（fitz）：速度快、依赖相对轻；适合“有可复制文字”的 PDF。
   - pdfplumber：对表格/布局更友好，但速度偏慢。
   - 策略：先尝试文字层提取；若提取文本过短/异常，再判定为扫描版或公式密集版。
3. **长期高质量（公式 LaTeX）**：对“扫描版/公式密集” PDF 增加 OCR + 数学公式识别：
   - 识别出文本 + 公式 LaTeX（如 Mathpix / Nougat / pix2tex 等）。
   - 需要考虑：成本、速度、依赖体积、离线/在线可用性。

**建议验收**：

- 最终 Markdown 中 **不再出现** 由 PDF 提取导致的“碎片公式垃圾段落”。
- 对于 PDF 来源：要么能输出“可读的正文摘要”，要么明确标注“PDF 未解析，仅保留链接”，但不污染主文。

---

## 二、网页内容清洗不足（P0 / High）

**现象**：爬取的百科页面包含大量网页 UI 噪音，直接混入正文。例如：

- 百度百科内容混入：“播报”“编辑”“新手上路”“成长任务”“©2025 Baidu”
- 搜狗百科内容混入：整段导航栏、“登录”“企业推广”“免责声明”、侧边栏分类标签等

**根因定位**（当前实现）：

- `Executor._tool_browse_web_pages()` 的 `_fetch_one()` 仅移除了 `script/style/header/footer/nav/aside` 等标签。
- 但百科站点大量 UI 结构使用 `div/span` 等通用标签；仅靠“删标签”很难得到正文。
- 现阶段抽取方式基本等价于“整页纯文本”，噪音比很高。

**改进方向**：

1. **通用正文抽取算法**：引入 `readability-lxml` / `trafilatura`（二选一或组合），优先从 HTML 中抽取“主内容”而不是“整页文本”。
2. **站点专用规则（高 ROI）**：对主流站点做定制抽取：
   - `baike.baidu.com`、`baike.sogou.com`：只取正文容器（通常有稳定的 id/class/结构）。
   - `zh.wikipedia.org`：只取 `#mw-content-text` 等正文区域。
3. **后处理去噪**：加一层“明显 UI 文本过滤”（正则或规则表），典型关键词如：`播报`、`编辑`、`登录`、`免责声明`、`©`、`版权`、`导航` 等。
4. **质量门槛**：为抽取结果增加 `min_text_chars` / `min_sentence_count` 门槛；低于门槛视为失败并降级为“仅保留链接 + snippet”。

**建议验收**：

- 对 3~5 个常见百科页面抽取结果进行人工 spot-check：正文中不应出现导航/登录/版权条款等 UI 噪音。
- 对同一页面重复抽取（多次生成）结果结构稳定（不应因为 DOM 细节变化大幅波动）。

---

## 三、例题与练习题缺失严重（P1 / High）

**现象**：样例中多个知识点出现“（未检索到例题）/（未检索到练习题）”，导致学习材料缺少“动手练习”的核心部分。

**根因定位**：

- 题库检索由 `Executor._tool_search_questions_by_knowledge()` 完成，依赖题库/爬虫覆盖面与可用性。
- `Executor._tool_generate_study_material()` 在 `examples/exercises` 为空时并没有稳定兜底策略。

**改进方向**：

1. **题库侧增强**：
   - 扩充题库数据源（如学科网、菁优网等）或增加“搜索引擎定向检索题目”作为补充源。
   - 放宽/重试策略：首次 strict 失败后，用更宽松的 query/subject/difficulty 重试一次。
2. **LLM 兜底生成（强烈建议）**：
   - 当题库检索失败或数量不足时，要求 LLM 自动生成：≥ 1 道例题（含详解）+ ≥ 2 道练习题。
   - 输出需标注来源：`source: question-bank` / `source: llm-generated`，避免误以为来自外部权威题库。
3. **组装阶段硬性约束**：
   - 在 `generate_study_material` 的提示词（instructions）中加入硬约束：如果外部题目为空，必须补齐最少数量，而不是输出空占位符。

**建议验收**：

- 每个知识点在最终 Markdown 中都出现“例题 + 练习题”段落，且不为空。
- 兜底生成内容有明确标注（避免误导）。

---

## 四、LLM 讲解内容被截断（P1 / High）

**现象**：部分知识点的讲解在中途被截断。例如样例中“无穷级数”出现半句话结束：

```
通项趋于零 ($\lim_{n \to \infty} u_n = 0$) 是级
```

**根因定位**：

- `Executor._call_llm_text()` 目前只返回 `choices[0].message.content`，没有把 `finish_reason` 等元信息传回上层。
- `generate_study_material` 中的 `max_tokens`（如 900/1100）对“信息密度大 + 结构化要求多”的写作任务容易触顶。

**改进方向**：

1. **可观测性优先**：让 `_call_llm_text()`（或新增一个 `_call_llm()`）可选返回：
   - `content`
   - `finish_reason`
   - `usage`（如 prompt_tokens / completion_tokens）
2. **自动续写**：当 `finish_reason == "length"` 时，自动触发“继续写（从上次结尾续写）”的补全请求，并在拼接时避免重复段落（可通过最后 N 行去重）。
3. **拆分生成**：把“定义/直观/关键点/误区/小结”等拆成多次短生成，再组装；比“一次生成大段”更稳。
4. **审查兜底**：在 `review_content` 阶段增加“截断检测”（如以不完整标点/未闭合 LaTeX 结尾等），触发 `revise_markdown` 修复。

**建议验收**：

- 最终 Markdown 不出现“半句/半段落”结束。
- 若发生截断，系统能自动续写直至结构完整或明确降级。

---

## 五、百科检索命中率低（P2 / Medium）

**现象**：多个知识点显示“（未检索到可靠百科词条）”，包括“极限与连续”“导数与微分”“积分学”等。

**根因定位**：

- 组合型知识点（如“极限与连续”）本身不是百科的标准词条标题。
- 当前检索通常直接用知识点作为 query（或拼上 subject），缺少“拆分 + 扩展 + 回退”。

**改进方向**：

1. **组合词自动拆分**：对包含“与/和/及/、/（ ）”等连接符的知识点拆成子查询（如“极限”“连续”），分别检索后合并。
2. **同义词与多语言扩展**：内置常用映射（如“导数/微分/derivative”，“积分/不定积分/integral”），用多 query 再择优。
3. **多源百科**：除 Wikipedia 外，可考虑：
   - MediaWiki 站点（Wikibooks/Wikiversity/ProofWiki 等）
   - 百度百科/搜狗百科（注意抽取与版权合规；可只做“概念锚点/术语对齐”，不大量搬运正文）

**建议验收**：

- 核心知识点（概念类）命中百科摘要的比例显著提升（可先以样例主题为基准对比）。

---

## 六、知识点拆分粒度过粗（P2 / Medium）

**现象**：微积分被拆分为 6 个大类（极限与连续、导数与微分、积分学、多元函数微分学、重积分、无穷级数），每个大类本身仍是庞大主题，导致：

- 讲解只能浅尝辄止
- 搜索/检索精度下降（query 过宽）
- LLM 单次生成负担过重，更易截断

**改进方向**：

1. **层级拆分**：在 `split_knowledge_points` 阶段要求输出树形结构，再按“目标粒度”展开为列表。
2. **粒度标准**：在提示词中明确“每个知识点应能在 1 页内讲清楚”的约束，避免巨型知识点。
3. **可配置性**：支持用户指定拆分深度/最大知识点数；或允许用户手工传入 `knowledge_points` 覆盖拆分结果。

**建议验收**：

- 对“微积分”等大主题，拆分结果更细（例如 15~30 个子知识点），且每个点都能对应到稳定的百科/网页/题库检索。

---

## 七、数学公式渲染不统一（P2 / Medium）

**现象**：同一份文档中数学公式的表示方式混乱：

- LLM 讲解使用标准 LaTeX（如 `$\sum_{n=1}^{\infty}$`）
- PDF 抽取得到碎片文本（或乱码）
- 网页抽取的公式格式各异

**改进方向**：

1. **明确统一目标**：最终 Markdown 中所有公式统一为 LaTeX（行内 `$...$` / 独立行 `$$...$$`）。
2. **prompt 约束**：在 `generate_study_material` 的 instructions 里要求：公式必须用 LaTeX，并且不得输出“半个公式”。
3. **后处理规范化**：对明显的碎片公式文本：
   - 能识别的尝试转 LaTeX（谨慎）
   - 不能识别的标注为不可用并跳过（比污染正文更好）

**建议验收**：

- 文档中不出现明显“公式碎片垃圾文本”；公式呈现方式一致。

---

## 八、来源引用质量与格式问题（P3 / Low）

**现象**：

- 部分引用只有 URL 没有有意义标题（如 `[1-5](https://...)`）
- PDF 链接对读者不友好（无法直接在 Markdown 内阅读）
- 缺少对来源可靠性的基本提示

**改进方向**：

1. **引用格式标准化**：统一为 `- [标题](URL) — 1~2 句摘要/用途说明`
2. **来源类型标注**：如 `[PDF课件]`、`[百科]`、`[高票问答]`、`[教材/讲义]`
3. **可信度提示**：给出简单分级（例如：高校/出版社 > 百科 > 博客/论坛），并在展示时优先排序

**建议验收**：

- 每个引用“可扫读”：读者不点开链接也能知道它是什么、能干什么、是否值得信任。

---

## 九、缺乏知识点间的关联与学习路径（P3 / Low）

**现象**：知识点之间缺少前置依赖与学习路线（如“极限 → 导数 → 积分”），材料更像“平铺百科”而非“可学的课程”。

**改进方向**：

1. **学习路线图**：在文档开头增加“学习路径/知识图谱”（可用简单箭头或列表）。
2. **交叉引用**：每个知识点增加“前置知识 / 后续应用 / 推荐练习顺序”。
3. **生成阶段引导**：要求 LLM 在讲解中自然引用已讲概念，并提醒读者先学什么再学什么。

**建议验收**：

- 读者能从文档中看出“先后顺序”和“为什么要学这个”，降低迷路感。

---

## 十、整体架构层面建议（跨模块）

| 方面 | 现状 | 建议（更偏工程落地） |
|---|---|---|
| 内容质量验证 | 弱/不系统 | 生成后增加 `review_content` 的硬性门槛（完整性、乱码、引用）并自动触发 `revise_markdown` |
| 空内容处理 | 输出“未检索到…”占位符 | 检索失败时回退：降低检索严格度 → 换 query → LLM 兜底生成（并标注来源） |
| 输出长度控制 | 单次生成易触顶 | 按知识点、按小节拆分生成；必要时对每段设置 max_tokens 并拼接 |
| 可观测性 | 依赖日志肉眼看 | 给每个知识点统计：来源数/正文字符数/题目数/LLM token；形成一份简短 “质量报告” |
| 用户反馈闭环 | 无 | 支持用户标记“有误/太浅/太难/需要更多例题”，把反馈写入下一轮 prompt 或计划 |
| 缓存与增量更新 | 基本无 | 对“成功的百科/网页抽取/题库结果”做缓存；失败的知识点支持单点重试，减少重复抓取与成本 |

---

## 附：验证与复现建议（本地）

1. 启动后端：`python -m uvicorn backend.app:app --reload --port 8000`
2. 触发生成：
   - Web UI：进入「自学资料」页面，输入主题开始生成；生成过程中刷新页面，验证能自动续流并恢复进度。
   - API：调用 `POST /api/study-materials/generate`（首个事件 `task_started` 中会返回 `task_id`）。
3. 验证“可重连”：
   - 中途断开 SSE（或刷新浏览器）后，使用 `GET /api/study-materials/tasks/{task_id}/stream?after_seq=...` 续流。
   - 确认 `seq` 单调递增，且重连后不会重复拼接文本/步骤。
4. 对比产物：检查 `study_archives/` 下新的 Markdown 与基线样例的差异，重点关注：
   - PDF 抽取是否还会产生乱码段落
   - 百科/网页是否仍混入 UI 噪音
   - 每个知识点例题/练习是否补齐
   - 是否存在半句截断

---

*本路线图基于 `study_archives/微积分_20260209_113100.md` 的现象总结；核心代码主要位于 `backend/agent/executor.py`，调度逻辑位于 `backend/agent/planner.py`。*
