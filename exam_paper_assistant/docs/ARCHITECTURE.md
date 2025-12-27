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

## 模块详解

### 1. MCP服务器 (`mcp_server/`)

**职责：** 为AI提供题目搜索和筛选工具

**核心功能：**
- 注册MCP工具（search, filter, create_paper等）
- 处理AI的工具调用请求
- 调用爬虫模块获取数据
- 调用数据库模块保存数据

**关键文件：**
- `server.py` - MCP服务器主程序

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

### 2. 爬虫模块 (`crawler/`)

**职责：** 从组卷网获取题目元数据

**核心功能：**
- 使用Playwright模拟浏览器
- 搜索题目（关键词、知识点）
- 提取题目元数据（编号、题型、难度等）
- 不存储题目内容，只返回编号

**关键文件：**
- `zujuan_crawler.py` - 爬虫核心类

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
- `models.py` - 数据模型定义

**数据模型：**

```
Paper (试卷表)
├── id: int (主键)
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

**API端点：**

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

- 只存储题目编号
- 不存储题目内容
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
