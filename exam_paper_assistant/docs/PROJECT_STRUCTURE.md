# 项目文件结构

```
exam_paper_assistant/
│
├── README.md                    # 项目说明
├── QUICKSTART.md               # 快速开始指南
├── requirements.txt            # Python依赖
├── .env.example                # 环境变量示例
├── .gitignore                  # Git忽略文件
├── mcp_config.json             # MCP配置示例
├── start.bat                   # Windows启动脚本
├── start.sh                    # Linux/macOS启动脚本
│
├── mcp_server/                 # MCP服务器模块
│   ├── __init__.py
│   └── server.py               # MCP服务器主程序
│                               # - 注册AI工具
│                               # - 处理工具调用
│                               # - 协调爬虫和数据库
│
├── crawler/                    # 爬虫模块
│   ├── __init__.py
│   └── zujuan_crawler.py       # 组卷网爬虫
│                               # - Playwright浏览器自动化
│                               # - 题目搜索和筛选
│                               # - 只提取题目元数据
│
├── database/                   # 数据库模块
│   ├── __init__.py
│   └── models.py               # 数据模型定义
│                               # - Paper（试卷表）
│                               # - PaperQuestion（题目编号表）
│                               # - SearchHistory（搜索历史）
│                               # - CRUD操作函数
│
├── backend/                    # Web后端
│   ├── __init__.py
│   └── app.py                  # FastAPI应用
│                               # - REST API端点
│                               # - 试卷管理
│                               # - 下载链接生成
│
├── frontend/                   # Web前端（Vite + React + TS）
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       └── App.tsx
│
├── tools/                      # 调试/验证脚本
├── artifacts/                  # 调试产物（截图/HTML/JSON）
├── data/                       # 本地数据文件
│
└── docs/                       # 文档目录
    ├── DEPLOYMENT.md           # 部署指南
    ├── API.md                  # API文档
    ├── ARCHITECTURE.md         # 架构说明
    └── TROUBLESHOOTING.md      # 故障排除

运行时生成的文件（不纳入版本控制）：
├── artifacts/                  # 调试产物
├── data/                       # 本地数据文件（含旧库备份）
├── venv/                       # Python虚拟环境
├── exam_papers.db              # SQLite数据库文件
└── __pycache__/                # Python缓存
```

## 核心文件说明

### 1. 配置和启动文件

| 文件 | 用途 | 使用场景 |
|------|------|----------|
| `requirements.txt` | Python依赖列表 | 安装依赖时使用 |
| `.env.example` | 环境变量模板 | 需要自定义配置时复制为.env |
| `mcp_config.json` | MCP配置示例 | 配置Claude Desktop时参考 |
| `start.bat` / `start.sh` | 启动脚本 | 一键启动Web服务器 |

### 2. MCP服务器 (`mcp_server/server.py`)

**核心类：** `ExamPaperMCPServer`

**主要功能：**
- 注册5个MCP工具供AI调用
- 处理AI的工具调用请求
- 调用爬虫获取题目数据
- 调用数据库保存试卷

**工具列表：**
1. `search_questions_by_keyword` - 关键词搜索
2. `search_questions_by_knowledge` - 知识点搜索
3. `filter_questions` - 题目筛选
4. `get_question_info` - 获取题目信息
5. `create_paper` - 创建试卷

### 3. 爬虫模块 (`crawler/zujuan_crawler.py`)

**核心类：** `ZujuanCrawler`

**主要方法：**
- `initialize()` - 初始化Playwright浏览器
- `search_by_keyword()` - 关键词搜索题目
- `search_by_knowledge()` - 知识点搜索题目
- `filter_questions()` - 筛选题目
- `get_question_info()` - 获取单个题目信息
- `close()` - 关闭浏览器

**重要特性：**
- 异步操作（async/await）
- 请求延迟（默认2秒）
- 只提取元数据，不存内容
- 可独立测试运行

### 4. 数据库模块 (`database/models.py`)

**数据模型：**

```python
Paper                          # 试卷表
├── id                        # 主键
├── paper_name                # 试卷名称
├── created_at                # 创建时间
├── updated_at                # 更新时间
└── questions (relationship)  # 关联题目

PaperQuestion                 # 试卷题目表
├── id                        # 主键
├── paper_id                  # 外键
├── question_id               # 题目编号（核心）
├── question_order            # 题目顺序
├── question_type             # 题型
├── difficulty                # 难度
├── knowledge_point           # 知识点
└── source_url                # 来源URL

SearchHistory                 # 搜索历史表
├── id
├── search_type
├── search_query
├── result_count
└── created_at
```

**核心函数：**
- `init_db()` - 初始化数据库
- `save_paper()` - 保存试卷
- `get_paper()` - 获取试卷
- `list_papers()` - 列出试卷
- `delete_paper()` - 删除试卷

### 5. Web后端 (`backend/app.py`)

**框架：** FastAPI

**API端点：**
```
GET  /                              - 前端页面
GET  /api/health                    - 健康检查
GET  /api/papers                    - 试卷列表
POST /api/papers                    - 创建试卷
GET  /api/papers/{id}               - 试卷详情
DELETE /api/papers/{id}             - 删除试卷
GET  /api/papers/{id}/download-link - 下载链接
POST /api/search-history            - 搜索历史
```

**特性：**
- 自动API文档（/docs）
- CORS支持
- 异步处理
- 静态文件服务

### 6. Web前端 (`frontend/`)

**技术栈：** React + Vite + TypeScript

**入口：** `frontend/src/main.tsx`、`frontend/src/App.tsx`

**核心功能：**
- 试卷列表展示（卡片式）
- 试卷详情查看（模态框）
- 下载链接获取
- 试卷删除

**交互流程：**
1. 页面加载 → 获取试卷列表
2. 点击"查看详情" → 显示题目信息
3. 点击"下载链接" → 生成组卷网链接
4. 点击题目链接 → 跳转到组卷网

### 7. 文档 (`docs/`)

| 文档 | 内容 |
|------|------|
| `DEPLOYMENT.md` | 安装、配置、运行的详细步骤 |
| `API.md` | REST API和MCP工具的完整文档 |
| `ARCHITECTURE.md` | 系统架构和设计理念 |
| `TROUBLESHOOTING.md` | 常见问题和解决方案 |

## 数据流向图

```
┌─────────────────────────────────────────────────────────────┐
│                        使用场景1：AI搜索                      │
└─────────────────────────────────────────────────────────────┘

用户 → Claude AI → MCP Server → Crawler → 组卷网
                       ↓
                   Database
                       ↓
                  保存试卷编号


┌─────────────────────────────────────────────────────────────┐
│                      使用场景2：查看试卷                      │
└─────────────────────────────────────────────────────────────┘

浏览器 → Backend API → Database → 返回试卷列表
                           ↓
                      组卷网链接生成
                           ↓
                   用户访问组卷网下载
```

## 技术栈总览

### 后端技术
- **Python 3.8+** - 主要编程语言
- **FastAPI** - Web框架
- **SQLAlchemy** - ORM
- **Playwright** - 浏览器自动化
- **MCP SDK** - AI工具协议

### 前端技术
- **React** - UI组件与状态管理
- **Vite** - 构建与开发服务器
- **TypeScript** - 类型系统
- **Tailwind CSS** - 样式工具链

### 数据存储
- **SQLite** - 轻量级数据库
- **只存题目编号** - 合规设计

### 开发工具
- **Git** - 版本控制
- **pip** - 包管理
- **venv** - 虚拟环境

## 使用流程

### 开发流程
1. 修改代码
2. 运行测试
3. 启动服务验证
4. 提交代码

### 用户使用流程
1. 启动Web服务器
2. 配置Claude Desktop（MCP）
3. 通过AI搜索题目
4. AI自动创建试卷
5. 在Web界面查看试卷
6. 获取组卷网链接
7. 到组卷网下载题目

## 扩展点

### 添加新功能
- 在 `mcp_server/server.py` 添加新工具
- 在 `crawler/` 添加新爬虫类
- 在 `backend/app.py` 添加新API端点
- 在 `frontend/src` 添加新UI（建议从 `App.tsx` 或 components 开始）

### 支持新网站
1. 创建 `crawler/new_site_crawler.py`
2. 实现相同的接口方法
3. 在MCP服务器中注册
4. 更新前端展示

## 重要提醒

⚠️ **合规使用**
- 只存储题目编号
- 不存储题目内容
- 引导用户到官网下载
- 遵守网站使用条款

⚠️ **爬虫友好**
- 控制请求频率
- 设置合理延迟
- 不要频繁爬取
- 模拟真实用户

⚠️ **数据安全**
- 本地存储
- 不上传云端
- 可随时删除
- 保护用户隐私

## 下一步计划

可以考虑的功能扩展：
- [ ] 添加用户系统
- [ ] 支持更多学科
- [ ] 题目收藏功能
- [ ] 试卷分享（只含编号）
- [ ] 搜索历史统计
- [ ] 支持更多题库网站
- [ ] Docker部署支持
- [ ] 单元测试覆盖

---

**项目创建时间：** 2025年1月
**适用场景：** 教育辅助、组卷助手
**许可：** 仅供学习交流使用
