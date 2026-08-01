# 作者 Agent 制自学资料生成架构设计稿

> 日期：2026-08-01
>
> 依据：2026-08-01 代码库调查（generation/orchestrator/workflow/quality_gate、agent 写作链、evals benchmark、检索链路与前端流式层均已回读核实）
>
> 性质：设计稿，已经用户逐块评审确认；尚未动工。
>
> 边界：只重写「从大纲到成稿」的写作子系统与检索调用方式；任务编排/SSE/归档/导出/验收门框架等外围基建保留。

## 1. 背景与诊断

### 1.1 现状

- 双运行时并存：默认 legacy AgentCore（无质量门），可选 Codex 六阶段工作流（plan→research→draft→review→revise→accept + 质量门，`backend/generation/study_materials/workflow.py:226`）。
- 评测体系已完备：Challenge v2 benchmark（`backend/evals/study_materials/`，六维评分 + 四道成熟度门槛），但真实产物成熟度分仅 9（`docs/STUDY_MATERIALS_BENCHMARK.md` 校准记录）。
- 已确证的结构性缺口：
  - 证据链断裂：`refs_by_kp` 收集后从不渲染（`backend/agent/tools/knowledge/study_archive.py:255` 有注释无渲染），写手 prompt 明令禁止 URL 与引用标记——引用维度结构性 0 分。
  - 学习闭环不进终稿：例题/自测/答案生成了但汇编不渲染；无学习目标与前置知识。
  - 图表稀缺：实际样例 0 图 0 表；兜底提示泄漏进正文（`study_archive.py:250-252`）。

### 1.2 用户痛点（本次设计的出发点）

用户实测反馈：图表过少；语言、结构僵硬；缺少严谨性与通俗性；前沿知识有错；节间连接生硬、前后无关；"易错点"并非真正的易错点而是套话。

### 1.3 病因分析

| 痛点 | 根因 |
| --- | --- |
| 结构僵硬、前后无关 | 每个知识点由独立写手 agent 用同一套固定小节模板并行写完再拼接；写手互不可见 |
| "易错点"是套话 | 写手被要求必须写易错点，但无任何真实依据，只能编造 |
| 前沿知识有错 | 草稿无逐条事实核查环节；研究阶段 `source_facts` 置信度未用于成稿校验 |
| 图表过少 | 配图是写作完成后的可选附加步骤，缺席时正文连图位规划都没有 |
| 检索慢 | 检索前套 LLM 拆子问题（默认开启）+ deep/research 档工具内嵌递归 LLM 引擎（单知识点最多 ~24 次搜索 + 25+ 次 LLM 调用）+ provider 级联重试（见 §8） |

## 2. 目标与非目标

**目标**

1. 成稿连贯：全书一条叙事线，节间有真实承接，无模板感。
2. 内容可信：易错点必须有出处；前沿论断逐条核查；无据论断不进终稿。
3. 图文配套：配图是蓝图阶段规划的一等公民，有渲染、有兜底。
4. 过程全透明：包括思考过程（CoT 增量）在内的所有 LLM/工具调用，前端可展示、可回放。
5. 不漏点：TODO 驱动的硬门槛，漏项机制性不可能静默发生。

**非目标**

- 不重构任务编排、SSE 帧协议、归档/版本/导出基建（仅按需扩展事件类型）。
- 不做站点级网页噪音清洗与 PDF 深度解析（沿用既有"需独立项目"结论）。
- 不追求恢复 per-KP 全并行写作的极限速度（顺序主干 + 并行填充已是平衡点）。

## 3. 总体架构：单一作者 Agent 制

不再是"研究阶段 → N 个并行写手 → 拼接"，而是一个主 agent（**作者**）走完调研与主干创作，细分小节正文委托一层子 agent 并行填充：

```
RESEARCH(作者) → BLUEPRINT(作者) → BACKBONE(作者) → TODO分解(作者)
→ FILL(子AI并行,一层) ∥ FIG(MCP异步) → ASSEMBLE(确定性汇编)
→ AUDIT(作者+独立复核) → REVIEW/REVISE → ACCEPT
```

- **作者对全书负责**：研究笔记、蓝图、主干、统稿、兜底补写都由它亲笔完成——"像真正的 agent 在制作书本：调研之后自己写作"。
- **子 agent 仅一层**，只填充小节正文（`[[FILL:sec-id]]`），无权改动主干。
- **配图委托 MCP 封装的子 AI**（`figure-forge`），异步生成，汇编时回填（`[[FIG:n]]`）。
- 复用 `backend/generation/study_materials/agentic/` 的 AgentRunSpec/预算/工具白名单骨架；六阶段状态机重写 DRAFT→REVIEW→REVISE 段，外围（orchestrator/SSE/归档/导出）不动。

## 4. 作者笔记与上下文工程

一本 deep/research 档的书 + 全部证据远超任何上下文窗口，作者像真人一样**依赖外部笔记而非纯记忆**。笔记为落盘文件，agent 通过读文件工具随取，全部纳入任务快照并可作为 trace 事件（`note_write`）：

| 文件 | 作者 | 内容 | 消费者 |
| --- | --- | --- | --- |
| `notes/research.md`（按主题分节） | 作者（RESEARCH） | 事实、出处、置信度；**带出处的真实易错点**（专门用"常见错误/误区/misconception"类查询挖掘）；挖不到可靠误区的节显式标记"无" | 作者、填充子 AI（切片）、AUDIT |
| `notes/blueprint.md` | 作者（BLUEPRINT） | 叙事弧线、小节清单及每节目的/要点/长度/难度、**术语与符号约定表**、**配图计划**（槽位/意图/类型/标题）、前沿/争议置信标注 | 全体 |
| `notes/backbone.md` | 作者（BACKBONE） | 全书骨架文档（见 §5.1） | 填充子 AI（片段）、汇编器、前端早期渲染 |
| `notes/sections/{sec-id}.summary.md` | 作者（统稿时补） | "写给未来的我"：本节讲了什么、用到哪些记号、与邻节关系 | AUDIT/REVISE |
| `todos.json` | 作者维护 | 结构化 TODO（见 §5.3） | 编排器、验收门、前端 |
| `sections/{sec-id}.md` | 填充子 AI | 小节正文片段 | 汇编器 |

断点续跑改为**按 TODO/节边界恢复**（替代 `resume.py` 现有阶段重定位猜测）。

## 5. 两级写作

### 5.1 主干（BACKBONE，作者亲笔）

骨架文档包含：书名页/meta、全书导言（为什么学、怎么读、各章关系）、每章导语与**学习目标**、**节间衔接段**（解决"前后无关"的核心载体）、每小节开头引入段（本节要回答什么、与上节关系）、全书总结章、术语表。小节正文留 `[[FILL:sec-id]]`，图位留 `[[FIG:n]]`。

颗粒度已确认：主干写到「小节引入段」为止，核心讲解正文归子 AI。

### 5.2 填充（FILL，一层子 AI 并行）

每个子 AI 拿到**有界上下文**：所属章节主干片段（导语+本节引入+相邻衔接段）、蓝图中本节规格、术语符号表、按节切好的研究笔记切片、写作规范（LaTeX 定界符、`[EXn]/[Qn]/[An]` 标签、易错点仅可用笔记中带出处的、禁 URL/引用标记——沿用现有 prompt 契约）。

**验收循环**：片段返回 → 确定性检查（结构 lint、术语一致性、占位符清零）→ 作者抽查内容 → 不合格打回重写（默认 ≤2 次）→ 仍不合格**作者亲自补写**（兜底已确认，保证没有交不出的节）。

### 5.3 TODO 驱动

作者在 BLUEPRINT 后把整本书分解为 `todos.json`，每条： `{id, type: research|backbone|fill|fig|audit|revision, ref, acceptance, deps, status, retries}`。

- 作者每完成一步更新清单；**验收门新增硬规则：TODO 全部完成或显式豁免**，漏点机制性不可能静默。
- 天然收益：续跑 = 从 pending TODO 恢复；前端进度 = 真实清单而非视图推断。

### 5.4 汇编（ASSEMBLE，确定性）

汇编器按主干占位符逐一替换（每个 `[[FILL:sec-id]]` 对应 `sections/{sec-id}.md`，每个 `[[FIG:n]]` 对应产物 URL）。**替换不到就报错进 REVISE，绝不留占位符进终稿**；任何机器兜底说明不进正文（修掉 `study_archive.py:250` 泄漏）。参考文献由汇编器从研究笔记统一渲染为文末书目（修掉 `refs_by_kp` 只收集不渲染的缺口）。

## 6. 配图 MCP 子 AI（figure-forge）

- **契约**：`design_and_render({intent, kind: auto|tikz|mermaid|manim|image, content_spec, caption})` → 异步返回 `figure_id`；作者留占位符继续写，汇编时回填 `![caption](artifact_url)`。
- **内部**：子 AI 生成 TikZ/Mermaid/Manim 代码或图像 prompt → 沙箱渲染（复用 `docker/latex-sandbox`、`docker/manim-sandbox`）→ 自检（编译通过、尺寸合法）→ 有界重试 → 产物 URL 或结构化失败。Mermaid 服务端预渲染 SVG，前端零改动。
- **trace 回传**：代码、每次渲染尝试、编译日志全部作为 `figure_trace` 事件挂任务时间线（§9 无隐藏调用）。
- **失败兜底链**：换引擎重试 → 降级为表格/文字替代 → 省略并修正正文引用；失败只记入 quality report。

## 7. AUDIT / REVIEW / REVISE

- **AUDIT**：抽取成稿可检验论断（前沿/争议全查），逐条对照研究笔记；无据论断改写、降级为推断措辞或删除。作者自查 + 现有 `review_content` 独立复核双保险。
- **REVISE 由作者本人执行**（它知道当初为什么这么写）；沿用现有验收门与 `quality_degraded` 降级交付机制。
- 易错点溯源为确定性检查：每条必须回链到研究笔记出处，否则不计分。

## 8. 检索链路薄封装化

现状（已核实）：`web_search_knowledge` 每次调用先经一次 LLM 拆子问题（`web_search_knowledge_impl.py:339`，`STUDY_MATERIALS_WEB_DECOMPOSE` 默认 True）；deep/research 档走 `deep_research` 递归引擎（`deep_research.py:306`），每轮 1 次 LLM 生成 SERP 查询 + 每条结果 1 次 LLM 提炼 learnings，research 档 breadth=6/depth=3/max_queries=24（`:68`）——单知识点 ~24 次搜索 + 25+ 次 LLM 调用，且这些内部 LLM 调用对事件流完全不可见。再叠加 Tavily→Exa→Metaso 级联重试。

**改造**：

1. 作者自己就是 LLM——它带研究意图直接构造查询，**删除 decompose 层**。
2. "检索→读→决定下一轮查什么"由作者主循环承担，**退役工具内嵌递归引擎**；搜索工具退化为薄封装（SERP + 页面抓取）。
3. 保留：结果缓存、熔断、provider 健康标记、并发信号量——全部留在薄封装层。
4. 研究质量门保留，验收对象改为作者的研究笔记（不达标打回补查，`research` 类 TODO）。

收益：每次检索少一次 LLM 往返；研究过程完全可观测（§9 的必需前提）。

## 9. 全链路透明（含思考过程）

**架构不变量：无隐藏调用**——任何 LLM 调用、任何工具调用都必须发生在会向事件流发事件的层。

**统一 trace 模型**：沿用 DB 事件溯源，每条事件带归属路径 `agent_path`（`main` / `fill:sec-3.2` / `fig:2`）。新增/规范事件：

| 事件 | 说明 |
| --- | --- |
| `thinking_delta` | 统一思考增量（规范 legacy `thinking` 与 codex `reasoning_delta` 为一个类型），随写随流 |
| `note_write` | 笔记/蓝图/主干落笔（附内容或 diff） |
| `todo_update` | TODO 状态变更 |
| `tool_call` | 含搜索查询与结果摘要（现有，补齐归属路径） |
| `subagent_spawn/end` | 复用 2026-07-31 已落地的子代理可见性契约 |
| `figure_trace` | 配图代码、渲染尝试、产物 URL |

**与追赶压缩的冲突解法**：现有 >800 条落后折叠 thinking/text_delta（`orchestrator.py:115-149`）只用于实时追赶通道；**完整 trace 永不丢弃**，前端"过程"面板按 seq 分页拉全量。存储侧加任务级事件 TTL：只清理瞬态增量，保留事件骨架（想了什么、调了什么、结果如何）。

**前端**：

- 生成页双栏：左「创作过程」（嵌套时间线：思考块可折叠、工具调用卡、TODO 实时勾选、笔记落笔、子 AI 泳道含其思考与工具调用），右「文稿」（主干骨架先行渲染，占位符显示"撰写中"，FILL 完成逐节点亮）。
- 断线重连后过程面板从 DB 全量回放，与直播无差别；档案详情页同样可回看完整 trace。
- 改动点集中在：`features/study-materials/`（新过程面板替换 `ui/stage-progress.tsx` 的视图推断）、`streaming/contract.ts`（新事件解码）、`model/reducer.ts`（新状态）。markdown-view 不动（图为 SVG/PNG URL）。

## 10. 质量门与评估更新

- 新硬门槛：**TODO 清零**、**占位符清零**、术语一致性。
- benchmark（Challenge v2）经现有 `--llm-judge` 通道增加 LLM rubric 维度：连贯性、文风自然度、易错点真实性——确定性正则测不了的三项，即用户痛点本体。
- 保留四道成熟度门槛与 golden/低分双锚点；新增架构的 golden fixture。

## 11. 错误处理矩阵

| 故障 | 处置 |
| --- | --- |
| 填充子 AI 失败/不合格 | 重试 ≤2 → 作者亲自补写 |
| 配图失败 | 换引擎 → 表格/文字替代 → 省略并修正正文；只记 quality report |
| 检索中断 | 沿用熔断 + 研究门重试 + `quality_degraded` 降级交付 |
| 任意阶段任务失败 | 从 pending TODO 恢复（`recovery_available`） |
| 汇编发现占位符未填 | 报错进 REVISE，不进终稿 |
| 事件存储膨胀 | 瞬态增量 TTL 清理，保留骨架 |

## 12. 测试策略

- 新 prompt（blueprint/backbone/fill-worker/figure-spec/audit）走现有 prompt 契约测试（`prompt_contracts.py`）。
- 汇编器单测：占位符替换、漏填报错、书目渲染。
- TODO 门槛与恢复：从各 pending 状态恢复的单元/集成测试。
- 检索薄封装：decompose 删除后的回归（`test_web_search_knowledge_resilience.py` 适配）。
- benchmark：dry-run 全量 + golden fixture 复评（`--regrade`）。
- 前端：新事件解码/reducer 的 Vitest；生成页 Playwright 快照更新（Windows `*-win32.png`）。

## 13. 与现有代码的映射

| 保留/复用 | 重写 | 新增 | 退役 |
| --- | --- | --- | --- |
| orchestrator/SSE 帧/归档/导出/版本历史、质量门框架、验收记录、research 工具缓存熔断、agentic runtime 骨架、子代理事件契约、markdown-view | workflow.py 的 DRAFT→REVIEW→REVISE 段、写手链（`study_material_generation.py` 的 per-KP writer 由 fill 子 AI 取代）、`resume.py`（按 TODO 恢复） | 笔记文件约定、TODO 模型与门槛、汇编器（占位符替换+书目渲染）、figure-forge MCP、统一 trace 事件、过程面板前端 | decompose LLM 层、工具内嵌 deep_research 递归引擎、per-KP 固定小节模板 |

legacy AgentCore 与 codex staged 双运行时在新写作子系统落地后收敛为单一作者运行时（收敛方案在实施计划中细化）。

## 14. 风险与权衡

- **时延**：主干与统稿是顺序的，deep/research 档总时长可能上升；缓解：检索批量并行、配图异步、FILL 并行、preset 控制规模。
- **长运行上下文**：依赖笔记文件纪律；若作者笔记质量差，填充切片随之差——研究门与蓝图契约是第一道防线。
- **子 AI 文气不一**：主干引入段+术语表+作者统稿三重约束；LLM rubric 文风维度兜底度量。
- **事件量**：全透明使事件量显著增长；TTL 与分页回放是必要的配套，不能省。

## 15. 后续

实施计划由 writing-plans 技能另行产出（分期：①检索薄封装+笔记/TODO 基建 ②作者主干+填充+汇编 ③figure-forge ④trace 与前端 ⑤评估与收敛）。
