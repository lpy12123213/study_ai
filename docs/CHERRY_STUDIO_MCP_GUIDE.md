# Cherry Studio MCP 配置指南

Study AI 提供 MCP stdio server。配置后，Cherry Studio 可以调用 Study AI 的题目搜索、蓝图组卷、创建试卷、审卷、内容检索和联网搜索工具。

其他 MCP 客户端可采用同一配置模型：命令运行 `python -m backend.mcp.stdio_server`，工作目录指向仓库根目录。

## 前置准备

在仓库根目录完成依赖安装：

```bat
start.bat setup
```

或手动安装：

```bash
python -m venv venv
python -m pip install -r requirements.txt
python -m playwright install chromium
```

如果需要 LLM 审卷、智能选题或联网搜索，请配置 `.env`：

- `CHAT_PROVIDER`
- `OPENROUTER_API_KEY` / `FIREWORKS_API_KEY` / `MOONSHOT_API_KEY`
- `MAIN_MODEL`
- `SUB_MODEL`
- `TAVILY_API_KEY` / `EXA_API_KEY` / `ZHIPU_API_KEY`

## 推荐启动命令

优先使用模块入口：

```bash
python -m backend.mcp.stdio_server
```

Windows 也可以通过启动器：

```bat
start.bat mcp
```

## Cherry Studio 配置

在 Cherry Studio 的 MCP 服务器设置中添加：

- 名称：`exam-paper-assistant`
- 命令：虚拟环境 Python 的绝对路径，或 `cmd`
- 参数：见下面示例
- 工作目录：仓库根目录 `study_ai`

Windows 示例，推荐使用虚拟环境 Python：

```json
{
  "mcpServers": {
    "exam-paper-assistant": {
      "command": "C:/path/to/study_ai/venv/Scripts/python.exe",
      "args": ["-m", "backend.mcp.stdio_server"],
      "cwd": "C:/path/to/study_ai"
    }
  }
}
```

使用启动器：

```json
{
  "mcpServers": {
    "exam-paper-assistant": {
      "command": "cmd",
      "args": ["/c", "C:/path/to/study_ai/start.bat", "mcp"],
      "cwd": "C:/path/to/study_ai"
    }
  }
}
```

路径里包含中文时，确认 Cherry Studio 配置文件使用 UTF-8 保存。Windows 路径可以使用 `/`，也可以把反斜杠写成 `\\`。

## 常用工具

题目与组卷：

- `search_questions_by_keyword`
- `search_questions_by_knowledge`
- `filter_questions`
- `get_question_info`
- `get_question_details`
- `select_best_question`
- `compose_paper_blueprint`
- `create_paper`
- `review_paper`

学习资料与检索：

- `search_examples`
- `search_exercises`
- `review_content`
- `web_search`
- `fetch_zhihu`

诊断：

- `diagnose_export`

工具列表以 `backend/integrations/mcp/tools/stdio_tools.py` 为准。

## 使用示例

搜索题目：

```text
帮我找 10 道高中数学“导数与单调性”的中等难度题，并给出题目 ID。
```

蓝图组卷：

```text
帮我按下面结构组一份高一数学小测：
1. 函数性质选择题 6 道，中等难度
2. 指数函数填空题 4 道，简单到中等
3. 综合解答题 2 道，中等偏难
最后创建试卷，名称为“函数单元小测”。
```

审卷：

```text
请审查 paper_id=3 的试卷，重点看题型分布、重复题和难度梯度。
```

## 排查

MCP 无法连接时：

1. 在仓库根目录手动运行 `python -m backend.mcp.stdio_server`。
2. 确认 Cherry Studio 的 `cwd` 是仓库根目录。
3. 确认虚拟环境依赖安装完成。
4. 如果工具调用 crawler 失败，先运行 `python -m playwright install chromium`。
5. 如果 LLM 工具失败，检查 `.env` 中 provider、API key 和模型名。

更多排查见 `TROUBLESHOOTING.md`。

## 维护口径

- MCP 工具清单以 `backend/integrations/mcp/tools/stdio_tools.py` 为准。
- 工具实现以 `backend/integrations/mcp/tools/stdio_handlers.py` 为准。
- 新 MCP 工具需要补充说明、输入 schema 和失败返回。
- 不要在 MCP 文档中承诺 HTTP API 尚未支持的 provider 切换能力。
