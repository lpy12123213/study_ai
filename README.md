# Study AI

Study AI 是一个本地优先的学习与出题工作台。它将 AI 对话、自学资料生成、教案生成、深度解题、题库管理、AI 出题、蓝图组卷、试卷导出、知识视频和 MCP 工具服务整合为一套可本地运行的应用。

项目状态：主动开发中。文档以当前仓库代码为准，面向本地开发、内网部署和受控环境使用。

| 属性 | 说明 |
| --- | --- |
| 应用类型 | 本地优先的学习与出题工作台 |
| 后端入口 | `backend.app:app` |
| 前端入口 | `frontend/src/main.tsx` |
| 长任务入口 | `/api/tasks`（提交、追踪、SSE 回放、取消） |
| MCP 入口 | `python -m backend.mcp.stdio_server` |

技术栈：

- 后端：FastAPI、SQLAlchemy、SQLite、Playwright、MCP。
- 前端：Vite、React、TypeScript、React Router、TanStack Query、Zustand、Vitest。
- 长任务：统一 TaskRuntime，事件持久化到 SQLite，支持断点续播与恢复。

## 环境要求

必需：

- Python 3.10 或更高版本（当前开发环境为 3.13）。
- Node.js LTS 与 npm。
- 可访问模型供应商和搜索供应商的网络环境，按功能需要配置。

按需：

- Playwright Chromium：题源抓取和部分浏览器自动化。
- LaTeX 工具链（xelatex/pdflatex）：PDF 导出。
- Pandoc：DOCX 导出。
- Docker：知识视频 Manim 沙盒、LaTeX 沙盒编译。

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

- **对话工作台**：在对话中调用工具、检索题目、创建试卷，支持思考过程与工具时间线展示。
- **自学资料生成**：按主题拆解知识点，联网检索来源，经质量门审查后生成讲义；支持预设档位、断点续播、失败恢复、版本历史与持续改进（详见下文）。
- **教案生成**：面向教学场景生成结构化教案并支持导出。
- **DeepThink**：面向复杂题目的多路径解题。
- **本地题库**：抓取、筛选、收藏、隐藏、评分和批量维护题目。
- **AI 出题**：基于主题、参考资料和题型要求生成题目草稿，经人工审核入库；含直觉练习工作流。
- **蓝图组卷**：按题型、难度、知识点、年级、教材版本等约束组合题目。
- **试卷导出**：导出 Markdown、LaTeX、PDF、DOCX；含试卷批改与主观题评估链路。
- **知识视频**：生成 Manim 风格的知识讲解视频任务。
- **任务中心**：统一查看/取消/恢复所有长任务。
- **MCP 服务**：把题目搜索、组卷、审卷、联网检索等能力暴露给 MCP 客户端。

### 自学资料生成链路

资料生成是本项目的旗舰链路，具备完整的质量与恢复机制：

- **预设档位**：`quick` / `standard` / `deep` / `research`，控制知识点数量、来源下限与审查轮次。
- **质量门**：逐知识点验收（章节覆盖、内容维度、lint 截断检测）；检索不足时自动按失败知识点补检索；写作不达标时有限轮次修订，仍不达标则降级交付并明确标注，不会静默失败或空结果冒充成功。
- **断点续播与恢复**：任务事件全部持久化，刷新/断线后从上次进度续播（服务端追赶压缩）；任务可取消后继续，失败任务可按阶段恢复。
- **归档复用**：通过的讲义进入资料档案，相同请求（含选项指纹与新鲜度校验）直接复用；每个主题保留多个历史版本。
- **弹性**：LLM 永久性 4xx 快速失败、启动模型自检、检索 provider 健康缓存、工具熔断、导出失败重试降级。

相关配置与维护口径见 `docs/STUDY_MATERIAL_IMPROVEMENTS.md`。

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
|   |-- agent/            # 通用 agent 编排（ReAct/计划模式）、执行器与工具
|   |-- api/              # FastAPI 路由与 schema
|   |-- core/             # 设置、日志、安全、媒体等基础能力
|   |-- database/         # SQLAlchemy schema、迁移、仓库层
|   |-- generation/       # 各生成链路（见下）
|   |   |-- study_materials/   # 自学资料：orchestrator、质量门、workflow、归档
|   |   |-- question_library/  # 本地题库、AI 出题、评分、直觉练习
|   |   |-- paper_compose/     # 组卷与导出
|   |   |-- lesson_plan/       # 教案生成
|   |   |-- deepthink/         # 深度解题
|   |   |-- knowledge_video/   # 知识视频
|   |   `-- ...                # 批改/评估等
|   |-- integrations/     # 外部服务集成（搜索 provider、crawler 等）
|   |-- llm/              # LLM 客户端：重试、熔断、流式、prompt 注册表
|   |-- mcp/              # MCP stdio 工具服务
|   |-- shared/           # 共享基础设施，包含 TaskRuntime
|   |-- tasks/            # 长任务提交与 runner
|   |-- workspace/        # 对话工作区链路
|   `-- app.py            # FastAPI 应用入口
|-- frontend/
|   `-- src/
|       |-- app/          # 应用骨架（providers、路由目录）
|       |-- components/   # 布局与通用组件（ui、markdown、task 等）
|       |-- features/     # 按域划分（chat、study-materials、question-library、
|       |                 #   paper-compose、deepthink、task-center、sharing 等）
|       |-- pages/        # 页面与档案详情
|       |-- shared/       # API 客户端、类型、流式协调
|       `-- stores/       # Zustand 全局状态
|-- docs/
|-- scripts/
|-- start.bat / start.ps1 / start.sh
|-- requirements.txt
|-- requirements-dev.txt
`-- mcp_config.json
```

## 配置

复制 `.env.example` 到 `.env` 配置运行环境，并从模型示例创建本地模型配置：

```powershell
Copy-Item .env.example .env
Copy-Item config/model.example.json config/model.json
```

常用配置：

- `config/model.json`：唯一的模型配置源，包含 provider、API Key、Base URL、路由、模型 ID、生成参数和上下文限制
- `MODEL_CONFIG_PATH`：仅在需要把模型配置放到其他位置时设置
- `TAVILY_API_KEY`、`EXA_API_KEY`、`METASO_API_KEY`：检索 provider（至少一个）
- `JWT_SECRET`、`ADMIN_USERNAME`、`ADMIN_PASSWORD`
- `VITE_API_BASE_URL`：前端 API 基础地址，默认同源相对 `/api`；跨站部署时设为后端 origin

注意：模型 ID 一旦失效（供应商下架或拼错），所有 LLM 调用会永久失败；后端启动时会做一次非阻塞模型自检并在日志中给出明确提示。完整字段见 `config/model.example.json` 和 `docs/CONFIGURATION.md`。旧的 `.env` 模型变量不再生效。

## 前端 API

前端使用 `VITE_API_BASE_URL` 定位后端，有两种受支持的模式：

- 同源反向代理（默认）：浏览器使用相对 `/api`，由后端托管 `frontend/dist`，无需设置 `VITE_API_BASE_URL`，认证 Cookie 为 `SameSite=Lax`。
- 跨站部署：前端构建时把 `VITE_API_BASE_URL` 设为后端 origin（如 `https://api.example.com`）；后端用 `CORS_ORIGINS` 白名单允许前端 origin，并设置 `AUTH_COOKIE_SAMESITE=none`（隐含 `Secure`，要求 HTTPS）。跨站请求携带凭证（`credentials: include`、EventSource `withCredentials`）；`CORS_ORIGINS=*` 与携带凭证的请求不能同时使用。

```bash
VITE_API_BASE_URL=https://api.example.com
```

修改后需要重新构建前端。完整说明见 `docs/DEPLOYMENT.md`。

## 质量检查

```bash
start.bat doctor     # 或 ./start.sh doctor
```

`doctor` 会检查 Python 编译、关键 import、依赖一致性、后端单元测试、Ruff、前端 lint 和前端构建。

单独运行：

```bash
cd backend && python -m pytest tests/ -q        # 后端测试
cd frontend && npx vitest run && npx tsc -b     # 前端测试与类型检查
```

## 维护原则

- `/api/tasks` 是新增长任务的唯一 canonical 接口。
- 后端新增路由必须进入对应 domain router。
- 前端新增复杂功能必须优先落在 `frontend/src/features/<domain>/`。
- 新模型配置必须同步 `config/model.example.json`，新环境变量必须同步 `.env.example`；两类变更都要更新 `docs/CONFIGURATION.md`。
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
- `docs/STUDY_MATERIAL_IMPROVEMENTS.md`：自学资料链路质量指南
- `docs/DEPLOYMENT.md`：部署与运行
- `docs/QUALITY_AND_RELEASE.md`：质量门禁与发布检查
- `docs/CHERRY_STUDIO_MCP_GUIDE.md`：Cherry Studio MCP 配置
- `docs/TROUBLESHOOTING.md`：常见问题排查
