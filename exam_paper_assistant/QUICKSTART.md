# 快速开始指南

欢迎使用智能组卷辅助系统！这个指南将帮助你在5分钟内启动并使用系统。

## 第一步：安装依赖

### Windows用户

双击运行项目根目录的 `start.bat`（或 `exam_paper_assistant/start.bat`），脚本会自动完成：
- 创建虚拟环境
- 安装Python依赖
- 安装Playwright浏览器
- 初始化数据库
- 启动后端与前端开发服务器

停止服务：在同一个窗口按一次 `Ctrl+C`（会自动清理并停止所有已启动的子进程）。

常用命令（命令行运行）：
- `start.bat setup`：仅安装依赖（不启动服务）
- `start.bat dev`：启动后端 + 前端（默认）
- `start.bat all`：启动后端 + 前端 + MCP
- `start.bat doctor`：运行 smoke checks

### Linux/macOS用户

```bash
chmod +x start.sh
./start.sh
```

常用命令：
- `./start.sh setup`：仅安装依赖（不启动服务）
- `./start.sh dev`：启动后端 + 前端（默认）
- `./start.sh all`：启动后端 + 前端 + MCP
- `./start.sh doctor`：运行 smoke checks

### 手动安装（可选）

如果自动脚本失败，可以手动执行：

```bash
# 1. 创建虚拟环境
python -m venv venv

# 2. 激活虚拟环境
# Windows
venv\Scripts\activate
# Linux/macOS
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt
playwright install chromium

# 4. 初始化数据库
python database/models.py

# 5. 启动服务
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload

# 6. 启动前端（开发模式）
cd frontend
npm install
npm run dev
```

## 第二步：配置Claude Desktop（可选但推荐）

要使用AI搜索功能，需要配置MCP：

### 1. 找到Claude Desktop配置文件

- **Windows**: `%APPDATA%\Claude\config\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/config/claude_desktop_config.json`

### 2. 编辑配置文件

参考 `mcp_config.json`，添加以下内容（修改路径为你的实际路径）：

```json
{
  "mcpServers": {
    "exam-paper-assistant": {
      "command": "python",
      "args": [
        "C:\\path\\to\\exam_paper_assistant\\mcp_server\\server.py"
      ]
    }
  }
}
```

注意：
- 使用绝对路径
- Windows路径用 `\\` 或 `/`
- 确保Python在系统PATH中

### 3. 重启Claude Desktop

完全退出并重新启动Claude Desktop

## 第三步：使用系统

### 访问Web界面

打开浏览器，访问：http://localhost:3000

后端API地址：http://localhost:8000

你会看到：
- 试卷列表
- 使用说明
- 下载引导

### 通过AI创建试卷

在Claude Desktop中输入：

```
帮我从组卷网搜索高中数学"函数"相关的题目，
要求：
- 10道选择题（中等难度）
- 5道填空题（中等难度）
- 3道解答题（中等-困难）
然后创建一份试卷
```

AI会自动：
1. 搜索符合条件的题目
2. 筛选题目
3. 创建试卷
4. 保存题目编号

### 查看和下载试卷

1. 在Web界面刷新，看到新创建的试卷
2. 点击"查看详情"查看题目编号
3. 点击"下载链接"获取组卷网链接
4. 访问组卷网官网，登录后查看题目
5. 使用组卷网的官方下载功能

## 常用AI指令示例

### 关键词搜索

```
搜索关于"圆锥曲线"的数学题，要20道
```

### 按难度筛选

```
找一些简单的物理力学题目，适合高一学生，要15道
```

### 综合组卷

```
帮我组一份高二化学测试卷：
- 化学平衡：5道选择题
- 电化学：3道填空题
- 有机化学：2道解答题
难度中等
```

### 按知识点搜索

```
我需要"三角函数"和"向量"两个知识点的题目各10道，
难度中等到困难
```

## 系统架构说明

```
用户 ←→ Claude AI ←→ MCP服务器 ←→ 爬虫 → 组卷网
                          ↓
                      数据库（只存编号）
                          ↓
                     Web后端API
                          ↓
                      前端页面
```

## 重要提醒

1. **合规使用**：
   - 只存储题目编号，不存储题目内容
   - 必须通过组卷网官网下载题目
   - 遵守组卷网使用条款

2. **爬虫设置**：
   - 默认请求间隔2秒
   - 避免频繁请求
   - 不要对网站造成压力

3. **数据隐私**：
   - 所有数据存储在本地
   - 不上传到云端

## 故障排除

### Web服务器无法启动

```bash
# 检查端口是否被占用
netstat -ano | findstr :8000

# 使用其他端口
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8001 --reload
```

### AI无法调用MCP工具

1. 检查MCP配置文件路径是否正确
2. 确认使用绝对路径
3. 重启Claude Desktop
4. 查看Claude Desktop日志

### 爬虫无法获取题目

1. 检查网络连接
2. 确认组卷网可访问
3. 可能需要更新CSS选择器（如果网站改版）

详细问题请查看：`docs/TROUBLESHOOTING.md`

## 下一步

- 查看 `docs/API.md` 了解API接口
- 查看 `docs/DEPLOYMENT.md` 了解详细部署
- 修改 `crawler/zujuan_crawler.py` 自定义爬虫逻辑

## 获取帮助

如有问题：
1. 查看 `docs/TROUBLESHOOTING.md`
2. 检查终端错误信息
3. 查看API文档：http://localhost:8000/docs

祝使用愉快！
