# 系统架构说明

## 总体架构

```
┌─────────────┐
│   用户界面   │
│  (浏览器)   │
└──────┬──────┘
       │
       │ HTTP
       ↓
┌─────────────┐
│  Web前端    │
│ (React/Vite)│
└──────┬──────┘
       │
       │ REST API
       ↓
┌─────────────┐
│  FastAPI    │
│  后端服务   │
└──────┬──────┘
       │
       │ SQLAlchemy
       ↓
┌─────────────┐
│  SQLite     │
│  数据库     │
│ (题目编号)  │
└─────────────┘


┌──────────────┐
│  Claude AI   │
│   (用户)     │
└──────┬───────┘
       │
       │ MCP Protocol
       ↓
┌──────────────┐
│ MCP Server   │
│ (工具提供者) │
└──────┬───────┘
       │
       │ Python调用
       ↓
┌──────────────┐
│  Playwright  │
│    爬虫      │
└──────┬───────┘
       │
       │ HTTP
       ↓
┌──────────────┐
│   组卷网     │
│(zujuan.xkw)  │
└──────────────┘
```

## 模块索引（入口与路由）

后端入口：
- FastAPI 应用入口：`backend/app.py`
- API 路由汇总（所有 `/api/*`）：`backend/api/router.py`

主要路由模块（按 `backend/api/router.py` 注册顺序）：
- 系统与健康检查：`backend/api/system.py`
- 兼容模型/老接口：`backend/api/models.py`（legacy/shim）
- 爬虫工具封装：`backend/api/crawler_tools.py`
- 学习画布：`backend/api/canvas.py`
- 媒体代理与下载：`backend/api/media.py`
- 试卷与题目：`backend/api/papers.py`
- 学科与筛选项：`backend/api/subjects.py`
- 对话（会话/消息）：`backend/api/conversations.py`
- Chat 对话：`backend/api/chat.py`
- 认证（JWT）：`backend/api/auth.py`
- DeepThink：`backend/api/deepthink.py`
- 教案：`backend/api/lesson_plan.py`
- 自学资料（SSE 任务）：`backend/api/study_materials.py`
- 题目质量评估：`backend/api/question_evaluate.py`
- 组卷蓝图：`backend/api/blueprints.py`
- 本地题库：`backend/api/question_library.py`
- 任务中心（统一任务与事件）：`backend/api/tasks.py`
- 收藏/置顶/标签（通用 meta）：`backend/api/item_meta.py`
- 自学资料归档：`backend/api/study_archives.py`
- 分享链接（含公开只读访问）：`backend/api/share_links.py`
- 模板库：`backend/api/templates.py`
- 批注/标注：`backend/api/annotations.py`
- 反馈与问题上报：`backend/api/feedback.py`
- 错题本：`backend/api/wrongbook.py`
- 学习计划：`backend/api/learning_plans.py`
- 导出中心：`backend/api/exports.py`
- 个人学习数据面板：`backend/api/dashboard.py`

新增域模块时：在此列表按顺序补充一行，格式为 `- <功能>：\`backend/api/<file>.py\``。

数据库与存储：
- SQLAlchemy 模型：`backend/database/schema.py`
- Engine / session / init：`backend/database/engine.py`
- CRUD 仓库层：`backend/database/repositories/`
- 兼容入口：`backend/database/models.py`（只做导出旧路径，推荐新路径）

## Legacy / Shim 说明

- `backend/database/models.py`：历史上把 schema+engine+CRUD 混在一个文件；现在已拆分到 `backend/database/*`，该文件仅保留旧 import 路径兼容。
- `docs/ARCHITECTURE.md`：以“索引 + 入口定位”为准；旧段落中若出现历史文件名（例如早期爬虫入口）以代码实际路径为准。

## 模块详解

### 1. MCP服务器 (`backend/mcp/stdio_server.py`)

**职责：** 为AI提供题目搜索和筛选工具

**核心功能：**
- 注册MCP工具（search, filter, create_paper等）
- 处理AI的工具调用请求
- 调用爬虫模块获取数据
- 调用数据库模块保存数据

**关键文件：**
- `stdio_server.py` - MCP服务器主程序（stdio）

**工具列表：**
- `search_questions_by_keyword` - 关键词搜索
- `search_questions_by_knowledge` - 知识点搜索
- `filter_questions` - 题目筛选
- `get_question_info` - 获取题目信息
- `create_paper` - 创建试卷

**通信协议：**
- 使用MCP (Model Context Protocol)
- stdio方式与Claude通信
- JSON格式数据交换

### 2. 爬虫模块 (`backend/crawler/`)

**职责：** 从组卷网获取题目元数据

**核心功能：**
- 使用Playwright模拟浏览器
- 搜索题目（关键词、知识点）
- 提取题目元数据（编号、题型、难度等）
- 不存储题目内容，只返回编号

**关键文件：**
- `backend/crawler/zujuan/client.py` - 组卷网检索/列表抓取（visitor + cookie）
- `backend/crawler/zujuan/detail.py` - 题目详情抓取与解析（题干/解析等）
- `backend/crawler/zujuan/basket.py` - 题篮导出与登录辅助（可选）

**技术特点：**
- 异步操作（async/await）
- 请求延迟（避免反爬）
- 无头浏览器模式
- CSS选择器提取数据

**数据提取流程：**
```
1. 初始化浏览器
   ↓
2. 访问搜索页面
   ↓
3. 填写搜索条件
   ↓
4. 提交搜索
   ↓
5. 解析结果页面
   ↓
6. 提取题目元数据
   ↓
7. 返回题目编号列表
```

**反爬策略：**
- 设置真实User-Agent
- 请求间隔延迟
- 模拟人类操作
- 避免频繁请求

### 3. 数据库模块 (`database/`)

**职责：** 存储试卷和题目编号

**核心功能：**
- 定义数据模型
- 提供CRUD操作
- 异步数据库访问

**关键文件：**
- `backend/database/schema.py` - SQLAlchemy 数据模型定义
- `backend/database/engine.py` - engine/session/init_db
- `backend/database/repositories/` - 领域 CRUD（async session 注入友好）
- `backend/database/models.py` - 兼容层（保留旧 import 路径）

**数据模型：**

```
Paper (试卷表)
├── id: int (主键)
├── user_id: str (用户隔离)
├── paper_name: str (试卷名称)
├── created_at: datetime (创建时间)
├── updated_at: datetime (更新时间)
└── questions: relationship (关联题目)

PaperQuestion (试卷题目表)
├── id: int (主键)
├── paper_id: int (外键 → Paper)
├── question_id: str (题目编号) ⭐
├── question_order: int (题目顺序)
├── question_type: str (题型)
├── difficulty: str (难度)
├── knowledge_point: str (知识点)
└── source_url: str (题目URL)

SearchHistory (搜索历史表)
├── id: int (主键)
├── search_type: str (搜索类型)
├── search_query: str (搜索内容)
├── result_count: int (结果数量)
└── created_at: datetime (创建时间)
```

**重要：** 只存储题目编号，不存储题目内容！

### 4. Web后端 (`backend/`)

**职责：** 提供REST API和前端服务

**核心功能：**
- RESTful API接口
- 试卷CRUD操作
- 生成下载链接
- 提供静态文件服务

**关键文件：**
- `app.py` - FastAPI应用主程序

**API端点（示例，非完整列表）：**

完整 API 列表以 OpenAPI 为准：启动后访问 `GET /docs`，或直接查看 `backend/api/router.py` 注册的路由模块。

```
GET  /                           - 前端页面
GET  /api/health                 - 健康检查
GET  /api/papers                 - 获取试卷列表
POST /api/papers                 - 创建试卷
GET  /api/papers/{id}            - 获取试卷详情
DELETE /api/papers/{id}          - 删除试卷
GET  /api/papers/{id}/download-link - 获取下载链接
POST /api/search-history         - 记录搜索历史
```

**技术栈：**
- FastAPI - 现代Web框架
- Uvicorn - ASGI服务器
- Pydantic - 数据验证
- CORS - 跨域支持

### 5. Web前端 (`frontend/`)

**职责：** 用户界面展示

**核心功能：**
- 展示试卷列表
- 查看试卷详情
- 获取下载链接
- 删除试卷

**关键文件：**
- `src/main.tsx` - 应用入口

**技术特点：**
- React/Vite/TypeScript
- 响应式设计
- 模态框交互
- AJAX请求

## 数据流详解

### 场景1：AI搜索题目并创建试卷

```
用户 → Claude AI: "搜索函数相关题目"
         ↓
Claude AI → MCP Server: call_tool(search_questions_by_keyword, {keyword: "函数"})
         ↓
MCP Server → Crawler: search_by_keyword("函数")
         ↓
Crawler → 组卷网: 访问搜索页面
         ↓
组卷网 → Crawler: 返回搜索结果页面
         ↓
Crawler → MCP Server: 返回题目编号列表 [{"question_id": "12345", ...}]
         ↓
MCP Server → Claude AI: 返回JSON结果
         ↓
Claude AI → 用户: "找到20道题目"
         ↓
用户 → Claude AI: "创建试卷"
         ↓
Claude AI → MCP Server: call_tool(create_paper, {paper_name: "...", question_ids: [...]})
         ↓
MCP Server → Database: save_paper(...)
         ↓
Database → MCP Server: paper_id = 1
         ↓
MCP Server → Claude AI: {"success": true, "paper_id": 1}
         ↓
Claude AI → 用户: "试卷创建成功！ID: 1"
```

### 场景2：用户查看和下载试卷

```
用户 → 浏览器: 访问 http://localhost:8000
         ↓
浏览器 → 后端API: GET /api/papers
         ↓
后端API → 数据库: list_papers()
         ↓
数据库 → 后端API: 返回试卷列表
         ↓
后端API → 浏览器: JSON数据
         ↓
浏览器 → 用户: 显示试卷列表
         ↓
用户 → 浏览器: 点击"下载链接"
         ↓
浏览器 → 后端API: GET /api/papers/{id}/download-link
         ↓
后端API → 数据库: get_paper(id)
         ↓
数据库 → 后端API: 试卷详情（含题目编号）
         ↓
后端API → 浏览器: 组卷网链接列表
         ↓
浏览器 → 用户: 显示题目链接
         ↓
用户 → 组卷网: 访问链接查看题目
         ↓
用户 → 组卷网: 使用官方下载功能
```

## 安全和合规设计

### 1. 数据最小化原则

- 默认存储题目编号与必要元数据（题型/难度/知识点/来源链接等）
- 可选（本地）：保存题干纯文本用于预览与审卷（不含答案/解析）
- 不存储题目图片

### 2. 版权保护

- 引导用户到官网下载
- 不提供直接下载功能
- 明确使用说明

### 3. 反爬虫友好

- 设置请求延迟
- 限制并发数量
- 模拟真实用户行为

### 4. 用户隐私

- 本地数据存储
- 不上传云端
- 可随时删除数据

## 扩展性设计

### 1. 支持更多网站

在 `crawler/` 下创建新爬虫类：
```python
class OtherSiteCrawler:
    # 实现相同接口
    async def search_by_keyword(self, keyword: str):
        pass
```

### 2. 支持更多题型

扩展 `filter_questions` 的筛选条件

### 3. 添加用户系统

在 `database/models.py` 添加 User 模型

### 4. 支持试卷导出

添加PDF/Word导出功能（只含题目编号）

## 性能优化

### 1. 爬虫优化

- 并发请求
- 结果缓存
- 连接池复用

### 2. 数据库优化

- 添加索引
- 查询优化
- 连接池

### 3. API优化

- 响应缓存
- 分页查询
- 数据压缩

## 部署架构

### 开发环境

```
本地机器
├── Python虚拟环境
├── SQLite数据库
├── Playwright浏览器
└── 开发服务器
```

### 生产环境（建议）

```
服务器
├── Docker容器
│   ├── Python应用
│   ├── Playwright
│   └── SQLite/PostgreSQL
├── Nginx (反向代理)
└── 日志监控
```

## 技术选型理由

### 为什么选择Playwright？

- 现代化、异步API
- 支持多种浏览器
- 强大的元素定位
- 自动等待机制

### 为什么选择MCP？

- Claude官方支持
- 标准化工具协议
- 易于集成AI

### 为什么选择FastAPI？

- 高性能
- 自动API文档
- 异步支持
- 类型检查

### 为什么选择SQLite？

- 轻量级
- 零配置
- 本地存储
- 适合小型项目

## 总结

这个系统的核心设计理念：

1. **合规第一** - 只存编号，引导官网下载
2. **AI驱动** - 通过MCP让AI调用工具
3. **模块化** - 清晰的职责分离
4. **易扩展** - 可添加新功能和新网站
5. **用户友好** - 简单易用的界面

通过合理的架构设计，系统既满足功能需求，又保证了合规性和可维护性。
