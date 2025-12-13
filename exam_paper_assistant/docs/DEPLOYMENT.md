# 部署指南

## 环境要求

- Python 3.8+
- Windows/Linux/macOS

## 安装步骤

### 1. 克隆或下载项目

```bash
cd exam_paper_assistant
```

### 2. 创建虚拟环境（推荐）

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/macOS
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 安装Playwright浏览器

```bash
playwright install chromium
```

### 5. 初始化数据库

```bash
python database/models.py
```

## 运行服务

### 方式一：单独启动各服务

#### 1. 启动Web后端

```bash
python backend/app.py
```

访问：http://localhost:8000

#### 2. 启动MCP服务器（用于AI）

```bash
python mcp_server/server.py
```

### 方式二：配置Claude Desktop使用MCP

1. 找到Claude Desktop配置文件：
   - Windows: `%APPDATA%\Claude\config\claude_desktop_config.json`
   - macOS: `~/Library/Application Support/Claude/config/claude_desktop_config.json`

2. 添加MCP服务器配置：

```json
{
  "mcpServers": {
    "exam-paper-assistant": {
      "command": "python",
      "args": [
        "你的项目路径/exam_paper_assistant/mcp_server/server.py"
      ]
    }
  }
}
```

3. 重启Claude Desktop

## 使用流程

### 1. 通过AI搜索题目

在Claude Desktop中询问AI：

```
帮我从组卷网搜索关于"函数"的数学题，难度中等，选择10道题
```

AI会自动：
1. 调用MCP工具搜索题目
2. 筛选符合条件的题目
3. 创建试卷并保存题目编号

### 2. 查看生成的试卷

在浏览器中访问 http://localhost:8000 查看生成的试卷列表

### 3. 下载题目

1. 点击试卷的"下载链接"按钮
2. 按照提示访问组卷网官网
3. 登录组卷网账号
4. 查看题目并使用官方下载功能

## AI命令示例

### 关键词搜索

```
帮我搜索关于"二次函数"的题目，要20道题
```

### 知识点搜索

```
搜索高中数学"三角函数"知识点的题目，难度中等
```

### 综合筛选

```
我需要一份高一数学期末试卷：
- 10道选择题（简单-中等）
- 5道填空题（中等）
- 3道解答题（中等-困难）
主题：函数、集合、不等式
```

## 注意事项

### 合规使用

1. 本系统仅存储题目编号，不存储题目内容
2. 必须通过组卷网官网下载题目
3. 请遵守组卷网的使用条款
4. 控制爬取频率，避免对网站造成压力

### 爬虫适配

由于组卷网的页面结构可能变化，如果遇到无法获取题目的情况：

1. 打开 `crawler/zujuan_crawler.py`
2. 调整CSS选择器以适配新的页面结构
3. 主要需要修改的选择器：
   - `.question-item` - 题目列表项
   - `.question-type` - 题型
   - `.difficulty` - 难度
   - `.knowledge-point` - 知识点

### 性能优化

1. 调整 `CRAWLER_DELAY` 控制请求间隔
2. 使用缓存减少重复请求
3. 批量处理题目信息

## 故障排除

### 爬虫无法启动

```bash
# 重新安装playwright
playwright install chromium --force
```

### 数据库错误

```bash
# 删除数据库文件重新初始化
rm exam_papers.db
python database/models.py
```

### MCP连接失败

1. 确认Python路径正确
2. 确认MCP服务器文件路径正确
3. 查看Claude Desktop日志

## 开发调试

### 测试爬虫

```bash
python crawler/zujuan_crawler.py
```

### 查看API文档

访问：http://localhost:8000/docs

### 数据库管理

使用SQLite工具查看数据库：
```bash
sqlite3 exam_papers.db
```

## 生产部署

### 使用gunicorn（Linux）

```bash
pip install gunicorn
gunicorn backend.app:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### 使用Docker

```dockerfile
# 待补充
```

## 支持

遇到问题请查看：
- 项目README.md
- docs/API.md
- docs/TROUBLESHOOTING.md
