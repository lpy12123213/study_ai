# 配置说明（Configuration）

本项目主要通过两类配置控制运行行为：

- 环境变量（`.env` / 系统环境变量）
- 模型与供应商配置（`config/model.json`）

建议从 `.env.example` 开始，复制并按需修改：

```powershell
Copy-Item .env.example .env
```

然后用 `start.bat setup` / `start.bat dev` 启动。

## 1. LLM（模型与渠道）

后端读取配置的优先级大致为：

1. 读取 repo 根目录 `.env`（不会覆盖同名的系统环境变量）
2. 读取 `config/model.json`（若存在，会覆盖对应 provider 的 `api_key/base_url`）
3. 若启用 pinned 模式，则强制使用 `config/model.json` 里的 `active_provider`
4. 否则走环境变量的 `CHAT_PROVIDER`（默认 `openrouter`）

常用环境变量（见 `.env.example`）：

- `CHAT_PROVIDER`: `openrouter` / `fireworks` / `moonshot`
- `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`
- `FIREWORKS_API_KEY`, `FIREWORKS_BASE_URL`
- `MOONSHOT_API_KEY`, `MOONSHOT_BASE_URL`
- `MAIN_MODEL`, `SUB_MODEL`（以及 temperature/max_tokens）
- `LLM_PROVIDER_PINNED=1`：锁定 provider，避免自动切换

Token 计数说明：
- 后端会做 best-effort 的 token 估算；如果安装了 `tiktoken`，会使用更准确的计数逻辑。

`config/model.json` 说明（示例结构，字段可能随版本扩展）：

```json
{
  "active_provider": "openrouter",
  "pinned": false,
  "providers": {
    "openrouter": { "base_url": "...", "api_key": "..." },
    "fireworks": { "base_url": "...", "api_key": "..." },
    "moonshot": { "base_url": "...", "api_key": "..." }
  },
  "models": {
    "main": "openai/gpt-4.1-mini",
    "sub": "openai/gpt-4.1-mini",
    "lesson_plan": "openai/gpt-4.1-mini",
    "review": "openai/gpt-4.1-mini"
  }
}
```

提示：
- `active_provider=openrouter` 且 `models.main=moonshotai/kimi-*` 这类情况也正常：OpenRouter 会路由到对应模型。
- 如果你在 OpenRouter 控制台看不到调用记录，优先检查运行时 `CHAT_PROVIDER` 是否为 `openrouter`，以及是否被 pinned 到其他 provider。

## 2. AI 出题（Question Library）

AI 出题与本地题库的运行期缓存、后台打分与任务池参数主要由以下环境变量控制：

- `QUESTION_LIBRARY_MAX_TASKS`：内存任务池容量（默认 `50`）
- `QUESTION_LIBRARY_TASK_TTL_S`：任务保留时间（秒，默认 `3600`）
- `QUESTION_LIBRARY_TASK_MAX_EVENTS`：单任务最多保留事件数（默认 `8000`）
- `QUESTION_LIBRARY_REALIZE_MAX_TOKENS`：草稿生成（realize）最大 tokens；不设置时会跟随 `LESSON_PLAN_MAX_TOKENS` 并保证最小预算
- `QUESTION_LIBRARY_JUDGE_MODEL`：审题模型（留空用默认 lesson_plan 模型）
- `QUESTION_LIBRARY_MCP_SEARCH_MODEL`：CLI 出题前的“素材检索”阶段使用的模型。默认值通常为 `openai/gpt-5-mini`；当当前 provider 为 `ikuncode` 且主出题模型是 `gpt-*` 时，会自动复用该 GPT 模型（例如 `gpt-5.2`），避免错误携带 OpenRouter 风格的模型前缀。该阶段依赖 tools + 引用 URL，建议选择支持 tool-calling 的模型。

出题素材联网搜索（可选）：

- `EXA_API_KEY`：推荐，Exa 搜索（更适合“时兴/热点素材”检索，支持按发布日期筛选）
- `ZHIPU_API_KEY`：可选，智谱 BigModel MCP（无 Exa key 时会尝试作为 fallback；未配置会出现 401）

题库后台自动打分（可选）：

- `QUESTION_LIBRARY_AUTO_SCORE=1`：开启后台批量打分
- `QUESTION_LIBRARY_SCORE_INTERVAL_S`：打分间隔（秒，默认 `20`）
- `QUESTION_LIBRARY_SCORE_BATCH`：单次打分数量（默认 `20`）
- `QUESTION_LIBRARY_HIDE_THRESHOLD`：低于阈值自动隐藏（默认 `70`）
- `QUESTION_LIBRARY_SCORE_MODEL`：打分模型（默认回落到 lesson_plan 模型）

## 3. 试卷导出（Markdown/LaTeX/PDF/DOCX）

试卷导出由 `backend/paper_compose/export.py` 驱动，关键环境变量：

- `PAPER_EXPORT_LATEX_ENGINE`：LaTeX 引擎（默认自动探测 `xelatex`/`pdflatex`）
- `PAPER_EXPORT_LATEX_TIMEOUT_S`：LaTeX 编译超时（秒，默认 `30`）
- `PAPER_EXPORT_DOCX_ENGINE`：DOCX 导出引擎（建议 `pandoc`；留空则自动探测）
- `PAPER_EXPORT_PANDOC_TIMEOUT_S`：pandoc 导出超时（秒，默认 `60`）

## 4. 画布版本（Canvas History）

为了防止版本历史无限增长，可设置：

- `CANVAS_VERSION_MAX_KEEP`：每个画布保留的历史版本数量（默认 `30`，上限 `500`）

## 5. OpenTelemetry（可选）

后端支持可选的 OpenTelemetry tracing（默认不启用）。启用后 JSON 日志会包含 `trace_id` 字段。

- `OTEL_ENABLE=1`：开启 tracing
- `OTEL_SERVICE_NAME=study_ai`：服务名
- `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces`：OTLP/HTTP exporter endpoint

说明：需要安装对应依赖（`opentelemetry-*`）。未安装时后端会自动跳过，不影响运行。
