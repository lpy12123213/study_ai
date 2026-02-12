# 智能组卷辅助系统

基于 AI 的教育辅助平台——集 **智能组卷**、**AI 对话选题**、**自学资料生成** 于一体。

---

## 功能概览

| 功能 | 说明 |
|------|------|
| **AI 对话组卷** | 通过自然语言与 AI 对话，搜索/筛选题目并一键创建试卷 |
| **蓝图组卷** | 可视化配置槽位（题型 × 难度 × 数量），批量组装题目 |
| **自学资料生成** | 输入知识点，AI Agent 自动检索、撰写结构化学习资料（Plan-Act-Reflect 架构） |
| **试卷管理** | 查看、删除已保存试卷；生成组卷网题目链接 |
| **MCP 集成** | 作为 MCP 工具服务器接入 Claude Desktop / Cherry Studio |
| **多学科支持** | 覆盖高中、初中、小学共 21 个学科 |

> **合规设计**：系统仅存储题目编号，不存储题目内容，引导用户到组卷网官网正规下载。

---

## 技术栈

| 层 | 技术 |
|----|------|
| **前端** | React 19 · TypeScript · Vite · TailwindCSS 4 · Radix UI · Zustand · React Query |
| **后端** | Python · FastAPI · SQLAlchemy · Pydantic v2 |
| **爬虫** | Playwright (Chromium) |
| **AI** | OpenAI 兼容接口（Fireworks / OpenRouter）· 智谱 GLM · Metaso 搜索 |
| **协议** | MCP (Model Context Protocol) — stdio 模式 |
| **数据库** | SQLite (aiosqlite) |
| **部署** | Docker / docker-compose（可选） |

---

## 项目结构

```
study_ai/
├── backend/
│   ├── agent/              # Plan-Act-Reflect 自学资料 Agent
│   ├── api/                # FastAPI 路由与 Pydantic schemas
│   ├── core/               # 共享配置 (settings.py) 与学科映射
│   ├── crawler/            # Playwright 爬虫
│   ├── database/           # SQLAlchemy 模型 + SQLite 操作
│   ├── mcp/                # MCP 工具 + stdio 服务器入口
│   └── app.py              # FastAPI 应用入口
├── frontend/
│   └── src/
│       ├── components/     # React 组件（UI / 布局 / 任务流）
│       ├── api/            # API 客户端
│       └── hooks/          # 自定义 Hooks
├── docs/                   # 架构、部署、API、排错等文档
├── scripts/                # 登录/状态管理等实用脚本
├── start.bat / .ps1 / .sh  # 一键启动脚本
├── requirements.txt
├── pyproject.toml
├── mcp_config.json
├── .env.example
└── docker-compose.agent.yml
```

---

## 快速开始

### 一键启动（推荐）

启动脚本会自动创建虚拟环境、安装依赖并启动服务。

**Windows**

```bat
start.bat              # 默认：后端 + 前端
start.bat all          # 后端 + 前端 + MCP
start.bat backend      # 仅后端
start.bat frontend     # 仅前端
start.bat doctor       # 冒烟检查
```

**Linux / macOS**

```bash
chmod +x start.sh
./start.sh dev
```

按 `Ctrl+C` 停止所有服务。

### 手动启动

```bash
# 1. 虚拟环境
python -m venv venv
# Windows: venv\Scripts\activate
# Linux/macOS: source venv/bin/activate

# 2. 后端依赖
pip install -r requirements.txt
python -m playwright install chromium

# 3. 启动后端 (http://localhost:8000)
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload

# 4. 启动前端 (http://localhost:3000，自动代理 /api → 后端)
cd frontend
npm install
npm run dev
```

---

## 环境变量配置

```bash
cp .env.example .env   # 复制模板后按需编辑
```

### 核心配置项

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CHAT_PROVIDER` | 对话模型供应商：`fireworks` / `openrouter` | `fireworks` |
| `FIREWORKS_API_KEY` | Fireworks API 密钥 | — |
| `OPENROUTER_API_KEY` | OpenRouter API 密钥 | — |
| `MAIN_MODEL` | 主 AI 模型（对话 + 工具编排） | `deepseek-v3p2` |
| `SUB_MODEL` | 子 AI 模型（选题 / 写作） | `deepseek-v3p2` |
| `DEFAULT_SUBJECT` | 默认学科 | `高中数学` |
| `ZHIPU_API_KEY` | 智谱 API 密钥（web_search 工具） | — |
| `METASO_API_KEY` | Metaso API 密钥（自学资料检索） | — |

### 认证配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `JWT_SECRET` | JWT 签名密钥（**生产环境务必修改**） | `dev-jwt-secret-change-me` |
| `JWT_EXPIRE_HOURS` | Token 有效期 | `24` |
| `ADMIN_USERNAME` | 管理员用户名 | `admin` |
| `ADMIN_PASSWORD` | 管理员密码 | `admin123` |

完整配置项见 `.env.example`。

---

## 使用说明

打开 `http://localhost:3000`，登录后即可使用。

- **对话**：在聊天界面用自然语言描述需求，AI 会自动调用工具搜索题目、筛选并创建试卷
- **蓝图**：侧边栏进入蓝图页面，按槽位配置题型/难度/数量，支持年级、教材版本、省份筛选，一键生成
- **试卷**：侧边栏查看已保存试卷，点击题目可跳转到组卷网原始链接
- **自学资料**：输入知识点，Agent 自动多轮检索并生成结构化讲解（支持 SSE 流式输出）
- **学科切换**：页面顶部可切换学科与模型（仅影响当前浏览器）

---

## MCP 集成

适用于 Claude Desktop / Cherry Studio 等支持 MCP 的客户端。

**入口**：`python -m backend.mcp.stdio_server`

**配置示例**（`mcp_config.json`，路径需改为本机绝对路径）：

```json
{
  "mcpServers": {
    "exam-paper-assistant": {
      "command": "python",
      "args": ["C:\\your\\path\\study_ai\\backend\\mcp\\stdio_server.py"],
      "description": "智能组卷辅助系统 MCP 服务器"
    }
  }
}
```

MCP 工具包括：`search_questions_by_keyword`、`search_questions_by_knowledge`、`filter_questions`、`get_question_info`、`create_paper`、`web_search` 等。

详细接入指南见 `docs/CHERRY_STUDIO_MCP_GUIDE.md`。

---

## 学科支持

| 学段 | 学科 |
|------|------|
| **高中** | 数学、语文、英语、物理、化学、生物、政治、历史、地理 |
| **初中** | 数学、语文、英语、物理、化学、生物、道德与法治、历史、地理 |
| **小学** | 数学、语文、英语 |

---

## 开发指南

### 代码规范

- **Python**：4 空格缩进，类型注解，snake_case（详见 `.editorconfig`、`pyproject.toml`）
- **前端**：严格 TypeScript，PascalCase 组件，2 空格缩进

### 冒烟检查

```bash
python -m compileall . -q
python -c "import backend.app, backend.mcp.stdio_server"
cd frontend && npm run build
```

### 提交规范

遵循 Conventional Commits：`feat:`、`fix:`、`refactor:`、`docs:`、`chore:` 等。

---

## 合规说明

- 仅存储题目编号，**不存储题目内容**
- 引导用户到组卷网官网正规下载
- 爬虫设置合理请求间隔，避免对目标网站造成压力
- 请遵守组卷网使用条款

## 更多文档

| 文档 | 说明 |
|------|------|
| `docs/ARCHITECTURE.md` | 系统架构与数据流 |
| `docs/API.md` | REST API 接口文档 |
| `docs/DEPLOYMENT.md` | 部署指南 |
| `docs/SEARCH_FILTERS_AND_BLUEPRINTS.md` | 搜索过滤、质量评分与蓝图用法 |
| `docs/CHERRY_STUDIO_MCP_GUIDE.md` | Cherry Studio MCP 接入指南 |
| `docs/OPENAI_INTEGRATION.md` | OpenAI Function Calling 集成指南 |
| `docs/TROUBLESHOOTING.md` | 常见问题排查 |
| `docs/STUDY_MATERIAL_IMPROVEMENTS.md` | 自学资料生成功能说明 |
| `docs/SVG_TO_LATEX.md` | SVG 公式转 LaTeX 工具说明 |

## 许可证

仅供学习交流使用
