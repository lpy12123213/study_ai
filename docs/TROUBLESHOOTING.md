# 常见问题排查

本文按现象组织排查路径。遇到问题时先运行一次本地检查：

```bash
start.bat doctor
```

Linux / macOS：

```bash
./start.sh doctor
```

## 后端无法启动

检查关键 import 和依赖：

```bash
python -m pip check
python -c "import backend.app, backend.mcp.stdio_server"
```

常见处理：

- 重新运行 `start.bat setup` 或 `./start.sh setup`。
- 确认正在使用仓库内 `venv`。
- 确认 `.env` 没有把 provider、base URL 或模型名写错。
- 如果 optional 的 ChromaDB 依赖安装失败，可先跳过 `requirements-semantic-memory.txt`。

## 前端无法启动

```bash
cd frontend
npm install
npm run lint
npm run build
```

Vite 默认端口通常是 `5173`。如果端口被占用，Vite 会提示新端口；也可手动指定：

```bash
npm run dev -- --port 5174
```

## 登录失败

检查 `.env`：

- `JWT_SECRET`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `JWT_EXPIRE_HOURS`

修改后重启后端。浏览器端如果仍使用旧 token，退出登录或清理本地存储后再试。

## LLM 调用失败

检查：

- `CHAT_PROVIDER` 是否为 `openrouter`、`fireworks` 或 `moonshot`。
- 对应的 API key 和 base URL 是否存在。
- `MAIN_MODEL`、`SUB_MODEL` 是否是该 provider 可识别的模型名。
- 如果使用 `config/model.json`，确认 `active_provider`、`pinned` 和模型映射一致。

后端配置摘要：

```http
GET /api/config
```

该接口会脱敏，不会显示密钥明文。

## 自学资料或长任务刷新后没有续上

优先使用任务中心接口：

- `GET /api/tasks/{task_id}`
- `GET /api/tasks/{task_id}/stream?after_seq=<last_seq>`

检查：

- 任务是否已过 TTL。
- 后端是否重启过，数据库中是否有事件。
- 客户端是否保存并传入了最后处理的 `seq`。
- SSE 是否被反向代理缓冲。

## SSE 看起来卡住

长工具调用期间应该有 `ping` 心跳。若没有：

- 检查代理是否缓冲 `text/event-stream`。
- 检查 `STUDY_MATERIALS_SSE_HEARTBEAT_S` 或相关 heartbeat 配置。
- 看后端日志是否有长时间阻塞或外部 provider 超时。

## Playwright 或题源抓取失败

安装 Chromium：

```bash
python -m playwright install chromium
```

排查方向：

- 当前机器是否能访问目标题源。
- 是否触发目标站点反爬或登录要求。
- crawler 代码路径是否是 `backend/integrations/crawler/`，不要使用旧路径。
- 短时间内不要高并发重复抓取。

## 筛选项或知识树加载慢

首次加载可能初始化 crawler 和缓存。可以检查：

- `/api/subjects/{subject_code}/filters`
- `/api/subjects/{subject_code}/knowledge-tree`
- 后端日志中的 crawler 初始化信息

重复请求仍然很慢时，重启后端并观察是否缓存失效或目标站点响应变慢。

## 导出 PDF 失败

常见原因：

- 没有安装 `xelatex` 或 `pdflatex`。
- `dvisvgm` 不在 `PATH`。
- LaTeX 首次运行需要安装缺失包。
- `PAPER_EXPORT_LATEX_TIMEOUT_S` 太短。

排查：

```bash
xelatex --version
dvisvgm --version
```

可先导出 LaTeX 或 Markdown，再手动编译。

## DOCX 导出失败

推荐安装 Pandoc，并确认：

```bash
pandoc --version
```

相关配置：

- `PAPER_EXPORT_DOCX_ENGINE`
- `PAPER_EXPORT_PANDOC_TIMEOUT_S`

## 媒体或图片无法显示

媒体代理会拒绝：

- 非白名单域名。
- 非图片 content type。
- 远程 SVG。
- 过大的文件。

检查：

- `MEDIA_PROXY_ALLOWED_DOMAINS`
- `MEDIA_PROXY_CACHE_MAX_BYTES`
- `MEDIA_PROXY_CACHE_MAX_FILES`
- `/api/media/generated/{filename}` 是否能直接访问。

## MCP 客户端连接失败

推荐入口：

```bash
python -m backend.mcp.stdio_server
```

如果客户端要求命令和参数，优先使用虚拟环境 Python 的绝对路径：

```json
{
  "command": "C:/path/to/study_ai/venv/Scripts/python.exe",
  "args": ["-m", "backend.mcp.stdio_server"]
}
```

确认客户端工作目录为仓库根目录，或在命令里使用启动器 `start.bat mcp`。

## Ruff 或测试失败

`doctor` 只对维护路径运行 Ruff。如果 Ruff 或测试失败：

- 优先修复报告中的文件。
- 不要用删除测试或跳过检查来掩盖问题。
- 文档-only 修改通常不需要完整业务测试，但仍可运行 `git diff --check` 检查格式。

## 仍无法定位

收集以下信息后再继续排查：

- 操作系统和启动命令。
- 后端日志中的第一个错误。
- 浏览器控制台错误。
- `/api/health` 和 `/api/config` 的脱敏结果。
- 任务 ID 和最后一个 `seq`，如果问题发生在长任务中。
