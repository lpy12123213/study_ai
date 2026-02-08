# 智能组卷辅助系统

## 项目简介

这是一个基于AI的智能组卷辅助系统，帮助用户从组卷网筛选题目并生成试卷。

### 核心功能

- 多种题目搜索方式（关键词、知识点、难度、题型等）
- AI智能筛选和组卷
- 可视化“蓝图组卷”：按多个槽位一次性组装题目 ID 列表，并支持年级/教材版本/省份等筛选
- 只存储题目编号，遵守版权规定
- 引导用户到官网正规下载

### 技术栈

- **后端**: Python + FastAPI
- **爬虫**: Playwright
- **AI集成**: MCP (Model Context Protocol)
- **数据库**: SQLite
- **前端**: React + Vite + TypeScript

## 项目结构

```
study_ai/
├── backend/                 # FastAPI 后端（含 crawler/core/mcp/database）
│   ├── api/                 # API 路由与 schemas
│   ├── crawler/             # Playwright 爬虫
│   ├── core/                # 共享配置与学科映射
│   ├── database/            # SQLite 数据库模型与操作
│   └── mcp/                 # MCP 工具 + stdio 服务器入口
├── frontend/                # Vite + React + TypeScript 前端
├── docs/                    # 项目文档
├── scripts/                 # 实用脚本
├── Dockerfile.agent
├── docker-compose.agent.yml
├── requirements.txt
├── pyproject.toml
├── mcp_config.json
├── .env.example
├── start.bat / start.ps1 / start.sh
└── README.md
```

## 快速开始

推荐直接使用启动脚本（会自动创建虚拟环境、安装依赖并启动服务）。

### Windows（推荐）

- 双击运行项目根目录 `start.bat`
- 或命令行运行：
  - `start.bat dev`：后端 + 前端（默认）
  - `start.bat all`：后端 + 前端 + MCP
  - `start.bat doctor`：smoke checks

停止服务：在同一个窗口按一次 `Ctrl+C`。

### Linux/macOS

```bash
chmod +x start.sh
./start.sh dev
```

### 手动启动（可选）

```bash
# 1) 创建并激活虚拟环境
python -m venv venv
# Windows: venv\Scripts\activate
# Linux/macOS: source venv/bin/activate

# 2) 安装后端依赖 + Playwright
pip install -r requirements.txt
python -m playwright install chromium

# 3) 启动后端
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload

# 4) 启动前端（开发模式）
cd frontend
npm install
npm run dev
```

## MCP（可选：Claude Desktop / Cherry Studio）

本项目的 MCP 服务器入口：

- `python -m backend.mcp.stdio_server`

配置时可参考 `mcp_config.json`（需要把路径改成你本机的**绝对路径**），例如：

```json
{
  "mcpServers": {
    "exam-paper-assistant": {
      "command": "python",
      "args": ["C:\\path\\to\\study_ai\\backend\\mcp\\stdio_server.py"],
      "description": "智能组卷辅助系统MCP服务器"
    }
  }
}
```

### 配置环境变量

复制 `.env.example` 文件为 `.env` 并填写配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```bash
# 对话模型供应商（openrouter / fireworks）
CHAT_PROVIDER=fireworks

# Fireworks AI 配置（当 CHAT_PROVIDER=fireworks 时使用）
FIREWORKS_API_KEY=your_fireworks_key_here
FIREWORKS_BASE_URL=https://api.fireworks.ai/inference/v1

# OpenRouter API 配置（当 CHAT_PROVIDER=openrouter 时使用）
OPENROUTER_API_KEY=your_api_key_here
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# 模型配置
MAIN_MODEL=accounts/fireworks/models/deepseek-v3p2-thinking        # 主AI模型（对话 + 工具调用）
SUB_MODEL=accounts/fireworks/models/deepseek-v3p2-thinking         # 子AI选题模型

# 模型参数
MAIN_MODEL_TEMPERATURE=0.7
MAIN_MODEL_MAX_TOKENS=2000
SUB_MODEL_TEMPERATURE=0.3
SUB_MODEL_MAX_TOKENS=1000

# 对话配置
MAX_TOOL_ITERATIONS=10              # 最大工具调用轮数

# 默认学科
DEFAULT_SUBJECT=高中数学

# 超时配置（秒）
API_TIMEOUT=120
SUB_AI_TIMEOUT=60

# Zhipu BigModel（用于 MCP 工具：web_search）
ZHIPU_API_KEY=your_zhipu_api_key_here
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4
ZHIPU_MODEL=glm-4.5
ZHIPU_TIMEOUT=60
```

### 3. 启动服务

**后端服务**：

```bash
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
```

**前端服务**（开发模式）：

```bash
cd frontend
npm run dev
```

### 4. 访问应用

打开浏览器访问：`http://localhost:3000`

- 侧边栏 `蓝图`：可视化配置组卷蓝图并一键生成题目列表/创建试卷
- 侧边栏 `试卷`：查看已保存的试卷与题目链接

## 配置说明

所有配置项从环境变量加载（`.env`），集中在 `backend/core/settings.py` 中；`backend/config.py` 为兼容层（旧导入路径仍可用）。

### 模型配置

- **MAIN_MODEL**: 主AI模型，负责对话和工具调用编排
- **SUB_MODEL**: 子AI模型，负责智能选题
- 当 `CHAT_PROVIDER=openrouter`：支持的模型列表见 [OpenRouter](https://openrouter.ai/models)
- 当 `CHAT_PROVIDER=fireworks`：模型名通常形如 `accounts/fireworks/models/...`（以 Fireworks 控制台为准）

### 学科支持

系统支持 21 个学科（高中、初中、小学），包括：
- 高中：数学、语文、英语、物理、化学、生物、政治、历史、地理
- 初中：数学、语文、英语、物理、化学、生物、道德与法治、历史、地理
- 小学：数学、语文、英语

在前端页面顶部可以切换学科与对话模型（模型覆盖仅影响当前浏览器，不会修改 `.env`）。

## 合规说明

- 本系统仅存储题目编号，不存储题目内容
- 用户需要到组卷网官网使用正规方式下载题目
- 爬虫设置了合理的请求间隔，避免对网站造成压力
- 请遵守组卷网的使用条款

## 许可证

仅供学习交流使用

## 更多文档

- `docs/SEARCH_FILTERS_AND_BLUEPRINTS.md`：题目搜索的年级/教材/选修过滤、质量评分、去重，以及组卷蓝图用法。
