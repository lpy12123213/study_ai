# 智能组卷辅助系统

## 项目简介

这是一个基于AI的智能组卷辅助系统，帮助用户从组卷网筛选题目并生成试卷。

### 核心功能

- 多种题目搜索方式（关键词、知识点、难度、题型等）
- AI智能筛选和组卷
- 只存储题目编号，遵守版权规定
- 引导用户到官网正规下载

### 技术栈

- **后端**: Python + FastAPI
- **爬虫**: Playwright
- **AI集成**: MCP (Model Context Protocol)
- **数据库**: SQLite
- **前端**: HTML + JavaScript

## 项目结构

```
exam_paper_assistant/
├── mcp_server/          # MCP服务器实现
├── crawler/             # Playwright爬虫模块
├── backend/             # Web后端API
├── frontend/            # 前端页面
├── database/            # 数据库模型和迁移
├── docs/                # 项目文档
└── README.md
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
cd frontend && npm install
```

### 2. 配置环境变量

复制 `.env.example` 文件为 `.env` 并填写配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```bash
# OpenRouter API 配置
OPENROUTER_API_KEY=your_api_key_here
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# 模型配置
MAIN_MODEL=openai/gpt-5-mini        # 主AI模型
SUB_MODEL=openai/gpt-5-mini         # 子AI选题模型

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
```

### 3. 启动服务

**后端服务**：

```bash
cd exam_paper_assistant
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
```

**前端服务**（开发模式）：

```bash
cd frontend
npm run dev
```

### 4. 访问应用

打开浏览器访问：`http://localhost:3002`

## 配置说明

所有配置项都在 `backend/config.py` 中集中管理，支持通过环境变量覆盖默认值。

### 模型配置

- **MAIN_MODEL**: 主AI模型，负责对话和工具调用编排
- **SUB_MODEL**: 子AI模型，负责智能选题
- 支持的模型列表见 [OpenRouter](https://openrouter.ai/models)

### 学科支持

系统支持 21 个学科（高中、初中、小学），包括：
- 高中：数学、语文、英语、物理、化学、生物、政治、历史、地理
- 初中：数学、语文、英语、物理、化学、生物、道德与法治、历史、地理
- 小学：数学、语文、英语

在前端页面顶部可以切换学科。

## 合规说明

- 本系统仅存储题目编号，不存储题目内容
- 用户需要到组卷网官网使用正规方式下载题目
- 爬虫设置了合理的请求间隔，避免对网站造成压力
- 请遵守组卷网的使用条款

## 开发者

高中生个人项目，用于学习AI和Web开发

## 许可证

仅供学习交流使用
