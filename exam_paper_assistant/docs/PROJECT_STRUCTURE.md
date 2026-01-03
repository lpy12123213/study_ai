# 项目目录结构

`exam_paper_assistant/` 是应用根目录。日常开发/运行建议从这里执行命令（`python` / `uvicorn` / `npm` / `start.*`）。

## 一览（核心目录）

```
exam_paper_assistant/
├── backend/                 # FastAPI 后端（入口：backend/app.py）
│   ├── api/                 # REST API 路由 + Pydantic schemas（按领域拆分）
│   ├── chat_service.py      # 对话编排（工具调用/流式输出）
│   ├── openai_adapter.py    # OpenAI-compatible 适配层（对接 OpenAI SDK / 兼容协议）
│   └── ...                  # 其他后端模块
├── mcp_server/              # MCP Server（入口：python -m mcp_server.server）
├── crawler/                 # Playwright 爬虫（组卷网抓取与筛选）
├── database/                # SQLAlchemy 模型 + SQLite 读写（只存题号/元数据）
├── core/                    # 项目级配置与常量（settings/学科映射）
├── frontend/                # React + Vite + TypeScript 前端（画布式对话 UI）
├── docs/                    # 项目文档（部署、API、故障排查等）
├── scripts/                 # 一次性脚本/维护脚本（迁移本地状态、修复、整理等）
├── tools/                   # 调试/验证工具脚本（偏开发者使用）
├── playground/              # 实验性代码或临时验证（不影响主流程）
├── utils/                   # 通用工具函数（跨模块复用）
└── .local/                  # 本地运行时文件（数据库/缓存/Playwright 用户数据；已在 gitignore 中忽略）
```

## 入口与常用命令

### 一键启动（推荐）

项目内置启动脚本（自动创建虚拟环境、安装依赖、启动后端/前端/可选 MCP）：

- Windows：`exam_paper_assistant/start.bat` 或仓库根目录 `start.bat`
- PowerShell：`exam_paper_assistant/start.ps1` 或仓库根目录 `start.ps1`
- Linux/macOS：`exam_paper_assistant/start.sh` 或仓库根目录 `start.sh`

常用参数：

- `dev`：后端 + 前端
- `all`：后端 + 前端 + MCP
- `setup`：仅安装依赖
- `doctor`：运行 smoke checks

### 手动启动（可选）

- 后端：`python -m uvicorn backend.app:app --reload --port 8000`
- 前端：`cd frontend && npm run dev`

## 本地状态（`.local/`）

为了让项目根目录保持干净，本项目将“只和本机有关”的文件集中到 `exam_paper_assistant/.local/`（例如 SQLite 数据库、反爬 Cookie 缓存、Playwright 用户数据等）。

详细说明见：`exam_paper_assistant/docs/LOCAL_STATE.md`。

