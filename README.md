# Study AI

Study AI 是一个本地优先的学习与出题工作台。它将 AI 对话、资料生成、教案生成、深度解题、题库管理、蓝图组卷、试卷导出、知识视频和 MCP 工具服务整合为一套可本地运行的应用。

项目状态：主动开发中。文档以当前仓库代码为准，面向本地开发、内网部署和受控环境使用。

| 属性 | 说明 |
| --- | --- |
| 应用类型 | 本地优先的学习与出题工作台 |
| 后端入口 | `backend.app:app` |
| 前端入口 | `frontend/src/main.tsx` |
| 长任务入口 | `/api/tasks` |
| MCP 入口 | `python -m backend.mcp.stdio_server` |

技术栈：

- 后端：FastAPI、SQLAlchemy、SQLite、Playwright、MCP。
- 前端：Vite、React、TypeScript、React Router、Zustand、Vitest。
- 长任务：统一通过 `/api/tasks` 提交、追踪、回放和控制。

## 环境要求

必需：

- Python 3.10 或更高版本。
- Node.js LTS 与 npm。
- 可访问模型供应商和搜索供应商的网络环境，按功能需要配置。

按需：

- Playwright Chromium：题源抓取和部分浏览器自动化。
- LaTeX 工具链：PDF 导出。
- Pandoc：DOCX 导出。

## 快速启动

Windows：

```bat
start.bat setup
start.bat dev
```

Linux / macOS：

```bash
chmod +x start.sh
./start.sh setup
./start.sh dev
```

启动结果：

- 后端默认在 `http://localhost:8000`
- 前端地址由 Vite 输出，默认端口通常为 `5173`
- API 文档在 `http://localhost:8000/docs`

## 常用命令

```bash
start.bat backend     # 只启动后端，Linux/macOS 使用 ./start.sh backend
start.bat frontend    # 只启动前端
start.bat all         # 后端 + 前端 + MCP
start.bat mcp         # 只启动 MCP stdio server
start.bat doctor      # 运行本地健康检查
```

## 手动安装

```bash
python -m venv venv
```

激活虚拟环境：

- Windows: `venv\Scripts\activate`
- Linux / macOS: `source venv/bin/activate`

安装依赖：

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

可选：如果需要 ChromaDB 语义记忆，再安装：

```bash
python -m pip install -r requirements-semantic-memory.txt
```

未安装语义记忆依赖时，系统会回退到本地 JSONL 存储。

启动后端：

```bash
python -m uvicorn backend.app:app --reload --port 8000
```

启动前端：

```bash
cd frontend
npm install
npm run dev
```

启动 MCP：

```bash
python -m backend.mcp.stdio_server
```

## 应用能力

- 对话工作台：在对话中调用工具、检索题目、创建试卷。
- 自学资料：按主题拆解知识点，检索来源，生成可继续改进的资料。
- 教案生成：面向教学场景生成结构化教案并支持导出。
- DeepThink：面向复杂题目的多路径解题。
- 本地题库：抓取、筛选、收藏、隐藏、评分和批量维护题目。
- AI 出题：基于主题、参考资料和题型要求生成题目草稿，并经人工审核入库。
- 蓝图组卷：按题型、难度、知识点、年级、教材版本等约束组合题目。
- 试卷导出：导出 Markdown、LaTeX、PDF、DOCX。
- 知识视频：生成 Manim 风格的知识讲解视频任务。
- MCP 服务：把题目搜索、组卷、审卷、联网检索等能力暴露给 MCP 客户端。

### 知识视频沙盒

知识视频依赖 Docker 和本地 Manim 沙盒镜像。首次使用前运行：

```bash
docker build -t study-ai/manim-sandbox:latest docker/manim-sandbox
```

镜像名、渲染质量、超时和资源限制可通过 `.env` 中的 `KNOWLEDGE_VIDEO_*` 配置调整。

## 目录结构

```text
study_ai/
|-- backend/
|   |-- api/              # FastAPI 路由与 schema
|   |-- agent/            # 通用 agent 编排与工具
|   |-- chat/             # 对话链路
|   |-- core/             # 设置、日志、安全、媒体等基础能力
|   |-- crawler/          # 题源抓取适配
|   |-- database/         # SQLAlchemy schema、迁移、仓库层
|   |-- generation/       # agentic 生成与知识视频
|   |-- lesson_plan/      # 教案生成
|   |-- mcp/              # MCP stdio 工具服务
|   |-- paper_compose/    # 组卷与导出
|   |-- question_library/ # 本地题库、AI 出题、评分
|   |-- shared/           # 共享基础设施，包含 TaskRuntime
|   |-- tasks/            # 长任务提交与 runner
|   `-- app.py            # FastAPI 应用入口
|-- frontend/
|   `-- src/
|       |-- api/
|       |-- components/
|       |-- features/
|       |-- pages/
|       `-- router/
|-- docs/
|-- scripts/
|-- start.bat
|-- start.ps1
|-- start.sh
|-- requirements.txt
|-- requirements-dev.txt
`-- mcp_config.json
```

## 配置

复制 `.env.example` 到 `.env` 后填写需要的密钥：

```powershell
Copy-Item .env.example .env
```

常用配置：

- `CHAT_PROVIDER`: `openrouter` / `fireworks` / `moonshot`
- `OPENROUTER_API_KEY`, `FIREWORKS_API_KEY`, `MOONSHOT_API_KEY`
- `MAIN_MODEL`, `SUB_MODEL`
- `JWT_SECRET`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`
- `TAVILY_API_KEY`, `EXA_API_KEY`, `METASO_API_KEY`
- `VITE_API_BASE_URL`

也可以使用本地私有的 `config/model.json` 管理多供应商模型配置。详见 `docs/CONFIGURATION.md`。

## 前端 API

前端只读取一个 API 基础地址：

- `VITE_API_BASE_URL`，默认 `/api`

同源部署时保持默认值即可，由后端托管 `frontend/dist`。前后端分开部署时，把它设置成后端的完整 API 地址，例如：

```bash
VITE_API_BASE_URL=https://your-backend.example/api
```

修改后需要重新构建前端。

## 质量检查

```bash
start.bat doctor
```

或：

```bash
./start.sh doctor
```

`doctor` 会检查 Python 编译、关键 import、依赖一致性、后端单元测试、Ruff、前端 lint 和前端构建。

## 维护原则

- `/api/tasks` 是新增长任务的唯一 canonical 接口。
- 后端新增路由必须进入对应 domain router。
- 前端新增复杂功能必须优先落在 `frontend/src/features/<domain>/`。
- 新配置项必须同步 `.env.example` 与 `docs/CONFIGURATION.md`。
- 用户可见行为变化必须同步 `docs/USER_GUIDE.md` 或对应专项文档。

## 数据与安全

默认策略是最小化持久化：

- 试卷默认保存题目 ID 和轻量元数据。
- 题干、答案、解析等内容只有在显式开启相关 `PAPER_STORE_*` 配置后才会持久化。
- `.env`、本地数据库、生成物和抓取内容不要提交到 Git。

本地数据通常位于 `.local/`、`data/`、`artifacts/`、`study_archives/` 或 `output/`。

## 文档

- `docs/README.md`：文档索引
- `docs/USER_GUIDE.md`：功能使用指南
- `docs/DEVELOPMENT.md`：开发指南
- `docs/ARCHITECTURE.md`：架构与模块边界
- `docs/API.md`：后端 API 总览
- `docs/CONFIGURATION.md`：配置说明
- `docs/DEPLOYMENT.md`：部署与运行
- `docs/QUALITY_AND_RELEASE.md`：质量门禁与发布检查
- `docs/CHERRY_STUDIO_MCP_GUIDE.md`：Cherry Studio MCP 配置
- `docs/TROUBLESHOOTING.md`：常见问题排查
