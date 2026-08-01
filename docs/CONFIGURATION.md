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

## 配置校验

本地可以用只读脚本检查高影响配置是否缺失：

```bash
python scripts/check_config.py
```

机器可读输出：

```bash
python scripts/check_config.py --json
```

严格模式会在必填关系缺失时返回非 0，用于发布前检查：

```bash
python scripts/check_config.py --strict
```

当前校验覆盖：

| 场景 | 必填或建议项 | 级别 |
| --- | --- | --- |
| `CHAT_PROVIDER=openrouter` | `OPENROUTER_API_KEY` | missing |
| `CHAT_PROVIDER=fireworks` | `FIREWORKS_API_KEY` | missing |
| `CHAT_PROVIDER=moonshot` | `MOONSHOT_API_KEY` | missing |
| `LESSON_PLAN_PROVIDER=<provider>` | 对应 provider API Key | missing |
| 共享或公网部署 | 非占位 `JWT_SECRET`、`ADMIN_PASSWORD` | recommended |
| `STUDY_MATERIALS_SEARCH_MODE=tavily/metaso/exa` | 对应搜索 API Key | recommended |
| `WEB_CONCURRENCY` / `UVICORN_WORKERS` / `WORKERS` > 1 | 单进程内存限速不再是全局窗口 | optional |

后端启动时也会执行同一套检查：`missing` 记录为 warning，`recommended` 记录为 info；不会在本地开发环境中阻断启动。

## 限速与 Worker

`backend/app.py` 内置的 API 与登录失败限速器是单进程内存窗口。使用单个后端 worker 时行为明确；如果通过
`WEB_CONCURRENCY`、`UVICORN_WORKERS` 或 `WORKERS` 启动多个 worker，每个进程都会维护独立窗口，实际全局限速会变宽。

共享或公网部署建议保持单 worker，或把限速下沉到 Redis、Nginx、Traefik 等共享/边缘层。配置检查会在发现多 worker
环境变量时输出 `optional` 提示，但不会阻断启动。

## SQLite 并发

默认数据库是 SQLite。`DB_POOL_SIZE` 和 `DB_MAX_OVERFLOW` 只控制异步连接等待 SQLite 锁的方式，不会提升写吞吐；
高频写入应通过批量刷写和单事务提交减少锁占用。详细策略见 `docs/DB_CONCURRENCY.md`。

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
- 也可在 Web 设置页的“API 配置”中维护供应商、Base URL、API Key 和默认模型。
- 通过 Web 设置页保存的 API Key 会写成 `enc:v1:` 加密值；本机解密密钥默认存放在 `.local/secrets/model_config.key`，可用 `LOCAL_ENCRYPTION_KEY_PATH` 指向其他位置。

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
- `pinned=false` 时允许运行时按模型名前缀做已有的 provider 推断。
- 模型名必须符合所选 provider 的格式。
- `main` 用于复杂推理和编排，`sub` 用于轻量提取、选择和判断。
- lesson plan、study materials 和 question library 可按需设置独立模型。
- 设置页“抓取模型”会调用供应商的 OpenAI-compatible `GET /models` 接口；如果输入框未填写新 Key，则会使用已保存的加密 Key。

## Agent Runtime

中/重型 agent 任务默认使用本机 Codex runtime，而不是把 agent 简单切到某个模型字符串。覆盖范围包括 DeepThink、教案、组卷/一键出卷、知识视频、AI 出题、题库评分和好题鉴别；普通导出、作文批改等非 agent 流程不受影响。

- `AGENT_RUNTIME`: 默认 `codex_runtime`。设为 `legacy` 时才允许走旧 agent/service 分支。
- `STUDY_MATERIALS_AGENT_RUNTIME`: 自学资料生成的专用开关。默认（留空）走不依赖 Codex CLI 的 legacy AgentCore 路径；显式设为 `codex_runtime` 时才启用 Codex 分阶段工作流（规划/起草/修订由 Codex CLI 执行，检索/审查仍由后端工具执行）。
- `CODEX_RUNTIME_COMMAND`: 默认 `codex`，可指向本机 Codex CLI。
- `CODEX_RUNTIME_MODEL`: 默认空，表示沿用本机 Codex 配置；需要固定模型时填写。
- `CODEX_RUNTIME_EFFORT`: 默认 `high`，保留给运行时策略与 metadata。
- `CODEX_RUNTIME_APPROVAL_POLICY`: 默认 `never`，对应 `codex --ask-for-approval never exec`。
- `CODEX_RUNTIME_SANDBOX`: 默认 `workspace-write`，对应 `codex exec --sandbox workspace-write`。
- `CODEX_RUNTIME_PROXY`: 可选的 HTTP 代理地址；现有 `HTTP_PROXY`/`HTTPS_PROXY` 优先。未显式配置时，Windows 会读取当前用户的 Internet Settings 代理并只注入 Codex 子进程。
- `CODEX_RUNTIME_TIMEOUT_S`: 默认 `900`。
- `CODEX_RUNTIME_FALLBACK_LEGACY`: 默认 `0`，不静默回退旧 agent。

每个任务会在 `.local/codex-runtime-agent/<task_id>` 建立隔离工作目录，并通过 `--add-dir` 只暴露该目录和请求中存在的必要输入文件目录。默认命令形态为 `codex --ask-for-approval never --disable plugins --disable memories exec --json --ephemeral --skip-git-repo-check --cd <task_dir> --sandbox workspace-write --output-last-message <task_dir>/agent-output.json -`：`-` 表示从标准输入读取精简任务指令，并关闭 CLI 的 plugins/memories feature。自学资料的初次生成会额外关闭 `shell_tool`、以内联输入直接生成 Markdown；LaTeX/PDF 留给后续独立导出，避免 Codex 把业务规格误解成环境探测和本地文件制作。应用会在启动前清理同名旧输出，并在进程成功退出后校验本次 `--output-last-message` JSON。任务启动 metadata 会包含 `runtime=codex_runtime`、`codex_runtime_version`、`approval_policy` 和 `sandbox_mode`。

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
- `STUDY_MATERIALS_STAGE_PROMPT_MAX_CHARS`: 默认 `30000`。单阶段 Codex worker 提示词载荷上限（字符）；超出时先按知识点裁剪研究证据、再按剩余预算截断正文。

任务池：

- `STUDY_MATERIALS_TASK_TTL_S`
- `STUDY_MATERIALS_MAX_TASKS`
- `STUDY_MATERIALS_TASK_MAX_EVENTS`

归档复用：

- `STUDY_MATERIALS_ARCHIVE_MAX_AGE_S`: 默认 `1209600`（14 天）。本地归档自动复用的新鲜度上限，超过该年龄的归档不再直接复用；`0` 表示不做时间过期。

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

## AI 组卷

- `PAPER_COMPOSE_AGENTIC_BLUEPRINT`: 仅在 `AGENT_RUNTIME=legacy` 时作为旧蓝图 Agentic 编排开关；默认 `AGENT_RUNTIME=codex_runtime` 会直接走 Codex runtime。
- `COMPOSE_SANDBOX_DOCKER_IMAGE`: 默认 `study-ai/compose-sandbox:latest`。组卷工作台 Docker 会话镜像。
- `COMPOSE_SANDBOX_ROOT`: 默认 `.local/compose-sandbox`。每个会话的宿主机工作区根目录。
- `COMPOSE_SANDBOX_TIMEOUT_S`: 默认 `60`。单次白名单命令超时时间。
- `COMPOSE_SANDBOX_TTL_S`: 默认 `900`。会话最长存活时间。
- `COMPOSE_SANDBOX_MAX_WORKSPACE_BYTES`: 默认 `52428800`。单会话工作区大小上限。
- `COMPOSE_SANDBOX_MEMORY` / `COMPOSE_SANDBOX_CPUS` / `COMPOSE_SANDBOX_PIDS_LIMIT` / `COMPOSE_SANDBOX_USER`: Docker 资源和运行用户限制。

Compose sandbox 只暴露 `xelatex`、`python3`、`ls`、`cat` 白名单命令；容器使用 `--network none`，
工作区路径限制在 `/workspace` 挂载内。Docker 或镜像不可用时，后端会返回 sandbox unavailable 错误，
不会开放宿主任意 shell。

构建默认组卷工作台镜像：

```bash
docker build -t study-ai/compose-sandbox:latest docker/compose-sandbox
```

## 试卷导出

- `PAPER_EXPORT_LATEX_BACKEND`: `auto` / `docker` / `host`
- `PAPER_EXPORT_LATEX_ENGINE`
- `PAPER_EXPORT_LATEX_TIMEOUT_S`
- `AGENT_LATEX_COMPILE_TIMEOUT_S`
- `LATEX_SANDBOX_DOCKER_IMAGE`
- `LATEX_SANDBOX_TIMEOUT_S`
- `LATEX_SANDBOX_MEMORY`
- `LATEX_SANDBOX_CPUS`
- `LATEX_SANDBOX_PIDS_LIMIT`
- `LATEX_SANDBOX_USER`
- `PAPER_EXPORT_DOCX_ENGINE`
- `PAPER_EXPORT_PANDOC_TIMEOUT_S`

PDF 编译默认 `PAPER_EXPORT_LATEX_BACKEND=auto`：如果 Docker 和 `LATEX_SANDBOX_DOCKER_IMAGE`
镜像可用，会在 `--network none`、只读根文件系统、drop capabilities 的容器内运行 `xelatex`；否则回退到本机
LaTeX 引擎。生产或公网环境建议构建并启用 Docker 沙盒，避免让模型生成的 LaTeX 直接在宿主机编译。

构建默认沙盒镜像：

```bash
docker build -t study-ai/latex-sandbox:latest docker/latex-sandbox
```

DOCX 推荐安装 Pandoc。

内容持久化：

- `PAPER_STORE_CONTENT=1`
- `PAPER_STORE_STEM=1`
- `PAPER_STORE_ANSWER=1`
- `PAPER_STORE_ANALYSIS=1`

默认不要开启不必要的题干、答案、解析持久化。

## 前端与部署

前端与后端之间有两种受支持的模式：

- 同源反向代理（默认）：浏览器使用相对 `/api`，无需设置 `VITE_API_BASE_URL`，认证 Cookie 为 `SameSite=Lax`。
- 跨站部署：前端构建时把 `VITE_API_BASE_URL` 设为后端 origin；后端用 `CORS_ORIGINS` 白名单允许前端 origin，并设置 `AUTH_COOKIE_SAMESITE=none`（隐含 `Secure`，要求 HTTPS）。前端跨站请求需携带凭证（`credentials: include`、EventSource `withCredentials`）；`CORS_ORIGINS=*` 与携带凭证的请求不能同时使用。

- `VITE_API_BASE_URL`（前端构建时）：后端 origin；默认留空表示同源相对 `/api`。
- `VITE_DEV_PROXY_TARGET`（前端开发）：Vite dev server 的 `/api` 代理目标，默认 `http://localhost:8000`。
- `AUTH_COOKIE_SAMESITE`：`lax`（默认）或 `none`；`none` 隐含 `Secure`，跨站部署需要 HTTPS。
- `CORS_ORIGINS`：允许跨站访问的 origin allowlist，逗号分隔。
- `TRUST_PROXY_HEADERS`：`1` 表示信任代理传入的客户端 IP 头（`X-Forwarded-For` / `Forwarded` 等）。
- `TRUSTED_PROXIES`：受信任的直接上游代理 IP/CIDR 列表，逗号分隔；只在 `TRUST_PROXY_HEADERS=1` 时生效，不要在未知代理后使用 `*`。

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
