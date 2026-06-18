# 对话工具扩展（Chat Tool Expansion） - 实施方案

**优先级**: P1, 增强/对话能力
**状态**: 已实现（2026-06-08）
**目标**: 把 `web_search` / `python_scientific_compute` / `plot_function` 接入对话工具集，并让对话气泡用 Markdown 渲染（显示图片/链接/公式），把对话从「找题机器人」升级为真正的解题助手。

## Context / 问题描述
对话仅挂 8 个题库/试卷工具（`backend/workspace/chat/tools_spec.py:5` 的 `TOOLS`）。MCP 侧（`backend/integrations/mcp/`）有 ~40 个工具，含联网搜索、Python 计算、画函数、TikZ、教纲对齐、整卷解答，**均未接入对话**。且对话气泡只渲染纯文本，图片/链接/公式无法显示。

## 关键扩展点（已核实，注册表范式）
- 工具规格：`tools_spec.py:5` `TOOLS`（OpenAI function-calling JSON schema）。
- 注册表：`tool_registry.py:28` `ChatToolRegistry`；`tools_mixin.py:20-39` 用 `handlers` dict（26-35 行）把名字→handler 绑定。
- 调度点：`tools_mixin.py:198` `execute_tool(...)` → `:212` `await tool.handler(arguments, sub_model=..., user_id=...)`。
- 可见性门控：`tools_mixin.py:44-48` `_determine_tools_for_request`（计划确认前只放出 search/filters）；并发互斥 `service.py:12` `MUTUALLY_EXCLUSIVE_CHAT_TOOLS`。
- 结果回流：`service.py:101` 执行 → `:268` 以 `tool_result` SSE 推前端 → `:276-292` 作为 `{role:tool}` 进下一轮。
- MCP 实现可复用度：
  - `python_scientific_compute`（`.../python_scientific_compute.py:345`）：**独立可复用**，子进程沙箱、无网络；`:58` 已提供 `openai_tool_spec()`。
  - `plot_function`：经 `render_matplotlib_2d_to_url`（`generation/question_library/diagram_utils.py:167`）**可复用**，但硬编码 `user_id="1"`，需传真实 user_id。
  - `web_search`（`stdio_handlers.py:816`）：provider 自动选择 ~150 行**内联在 handler**，但 `integrations/mcp/search/*` 的 provider 函数可复用 → **抽出共享 `run_web_search` 服务**给 MCP handler 与对话共用。需 `TAVILY_API_KEY`/`EXA_API_KEY`/`ZHIPU_API_KEY`，有网络出口。
  - 后续（不在 v1）：`render_tikz`（需 xelatex/dvisvgm）、`align_to_curriculum`（内联判定）、`solve_paper`（~95 行编排待抽取）。
- 规格格式：MCP `inputSchema` 与对话 `parameters` 同为 JSON Schema，转换 trivial。
- 前端渲染：`features/chat/components/MessageBubble.tsx:49,92` 助手消息为纯 `whitespace-pre-wrap`；已存在 `components/shared/Markdown`（react-markdown + KaTeX + `AuthImage` 解析 `/api/media/generated/...`），lessonPlans/studyMaterials 已用。换上即可显示工具产出的图片/链接/公式。

## 设计决策
- v1 子集 = python 计算 + 作图 + 联网搜索（性价比最高、复用最干净）；TikZ/教纲对齐/整卷解答留作 phase 2。
- handler 一律传真实 `user_id` 与 `self.current_subject` / `self._get_crawler()`，**不沿用硬编码 `"1"`**。
- 工具产出统一返回带 Markdown（图片用 `![](/api/media/generated/...)`、搜索结果用链接列表），前端 `<Markdown>` 直接渲染。

## 实施清单
- [x] 后端：抽出共享 `run_web_search(query, ...)` 服务（`integrations/mcp/search/` 下），并改 MCP handler 调用它（去重 150 行）
- [x] 后端：新建 `backend/workspace/chat/extra_tools.py` —— 3 个 async handler 包装：`python_scientific_compute`（直接 import）、`plot_function`（调 `render_matplotlib_2d_to_url`，传真实 `user_id`）、`web_search`（调 `run_web_search`）
- [x] 后端：`tools_spec.py` 追加 3 个规格（python 用 `openai_tool_spec()`；plot/web_search 由 MCP `inputSchema` 翻译）
- [x] 后端：`tools_mixin.py` `handlers` dict 注册 3 个 handler；`_determine_tools_for_request` 把新工具加入可见集；按需更新 `MUTUALLY_EXCLUSIVE_CHAT_TOOLS`
- [x] 前端：`MessageBubble.tsx` 把 49、92 行助手内容从纯文本 `<div>` 换成 `<Markdown>`
- [x] 前端（可选增强）：把 `tool_result` SSE 渲染成小卡（「联网搜索 / 计算 / 作图」）
- [x] 测试：后端 3 个 handler（mock LLM/网络/子进程）；前端 Vitest 验证 Markdown 渲染图片/链接

## 验证
1. 对话「用 Python 求 ∫…」→ 触发 `python_scientific_compute`，结果回显。
2. 「画出 y=x²-2x」→ `plot_function` 返回图片 → 气泡内显示 SVG/PNG。
3. 「联网搜一下…」→ `web_search` 返回链接列表 → 可点击。
4. 计划确认前后工具可见性符合 `_determine_tools_for_request` 门控；无网络/无 key 时优雅报错。

## 风险
- 联网/计算成本与安全：python 已沙箱；web_search 有网络出口与 key 依赖，缺 key 时降级报错。
- `<Markdown>` 渲染范围：仅助手消息；图片经 `AuthImage`/media 代理，避免外链问题。
