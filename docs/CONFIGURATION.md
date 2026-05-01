# 配置说明

Study AI 主要通过 `.env`、系统环境变量和本地 `config/model.json` 配置。本文只记录当前代码读取和建议维护的配置项。

不要提交真实密钥、Cookie、本地数据库或抓取内容。

## 配置加载

后端会从仓库根目录加载 `.env`，并保留系统环境变量的优先级。核心代码在 `backend/core/settings.py`。

加载顺序：

1. 系统环境变量。
2. 仓库根目录 `.env`，不覆盖已存在的系统环境变量。
3. `config/model.json` 或 `MODEL_CONFIG_PATH` 指向的模型配置。
4. 代码默认值。

安全等级：

- Secret：API key、JWT secret、Cookie、管理员密码。
- Operational：超时、并发、任务池、导出工具链。
- Product：默认学科、生成预设、前端 API base URL。

Secret 配置不得出现在日志、文档示例真实值、测试快照或提交记录中。

推荐流程：

```powershell
Copy-Item .env.example .env
```

Linux / macOS：

```bash
cp .env.example .env
```

## 模型供应商

通用对话供应商：

- `CHAT_PROVIDER`: `openrouter` / `fireworks` / `moonshot`
- `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`
- `FIREWORKS_API_KEY`, `FIREWORKS_BASE_URL`
- `MOONSHOT_API_KEY`, `MOONSHOT_BASE_URL`
- `MAIN_MODEL`
- `SUB_MODEL`
- `MAIN_MODEL_TEMPERATURE`
- `MAIN_MODEL_MAX_TOKENS`
- `SUB_MODEL_TEMPERATURE`
- `SUB_MODEL_MAX_TOKENS`

本地模型配置文件：

- 默认路径：`config/model.json`
- 可用 `MODEL_CONFIG_PATH` 指向其他路径
- `LLM_PROVIDER_PINNED=1` 可锁定 active provider，避免根据模型名自动切换

示例结构：

```json
{
  "active_provider": "openrouter",
  "pinned": false,
  "providers": {
    "openrouter": {
      "base_url": "https://openrouter.ai/api/v1",
      "api_key": "sk-or-..."
    }
  },
  "models": {
    "main": "openai/gpt-5-mini",
    "sub": "openai/gpt-5-mini",
    "lesson_plan": "openai/gpt-5-mini"
  },
  "params": {
    "main_temperature": 0.7,
    "sub_temperature": 0.3,
    "thinking_effort": "xhigh"
  }
}
```

模型配置规则：

- `pinned=true` 时，以 `active_provider` 为准，不做自动 provider 推断。
- 模型名必须符合所选 provider 的格式。
- `main` 用于复杂推理和编排，`sub` 用于轻量提取、选择和判断。
- lesson plan、study materials 和 question library 可按需设置独立模型。

## 登录与权限

- `JWT_SECRET`：JWT 签名密钥，生产环境必须改成随机长字符串。
- `JWT_EXPIRE_HOURS`：token 过期小时数。
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `ADMIN_ROLE`

开发环境可使用 `.env.example` 中的占位值；共享或公网环境必须更换。

## 搜索与外部检索

自学资料、AI 出题、MCP 联网搜索可能使用：

- `TAVILY_API_KEY`, `TAVILY_BASE_URL`, `TAVILY_TIMEOUT`
- `EXA_API_KEY`, `EXA_BASE_URL`
- `METASO_API_KEY`, `METASO_BASE_URL`, `METASO_TIMEOUT`
- `ZHIPU_API_KEY`, `ZHIPU_BASE_URL`, `ZHIPU_MODEL`, `ZHIPU_TIMEOUT`
- `ZHIHU_COOKIES`

`ZHIHU_COOKIES` 只能保存在本地环境，不能提交。

## 自学资料

常用配置：

- `STUDY_MATERIALS_PRESET`: `quick` / `standard` / `deep` / `research`
- `STUDY_MATERIALS_SUBAGENT_CONCURRENCY`
- `STUDY_MATERIALS_SEARCH_MODE`: `tavily` / `exa` / `deepresearch` / `metaso`
- `STUDY_MATERIALS_WEB_DECOMPOSE`
- `STUDY_MATERIALS_WEB_SUBQUERIES`
- `STUDY_MATERIALS_THINKING_MODEL`
- `STUDY_MATERIALS_WRITER_MODEL`
- `STUDY_MATERIALS_THINKING_EFFORT`
- `STUDY_MATERIALS_STEP_TIMEOUT_S`
- `STUDY_MATERIALS_LATEX_STEP_TIMEOUT_S`
- `STUDY_MATERIALS_SSE_HEARTBEAT_S`

任务池：

- `STUDY_MATERIALS_TASK_TTL_S`
- `STUDY_MATERIALS_MAX_TASKS`
- `STUDY_MATERIALS_TASK_MAX_EVENTS`

## 教案

- `LESSON_PLAN_PROVIDER`
- `LESSON_PLAN_MODEL`
- `LESSON_PLAN_TEMPERATURE`
- `LESSON_PLAN_MAX_TOKENS`
- `LESSON_PLAN_SUBAGENT_CONCURRENCY`
- `LESSON_PLAN_WRITER_MODEL`

未单独设置时，教案会回落到主模型配置。

## AI 出题与题库

- `QUESTION_LIBRARY_MAX_TASKS`
- `QUESTION_LIBRARY_TASK_TTL_S`
- `QUESTION_LIBRARY_TASK_MAX_EVENTS`
- `QUESTION_LIBRARY_REALIZE_MAX_TOKENS`
- `QUESTION_LIBRARY_JUDGE_MODEL`
- `QUESTION_LIBRARY_MCP_SEARCH_MODEL`
- `QUESTION_LIBRARY_AUTO_SCORE`
- `QUESTION_LIBRARY_SCORE_INTERVAL_S`
- `QUESTION_LIBRARY_SCORE_BATCH`
- `QUESTION_LIBRARY_HIDE_THRESHOLD`
- `QUESTION_LIBRARY_SCORE_MODEL`

题库生成的长任务应通过 `/api/tasks/question-library/*` 使用。

## DeepThink

- `DEEPTHINK_GENERATOR_MODEL`
- `DEEPTHINK_GENERATOR_TEMPERATURE`
- `DEEPTHINK_GENERATOR_MAX_TOKENS`
- `DEEPTHINK_EVALUATOR_MODEL`
- `DEEPTHINK_EVALUATOR_TEMPERATURE`
- `DEEPTHINK_EVALUATOR_MAX_TOKENS`
- `DEEPTHINK_REASONING_EFFORT`
- `TOT_BRANCH_FACTOR`
- `TOT_BEAM_WIDTH`
- `TOT_MAX_DEPTH`
- `TOT_PRUNE_THRESHOLD`
- `TOT_TIMEOUT`

## 试卷导出

- `PAPER_EXPORT_LATEX_ENGINE`
- `PAPER_EXPORT_LATEX_TIMEOUT_S`
- `AGENT_LATEX_COMPILE_TIMEOUT_S`
- `PAPER_EXPORT_DOCX_ENGINE`
- `PAPER_EXPORT_PANDOC_TIMEOUT_S`

PDF 需要本机可执行的 LaTeX 引擎，DOCX 推荐安装 Pandoc。

内容持久化：

- `PAPER_STORE_CONTENT=1`
- `PAPER_STORE_STEM=1`
- `PAPER_STORE_ANSWER=1`
- `PAPER_STORE_ANALYSIS=1`

默认不要开启不必要的题干、答案、解析持久化。

## 前端

- `VITE_API_BASE_URL`：默认 `/api`

同源部署保持默认值。前后端分开部署时设置为后端完整 API 地址并重新构建。

## 媒体、画布与可观测性

媒体代理：

- `MEDIA_PROXY_ALLOWED_DOMAINS`
- `MEDIA_PROXY_CACHE_TTL_SECONDS`
- `MEDIA_PROXY_CACHE_MAX_BYTES`
- `MEDIA_PROXY_CACHE_MAX_FILES`

画布历史：

- `CANVAS_VERSION_MAX_KEEP`

OpenTelemetry：

- `OTEL_ENABLE`
- `OTEL_SERVICE_NAME`
- `OTEL_EXPORTER_OTLP_ENDPOINT`

## 排查配置

启动后访问：

- `GET /api/config`
- `GET /api/health`
- `GET /api/health/ready`

配置摘要会脱敏，不会返回密钥明文。

## 变更规则

- 新增配置项时同步 `.env.example`。
- 后端读取配置优先集中到 `backend/core/settings.py`。
- 用户可见或部署相关配置同步更新本文。
- 密钥类型配置在日志和 `/api/config` 中必须脱敏。
- 配置项删除或语义变更必须检查测试、文档和前端设置页。
