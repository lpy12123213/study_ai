# 自学资料生成质量指南

本文记录自学资料生成链路的维护口径、质量标准和常见问题。它不是单次计划，而是用于排查质量、稳定性和体验问题的长期指南。

## 当前链路

主要入口：

- `POST /api/study-materials/generate`
- `POST /api/study-materials/tasks/{task_id}/continue`（续作模式：improve / deepen_research / fix_export / skip_export / resume_failed_stage / retry_search / replan_from_failure）
- `GET /api/study-materials/tasks/{task_id}`
- `GET /api/study-materials/tasks/{task_id}/stream?after_seq=<last_seq>`
- `POST /api/tasks/{task_id}/cancel`：服务端真实取消，不再只是前端断开连接

相关模块：

- `backend/generation/study_materials/`：Codex 分阶段工作流（workflow / codex_stages / quality_gate / coverage / tool_executor / resume / orchestrator）
- `backend/core/text_lint.py`：生成文本轻量 lint（截断、占位符、未闭合结构）
- `backend/agent/tools/`：legacy AgentCore 路径的检索、分析、生成工具
- `backend/generation/agentic/`：agent spec 与 Codex runtime
- `frontend/src/features/study-materials/`：阶段进度、知识点看板、质量报告、降级提示与版本历史 UI

典型阶段（Codex 分阶段工作流）：

1. plan：Codex 把主题拆成可教学、互不重复的知识点，并给出检索查询。
2. research：后端工具按知识点并发检索，质量门逐点评估证据数与来源类别数。
3. draft：Codex 仅依据已验证证据写完整 Markdown 和 coverage_map。
4. review：后端 review 工具独立审查，`coverage.py` 按知识点小节验收，`text_lint` 做结构检查。
5. revise：Codex 按审查问题定向修订，最多 `max_review_cycles` 轮。
6. accept：复评通过则落验收记录并归档；修订预算用尽但已有成稿时降级交付。
7. 可选导出 Markdown / LaTeX / PDF。

`STUDY_MATERIALS_AGENT_RUNTIME` 留空时走不依赖 Codex CLI 的 legacy AgentCore 路径。Codex 阶段结果缺失且 `CODEX_RUNTIME_FALLBACK_LEGACY=1` 时显式回退 legacy：回退一定留 `study_materials_codex_fallback_to_legacy` 日志和 `codex_fallback_to_legacy` 任务事件，绝不静默切换。

质量与稳定性机制（2026-07 起）：

- 质量门：`quality_gate.py` 按 preset（quick / standard / deep / research）定义 `min_sources` / `min_source_classes` / `min_dimensions` / `max_review_cycles` / `max_research_cycles` / `max_consecutive_tool_failures`；每次评估广播 `quality_report` 事件。
- 检索重试：研究门未过且还有预算时发 `research_retry_required`（point_ids、attempt、remaining_attempts），只对未通过的知识点补检；预算耗尽报 `quality_gate_not_met`。
- 工具熔断：连续工具失败达到 `max_consecutive_tool_failures`（各 preset 默认 3）判定检索链路整体不可用，以 `research_tool_outage` 失败（recoverable），前端可据此发起 retry_search / deepen_research 续作。
- 按知识点验收：`coverage.py` 把 Markdown 二级标题小节归属到知识点，逐点检查 `draft_section_unmatched` / `coverage_map_mismatch` / `kp_dimensions_missing`（每点必须含“定义/概念”并覆盖足够维度），结果体现在 `quality_report.per_knowledge_point`。
- 降级交付：修订预算用尽但已有成稿时发 `quality_degraded`（issues、revision_attempts），结果带 `degraded=true`、`material.passed=false`、`material.issues=[...]`；降级产物不写验收记录，不会被归档复用。
- 真实取消：`POST /api/tasks/{task_id}/cancel` 先走任务运行时取消，运行时找不到再直接落库 `canceled` 并追加 `task_canceled` 步骤事件；前端收到确认后终止本地流。
- 事件溯源冷续作：DB 任务行（request / result / 事件流）是唯一事实来源；`.local/study_materials/tasks/*.json` 快照只是可重建的缓存。快照缺失时依次从 result 载荷、已入档成稿、事件流重放重建续作上下文。
- 归档新鲜度：归档复用要求验收记录与当前 preset、草稿哈希、策略版本一致，且不超过 `STUDY_MATERIALS_ARCHIVE_MAX_AGE_S`（默认 14 天，0 表示不过期）。

## 质量目标

每份资料应尽量满足：

- 结构完整：有目标、知识点、讲解、例题/练习、总结和来源。
- 来源可追溯：重要结论有链接或来源摘要。
- 数学表达稳定：公式统一使用 Markdown/LaTeX。
- 不污染正文：网页导航、PDF 乱码、无关版权脚注不进入主内容。
- 门控可信：每个知识点通过研究门和验收门；未全过但必须交付时明确标记降级。
- 可恢复：刷新或断线后能通过任务流继续查看；本地快照丢失也能从 DB 重建。
- 可继续：用户能基于已有任务发起改进或扩展。

## 常见问题与处理

### 网页噪音

表现：

- 正文混入导航、登录、版权、推荐阅读、广告。

处理方向：

- 优先使用搜索 provider 的摘要和来源，而不是整页纯文本。
- 对抓取正文做站点级清洗。
- 抽取质量低时保留链接，不把噪音写入正文。

注：系统性的来源清洗仍未做，见“改进状态”。

### PDF 解析污染

表现：

- 公式变成零散字符。
- 段落顺序混乱。

处理方向：

- 识别 PDF 后降级为来源链接或摘要。
- 需要深度解析时引入专用 PDF 文本提取或 OCR，不要把坏文本直接写入正文。

注：PDF 降级与来源清洗同属一个独立项目，本次未做，见“改进状态”。

### 输出截断

表现：

- 句子中途停止。
- Markdown 或 LaTeX 块没有闭合。

处理方向：

- 现在由 `backend/core/text_lint.py` 在验收门自动检测：`unclosed_display_math`（独立公式未闭合）、`heading_with_empty_body`（空标题）、`eof_mid_sentence`（句末截断），另有 `unclosed_code_fence` / `unbalanced_inline_math` / `unresolved_placeholder`。
- 命中 lint 信号会产生 `markdown_lint_failed` 失败项并触发定向 revise；`content_review` 工具同样消费这些信号。
- 兜底仍是提高对应 `*_MAX_TOKENS` 和续写次数。

相关配置：

- `STUDY_MATERIALS_WRITER_MAX_TOKENS`
- `STUDY_MATERIALS_MAX_CONTINUATIONS`
- `STUDY_MATERIALS_LATEX_MAX_TOKENS`
- `STUDY_MATERIALS_LATEX_REFINE_MAX_TOKENS`

### 检索不足

表现：

- 来源太少，研究门报 `research_evidence_missing` / `source_classes_missing`。
- 内容偏泛。
- 例题缺失。

处理方向：

- 链路会自动对未通过的知识点补检并广播 `research_retry_required`，预算为 preset 的 `max_research_cycles`；预算耗尽才报 `quality_gate_not_met`。
- 所有检索工具连续失败达到 `max_consecutive_tool_failures`（默认 3）判定整体 outage，以 `research_tool_outage` 失败，可用 retry_search / deepen_research 续作恢复。
- 开启 query 拆分：`STUDY_MATERIALS_WEB_DECOMPOSE=1`
- 增加子问题数量：`STUDY_MATERIALS_WEB_SUBQUERIES`
- 使用 `deep` 或 `research` preset。
- 配置 Tavily、Exa、Metaso 等至少一个搜索 provider。

### 质量门反复不通过（降级交付）

表现：

- 事件流里反复出现 `revision_required` / `research_retry_required`，最后收到 `quality_degraded`。

处理方向：

- 这是尽力交付：修订/检索预算用尽但已有成稿。结果可读，但 `degraded=true`、`material.passed=false`，`material.issues` 列出未通过的检查。
- 降级产物不落验收记录、不会被归档复用；下次同主题请求会重新生成。
- 想继续提升质量，用 improve / deepen_research 续作，而不是重新发起全新任务。

### 用户刷新丢进度

表现：

- 页面刷新后看不到后续事件。
- 重连后重复拼接。

处理方向：

- 事件写入 DB 且带递增 `seq`，前端用 `/api/study-materials/tasks/{task_id}/stream?after_seq=<last_seq>` 续流，客户端保存最后处理的 `seq`。
- DB 是事实来源：本地快照（`.local/study_materials/tasks/`）只是可重建缓存，冷续作能从 result 载荷、已入档成稿或事件流重放重建上下文。
- 需要真正停止任务时用 `POST /api/tasks/{task_id}/cancel`，不要只关页面。

## 关键配置

```bash
STUDY_MATERIALS_PRESET=standard
STUDY_MATERIALS_SUBAGENT_CONCURRENCY=3
STUDY_MATERIALS_STAGE_PROMPT_MAX_CHARS=30000
STUDY_MATERIALS_SEARCH_MODE=
STUDY_MATERIALS_WEB_DECOMPOSE=1
STUDY_MATERIALS_WEB_SUBQUERIES=4
STUDY_MATERIALS_THINKING_MODEL=
STUDY_MATERIALS_WRITER_MODEL=
STUDY_MATERIALS_STEP_TIMEOUT_S=240
STUDY_MATERIALS_SSE_HEARTBEAT_S=4
STUDY_MATERIALS_TASK_TTL_S=3600
STUDY_MATERIALS_TASK_MAX_EVENTS=8000
STUDY_MATERIALS_ARCHIVE_MAX_AGE_S=1209600
```

说明：

- `STUDY_MATERIALS_STAGE_PROMPT_MAX_CHARS`：单阶段 Codex worker 提示词载荷上限（默认 30000），超出时先按知识点裁剪研究证据、再按剩余预算截断正文。
- `STUDY_MATERIALS_ARCHIVE_MAX_AGE_S`：归档自动复用的新鲜度上限（默认 1209600 = 14 天，0 表示不做时间过期）。
- 各 preset 的质量门预算（min_sources / max_review_cycles / max_research_cycles 等）在 `quality_gate.py` 的 `PRESET_PROFILES` 中，不是环境变量。

搜索 provider：

```bash
TAVILY_API_KEY=
EXA_API_KEY=
METASO_API_KEY=
```

## 验收清单

一次自学资料生成完成后，至少抽查：

- 没有明显网页 UI 噪音。
- 没有 PDF 公式乱码进入正文。
- `quality_report.per_knowledge_point` 中每个知识点 `passed=true`；若有未通过项，结果应是降级交付（`degraded=true`）且 `material.issues` 写清原因。
- 正文无 `text_lint` 截断/残留信号（`markdown_lint_failed` 不出现在 failed_checks 里）。
- 引用链接可打开或有清晰失败说明。
- 长任务事件包含递增 `seq`，刷新后可用 `after_seq` 续流；删掉本地快照后仍能从 DB 重建任务状态。
- `POST /api/tasks/{task_id}/cancel` 后任务状态变为 `canceled` 且事件流终止。
- LaTeX 转换失败时能返回可排查的错误或部分结果。

## 改进状态

状态口径：✅ 已实现 / 🚧 部分 / ⬜ 未做。

| 项目 | 状态 | 日期 | 证据 |
| --- | --- | --- | --- |
| 任务流稳定性（事件溯源冷续作、真实取消、检查点先落盘再广播） | ✅ 已实现 | 2026-07 | `backend/generation/study_materials/orchestrator.py`、`backend/generation/study_materials/workflow.py`、`backend/api/tasks.py` |
| 输出截断检测（未闭合独立公式/空标题/句末截断，质量门消费） | ✅ 已实现 | 2026-07 | `backend/core/text_lint.py`、`backend/generation/study_materials/quality_gate.py` |
| prompt 契约测试 | ✅ 已实现 | 2026-07 | `backend/tests/test_study_materials_prompt_contracts.py` |
| 检索重试与工具熔断 | ✅ 已实现 | 2026-07 | `backend/generation/study_materials/workflow.py`（research_retry_required）、`backend/generation/study_materials/tool_executor.py`（research_tool_outage） |
| 按知识点验收 | ✅ 已实现 | 2026-07 | `backend/generation/study_materials/coverage.py`、`backend/generation/study_materials/quality_gate.py` |
| 降级交付（best-effort） | ✅ 已实现 | 2026-07 | `backend/generation/study_materials/workflow.py`（quality_degraded / _degraded_result） |
| 归档新鲜度约束 | ✅ 已实现 | 2026-07 | `STUDY_MATERIALS_ARCHIVE_MAX_AGE_S`、`backend/generation/study_materials/orchestrator.py`（_archive_max_age_s） |
| 知识点看板与质量 UI | ✅ 已实现 | 2026-07 | `frontend/src/features/study-materials/ui/knowledge-point-board.tsx`、`material-result-card.tsx`、`stage-progress.tsx` |
| 版本历史 | ✅ 已实现 | 2026-07 | `frontend/src/features/study-materials/ui/material-result-card.tsx`、`GET /api/study-archives?base_fingerprint=` |
| 来源清洗和 PDF 降级 | ⬜ 未做 | — | 本次未做，需独立项目 |
| 更细的知识点拆分 | ⬜ 未做 | — | — |
| 来源可信度排序 | ⬜ 未做 | — | — |
| 例题兜底生成 | ⬜ 未做 | — | — |
| 用户反馈驱动的二次改写 | ⬜ 未做 | — | — |

## 相关文档

- `USER_GUIDE.md`：用户如何使用自学资料页面。
- `API.md`：任务接口和 SSE 续流。
- `CONFIGURATION.md`：环境变量与默认值。
