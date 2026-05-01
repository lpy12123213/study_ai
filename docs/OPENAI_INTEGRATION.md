# OpenAI-compatible 集成说明

Study AI 通过 OpenAI-compatible Chat Completions 风格调用模型供应商。本文说明如何配置兼容供应商，以及哪些能力会使用这些模型。

当前主路径是在后端配置 provider、base URL、API key 和模型名；不是单独启动额外适配器服务。

## 支持口径

当前配置支持：

- OpenRouter
- Fireworks
- Moonshot
- 其他兼容 OpenAI API 形态的供应商，可通过 `config/model.json` 指定 base URL 和模型名

核心配置位于：

- `.env`
- `config/model.json`
- `backend/core/settings.py`
- `backend/llm/`

## 使用 OpenAI 或兼容供应商

如果供应商提供 OpenAI-compatible endpoint，可在 `config/model.json` 中配置：

```json
{
  "active_provider": "openai-compatible",
  "pinned": true,
  "providers": {
    "openai-compatible": {
      "base_url": "https://api.example.com/v1",
      "api_key": "sk-..."
    }
  },
  "models": {
    "main": "gpt-5-mini",
    "sub": "gpt-5-mini",
    "lesson_plan": "gpt-5-mini"
  }
}
```

如果只使用 `.env`，则选择内置 provider：

```bash
CHAT_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
MAIN_MODEL=openai/gpt-5-mini
SUB_MODEL=openai/gpt-5-mini
```

## 模型使用场景

- `MAIN_MODEL`：对话主模型、复杂生成、工具编排。
- `SUB_MODEL`：较轻的选择、提取、判断、拆分任务。
- `LESSON_PLAN_MODEL`：教案和自学资料相关生成，可不设置，默认回落到主模型。
- `STUDY_MATERIALS_THINKING_MODEL`：自学资料检索/拆分/规划。
- `STUDY_MATERIALS_WRITER_MODEL`：自学资料正文写作。
- `QUESTION_LIBRARY_JUDGE_MODEL`：AI 出题后的审题模型。

## 工具调用

Study AI 内部已经把工具调用封装在后端和 MCP 中。外部系统有两种推荐接入方式：

1. HTTP API：调用 `/api/tasks/*`、`/api/chat`、`/api/question-library/*` 等接口。
2. MCP：通过 `python -m backend.mcp.stdio_server` 暴露工具给支持 MCP 的客户端。

不建议复制历史资料中的独立适配器服务方式；当前仓库没有把它作为维护入口。

## 调试

检查运行时配置：

```http
GET /api/config
```

开启控制台 LLM 日志：

```bash
LLM_CONSOLE_LOG=1
LLM_CONSOLE_STREAM=1
```

如果模型调用失败，优先检查：

- provider 是否被 `LLM_PROVIDER_PINNED=1` 或 `config/model.json` 锁定。
- 模型名是否带了供应商要求的前缀。
- base URL 是否以 `/v1` 结尾，具体取决于供应商。
- API key 是否配置到实际运行进程可见的环境中。

## 安全

- 不要把 API key 写入文档、截图或 Git。
- Web UI 的请求级 API key override 默认应保持关闭；共享部署尤其不要随意开启。
- 如果开放公网访问，务必修改 `JWT_SECRET` 和管理员密码。

## 相关文档

- `CONFIGURATION.md`：完整环境变量说明。
- `DEVELOPMENT.md`：新增模型相关代码的维护规则。
- `TROUBLESHOOTING.md`：模型调用失败排查。
