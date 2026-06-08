# 自学资料生成质量指南

本文记录自学资料生成链路的维护口径、质量标准和常见问题。它不是单次计划，而是用于排查质量、稳定性和体验问题的长期指南。

## 当前链路

主要入口：

- `POST /api/tasks/study-materials/generate`
- `POST /api/tasks/study-materials/{task_id}/continue`
- `GET /api/tasks/{task_id}`
- `GET /api/tasks/{task_id}/stream`

相关模块：

- `backend/study_materials/`
- `backend/generation/agentic/`
- `backend/agent/tools/knowledge/`
- `backend/agent/tools/search/`
- `backend/agent/tools/analysis/`
- `backend/agent/tools/generation/`

典型阶段：

1. 分析主题和知识点。
2. 联网检索或读取本地归档。
3. 对每个知识点做来源整理。
4. 写作讲解、示意图、例题或练习。
5. 审查、修订和归档。
6. 可选转换为 LaTeX / PDF。

## 质量目标

每份资料应尽量满足：

- 结构完整：有目标、知识点、讲解、例题/练习、总结和来源。
- 来源可追溯：重要结论有链接或来源摘要。
- 数学表达稳定：公式统一使用 Markdown/LaTeX。
- 不污染正文：网页导航、PDF 乱码、无关版权脚注不进入主内容。
- 可恢复：刷新或断线后能通过任务流继续查看。
- 可继续：用户能基于已有任务发起改进或扩展。

## 常见问题与处理

### 网页噪音

表现：

- 正文混入导航、登录、版权、推荐阅读、广告。

处理方向：

- 优先使用搜索 provider 的摘要和来源，而不是整页纯文本。
- 对抓取正文做站点级清洗。
- 抽取质量低时保留链接，不把噪音写入正文。

### PDF 解析污染

表现：

- 公式变成零散字符。
- 段落顺序混乱。

处理方向：

- 识别 PDF 后降级为来源链接或摘要。
- 需要深度解析时引入专用 PDF 文本提取或 OCR，不要把坏文本直接写入正文。

### 输出截断

表现：

- 句子中途停止。
- Markdown 或 LaTeX 块没有闭合。

处理方向：

- 提高对应 `*_MAX_TOKENS`。
- 使用续写逻辑。
- 在 review/revise 阶段检测未闭合结构。

相关配置：

- `STUDY_MATERIALS_WRITER_MAX_TOKENS`
- `STUDY_MATERIALS_MAX_CONTINUATIONS`
- `STUDY_MATERIALS_LATEX_MAX_TOKENS`
- `STUDY_MATERIALS_LATEX_REFINE_MAX_TOKENS`

### 检索不足

表现：

- 来源太少。
- 内容偏泛。
- 例题缺失。

处理方向：

- 开启 query 拆分：`STUDY_MATERIALS_WEB_DECOMPOSE=1`
- 增加子问题数量：`STUDY_MATERIALS_WEB_SUBQUERIES`
- 使用 `deep` 或 `research` preset。
- 配置 Tavily、Exa、Metaso 等至少一个搜索 provider。

### 用户刷新丢进度

表现：

- 页面刷新后看不到后续事件。
- 重连后重复拼接。

处理方向：

- 前端使用 `/api/tasks/{task_id}/stream?after_seq=<last_seq>`。
- 客户端保存最后处理的 `seq`。
- 后端任务事件写入数据库，避免只依赖内存。

## 关键配置

```bash
STUDY_MATERIALS_PRESET=standard
STUDY_MATERIALS_SUBAGENT_CONCURRENCY=3
STUDY_MATERIALS_SEARCH_MODE=
STUDY_MATERIALS_WEB_DECOMPOSE=1
STUDY_MATERIALS_WEB_SUBQUERIES=4
STUDY_MATERIALS_THINKING_MODEL=
STUDY_MATERIALS_WRITER_MODEL=
STUDY_MATERIALS_STEP_TIMEOUT_S=240
STUDY_MATERIALS_SSE_HEARTBEAT_S=4
STUDY_MATERIALS_TASK_TTL_S=3600
STUDY_MATERIALS_TASK_MAX_EVENTS=8000
```

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
- 每个核心知识点都有可读讲解。
- 引用链接可打开或有清晰失败说明。
- 长任务事件包含递增 `seq`，刷新后可续流。
- LaTeX 转换失败时能返回可排查的错误或部分结果。

## 改进优先级

优先做：

- 任务流稳定性。
- 来源清洗和 PDF 降级。
- 输出截断检测。
- prompt 契约测试。

后续做：

- 更细的知识点拆分。
- 来源可信度排序。
- 例题兜底生成。
- 用户反馈驱动的二次改写。

## 相关文档

- `USER_GUIDE.md`：用户如何使用自学资料页面。
- `API.md`：任务接口和 SSE 续流。
