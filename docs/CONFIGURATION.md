# 配置说明

Study AI 将配置分成两类：模型配置只存放在本地 `config/model.json`；非模型的运行、认证、搜索服务和部署配置存放在系统环境变量或 `.env`。

不要提交真实密钥、Cookie、本地数据库或抓取内容。

## 配置加载

后端会从仓库根目录加载 `.env`，并保留系统环境变量的优先级；模型配置则独立加载 `config/model.json`。核心代码在 `backend/core/settings.py`。

非模型配置加载顺序：

1. 系统环境变量。
2. 仓库根目录 `.env`，不覆盖已存在的系统环境变量。
3. 代码默认值。

模型供应商、API Key、Base URL、路由、模型 ID、temperature、max_tokens、reasoning effort 和上下文限制不再读取 `.env`。它们只读取 `config/model.json`，文件位置可由 `MODEL_CONFIG_PATH` 指定。

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
| `routes.chat` | 对应 `providers.<name>.api_key` | missing |
| `routes.lesson_plan` | 对应 `providers.<name>.api_key` | missing |
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

## 模型配置

- 默认路径：`config/model.json`
- 可用 `MODEL_CONFIG_PATH` 指向其他路径
- 复制 `config/model.example.json` 可得到完整字段模板
- Web 设置页的“模型设置”可以切换供应商；保存目标也是该 JSON 文件
- 通过 Web 设置页保存的 API Key 会写成 `enc:v2:` 加密值；本机解密密钥默认存放在 `.local/secrets/model_config.key`，可用 `LOCAL_ENCRYPTION_KEY_PATH` 指向其他位置。

示例结构：

```json
{
  "active_provider": "openrouter",
  "pinned": true,
  "providers": {
    "openrouter": {
      "base_url": "https://openrouter.ai/api/v1",
      "api_key": "sk-or-..."
    }
  },
  "routes": {
    "chat": "openrouter",
    "lesson_plan": "openrouter",
    "review": "openrouter",
    "image": "ark"
  },
  "models": {
    "main": "openai/gpt-5-mini",
    "sub": "openai/gpt-4o-mini",
    "lesson_plan": "openai/gpt-5-mini",
    "study_materials_writer": "openai/gpt-5-mini"
  },
  "params": {
    "main_temperature": 0.7,
    "main_max_tokens": 2000,
    "study_materials_thinking_effort": "xhigh"
  },
  "context": {
    "input_multiplier": 1.15,
    "reserve_ratio": 0.015,
    "openrouter_fetch_limits": true
  }
}
```

模型配置规则：

- `active_provider` 是未指定路由时的默认供应商；`routes` 可分别指定 chat、lesson_plan、review 和 image。
- `pinned=true` 时不按模型名前缀自动切换供应商；`pinned=false` 仅保留已有的兼容推断行为。
- 模型名必须符合所选 provider 的格式。
- `models` 保存所有模型角色。完整角色清单以 `config/model.example.json` 为准，支持字符串或按 provider 分组的映射。
- `params` 保存 temperature、max_tokens、reasoning effort、模型 tier 和图像生成参数。
- `context` 保存模型上下文长度、输入倍率、预留 token、聊天 token 预算和 OpenRouter 模型限制拉取参数。
- 设置页“抓取模型”会调用供应商的 OpenAI-compatible `GET /models` 接口；如果输入框未填写新 Key，则会使用已保存的加密 Key。
- `.env` 中旧的 `*_MODEL`、`*_PROVIDER`、模型 temperature/max_tokens、LLM provider API Key/Base URL 不再生效。

## Agent Runtime

中/重型 agent 任务默认使用本机 Codex runtime，而不是把 agent 简单切到某个模型字符串。覆盖范围包括 DeepThink、教案、组卷/一键出卷、知识视频、AI 出题、题库评分和好题鉴别；普通导出、作文批改等非 agent 流程不受影响。

- `AGENT_RUNTIME`: 默认 `codex_runtime`。设为 `legacy` 时才允许走旧 agent/service 分支。
- `STUDY_MATERIALS_AGENT_RUNTIME`: 自学资料生成的专用开关。默认（留空）走 author 作者流水线（research→blueprint→backbone→fill→assemble→audit→accept，见 `backend/generation/study_materials/author/`）；显式设为 `legacy` 回退不依赖 Codex CLI 的 legacy AgentCore 路径，设为 `codex_runtime` 时启用 Codex 分阶段工作流（规划/起草/修订由 Codex CLI 执行，检索/审查仍由后端工具执行）。2026-08 之前默认是 legacy。
- `CODEX_RUNTIME_COMMAND`: 默认 `codex`，可指向本机 Codex CLI。
- `models.codex_runtime`（`config/model.json`）：默认空，表示沿用本机 Codex 配置。
- `params.codex_runtime_effort`（`config/model.json`）：默认 `high`，用于 Codex runtime 推理强度与 metadata。
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

- `.env`: `TAVILY_API_KEY`, `TAVILY_BASE_URL`, `TAVILY_TIMEOUT`
- `.env`: `EXA_API_KEY`, `EXA_BASE_URL`
- `.env`: `METASO_API_KEY`, `METASO_BASE_URL`, `METASO_TIMEOUT`
- `config/model.json`: `providers.zhipu` 与 `models.zhipu_search`；`.env` 仅保留 `ZHIPU_TIMEOUT`
- `config/model.json`: 可选 `models.metaso_ask`；Metaso 搜索服务密钥仍属于 `.env` 中的集成配置
- `ZHIHU_COOKIES`

`ZHIHU_COOKIES` 只能保存在本地环境，不能提交。

## 自学资料

运行时（2026-08 起）：

- `STUDY_MATERIALS_AGENT_RUNTIME`: 默认 `author`（留空即走 author 作者流水线）。显式回退值：`legacy`（旧 AgentCore 路径）、`codex_runtime`（Codex 分阶段工作流）。
- `STUDY_MATERIALS_TRACE_TTL_S`: 默认 `0`（不清理）。author runtime trace 事件骨架的保留时长（秒）；目前只留开关，清理器未实现。
- `STUDY_MATERIALS_WEB_DECOMPOSE`: 默认 `0`（此前默认 `1`）。检索默认不再为每个知识点调 LLM 拆子问题；显式设为 `1` 恢复拆分，或在工具入参里逐次传 `decompose`。

常用配置：

- `STUDY_MATERIALS_PRESET`: `quick` / `standard` / `deep` / `research`
- `STUDY_MATERIALS_SUBAGENT_CONCURRENCY`
- `STUDY_MATERIALS_SEARCH_MODE`: `tavily` / `exa` / `deepresearch` / `metaso`
- `STUDY_MATERIALS_WEB_SUBQUERIES`
- `config/model.json`: `models.study_materials_thinking`、`models.study_materials_writer` 及其他阶段模型
- `config/model.json`: `params.study_materials_thinking_effort`、LaTeX token 上限与 reasoning 开关
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

- `config/model.json`: `routes.lesson_plan`
- `config/model.json`: `models.lesson_plan`、`lesson_plan_writer`、`lesson_plan_split`、`lesson_plan_research`、`lesson_plan_kp_review`、`lesson_plan_latex`、`lesson_plan_latex_refine`
- `config/model.json`: `params.lesson_plan_temperature`、`lesson_plan_max_tokens`、`lesson_plan_infinite_max_tokens`
- `.env`: `LESSON_PLAN_SUBAGENT_CONCURRENCY` 以及重试、超时等运行参数

未配置专项模型时，教案会回落到 `models.lesson_plan`、`models.sub` 或 `models.main`。

## AI 出题与题库

- `QUESTION_LIBRARY_MAX_TASKS`
- `QUESTION_LIBRARY_TASK_TTL_S`
- `QUESTION_LIBRARY_TASK_MAX_EVENTS`
- `config/model.json`: `params.question_library_realize_max_tokens`
- `config/model.json`: `models.question_library_judge`、`question_library_mcp_search`、`question_library_score`
- `QUESTION_LIBRARY_AUTO_SCORE`
- `QUESTION_LIBRARY_SCORE_INTERVAL_S`
- `QUESTION_LIBRARY_SCORE_BATCH`
- `QUESTION_LIBRARY_HIDE_THRESHOLD`

题库生成的长任务应通过 `/api/tasks/question-library/*` 使用。

## DeepThink

- `config/model.json`: `models.deepthink_generator`、`models.deepthink_evaluator`
- `config/model.json`: 对应的 temperature、max_tokens 和 `params.deepthink_reasoning_effort`
- `.env`: `TOT_BRANCH_FACTOR`
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

- 新增模型配置时同步 `config/model.example.json`；新增非模型环境变量时同步 `.env.example`。
- 后端读取配置优先集中到 `backend/core/settings.py`。
- 用户可见或部署相关配置同步更新本文。
- 密钥类型配置在日志和 `/api/config` 中必须脱敏。
- 配置项删除或语义变更必须检查测试、文档和前端设置页。
