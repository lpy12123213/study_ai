# 常见问题解决

## 安装问题

### 1. Playwright安装失败

**问题：** `playwright install` 失败或下载缓慢

**解决方案：**

```bash
# 使用国内镜像
set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/
playwright install chromium

# 或手动指定浏览器路径
playwright install chromium --with-deps
```

### 2. pip安装依赖失败

**问题：** 某些包安装失败

**解决方案：**

```bash
# 使用国内镜像
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 分别安装问题包
pip install playwright --upgrade
```

---

## 运行问题

### 3. MCP服务器无法启动

**问题：** `python mcp_server/server.py` 报错

**可能原因及解决：**

**原因1：** 缺少mcp包
```bash
pip install mcp
```

**原因2：** 导入路径错误
- 检查是否在项目根目录运行
- 确认`crawler`和`database`模块存在

**原因3：** Python版本过低
- 确保Python >= 3.8
```bash
python --version
```

### 4. Web服务器启动失败

**问题：** 端口8000被占用

**解决方案：**

```bash
# 查找占用端口的进程（Windows）
netstat -ano | findstr :8000

# 杀死进程
taskkill /PID <进程ID> /F

# 或者使用其他端口
uvicorn backend.app:app --host 0.0.0.0 --port 8001
```

### 5. 数据库初始化失败

**问题：** `database/models.py` 运行出错

**解决方案：**

```bash
# 删除旧数据库
rm exam_papers.db

# 重新安装sqlalchemy
pip install sqlalchemy aiosqlite --upgrade

# 重新初始化
python database/models.py
```

---

## 爬虫问题

### 6. 爬虫无法获取题目

**问题：** 搜索返回空结果或错误

**可能原因：**

1. **组卷网页面结构变化**
   - 打开浏览器访问组卷网
   - 检查页面结构
   - 更新`crawler/zujuan_crawler.py`中的CSS选择器

2. **反爬虫机制**
   - 增加请求延迟：修改`CRAWLER_DELAY`
   - 使用代理IP
   - 添加更真实的浏览器headers

3. **网络连接问题**
   - 检查网络连接
   - 确认组卷网可正常访问

**调试方法：**

```python
# 在crawler/zujuan_crawler.py中添加调试
async def _create_page(self) -> Page:
    page = await self.browser.new_page()

    # 截图调试
    await page.screenshot(path='debug.png')

    # 打印页面内容
    content = await page.content()
    print(content)

    return page
```

### 7. 浏览器启动失败

**问题：** Playwright无法启动chromium

**解决方案：**

```bash
# Windows - 可能需要安装依赖
# 下载并安装 Visual C++ Redistributable

# Linux - 安装系统依赖
sudo apt-get update
sudo apt-get install -y \
    libnss3 \
    libxss1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0

# 重新安装playwright
playwright install chromium --force
```

---

## MCP集成问题

### 8. Claude Desktop无法连接MCP

**问题：** AI无法调用MCP工具

**检查步骤：**

1. **确认配置文件位置**
   - Windows: `%APPDATA%\Claude\config\claude_desktop_config.json`
   - macOS: `~/Library/Application Support/Claude/config/claude_desktop_config.json`

2. **检查配置格式**
```json
{
  "mcpServers": {
    "exam-paper-assistant": {
      "command": "python",
      "args": [
        "完整的绝对路径/exam_paper_assistant/mcp_server/server.py"
      ]
    }
  }
}
```

3. **路径必须使用绝对路径**
   - Windows使用`\\`或`/`
   - 确保路径中没有中文（可能导致问题）

4. **重启Claude Desktop**
   - 完全退出Claude Desktop
   - 重新启动

5. **查看日志**
   - Claude Desktop的日志文件位于配置目录
   - 检查是否有启动错误

### 9. MCP工具调用失败

**问题：** AI能看到工具但调用失败

**可能原因：**

1. **爬虫未初始化**
   - 确保`ZujuanCrawler`正确初始化
   - 检查浏览器是否成功启动

2. **参数格式错误**
   - 检查MCP工具的参数定义
   - 确认AI传递的参数类型正确

3. **超时问题**
   - 增加请求延迟
   - 调整超时设置

**调试方法：**

```python
# 在mcp_server/server.py的call_tool中添加日志
@self.server.call_tool()
async def call_tool(name: str, arguments: Any):
    print(f"调用工具: {name}")
    print(f"参数: {arguments}")

    try:
        # ... 工具处理逻辑
        pass
    except Exception as e:
        print(f"错误: {str(e)}")
        import traceback
        traceback.print_exc()
```

---

## 前端问题

### 10. 前端无法加载试卷列表

**问题：** 页面显示"加载失败"

**检查步骤：**

1. **确认后端运行**
```bash
# 访问健康检查端点
curl http://localhost:8000/api/health
```

2. **检查浏览器控制台**
   - 按F12打开开发者工具
   - 查看Console和Network标签
   - 确认API请求是否成功

3. **CORS问题**
   - 确认backend/app.py中CORS配置正确
   - 允许前端域名访问

### 11. 下载链接无法打开

**问题：** 点击题目链接无反应

**可能原因：**

1. **题目编号错误**
   - 检查数据库中存储的题目编号格式
   - 确认URL格式正确

2. **组卷网需要登录**
   - 组卷网可能需要登录才能查看题目
   - 提示用户先登录组卷网

---

## 性能问题

### 12. 爬虫速度太慢

**优化方案：**

1. **减少延迟（但要注意反爬）**
```python
self.request_delay = 1  # 从2秒减少到1秒
```

2. **并发请求**
```python
# 使用asyncio并发获取多个题目
tasks = [self.get_question_info(qid) for qid in question_ids]
results = await asyncio.gather(*tasks)
```

3. **添加缓存**
```python
from functools import lru_cache

@lru_cache(maxsize=1000)
async def get_question_info_cached(self, question_id: str):
    # 缓存题目信息
    pass
```

### 13. 数据库查询慢

**优化方案：**

1. **添加索引**
```python
# 在models.py中添加索引
class PaperQuestion(Base):
    __tablename__ = "paper_questions"

    question_id = Column(String(50), nullable=False, index=True)
```

2. **批量查询**
```python
# 一次性查询多个试卷
papers = await session.execute(
    select(Paper).options(selectinload(Paper.questions))
)
```

---

## 其他问题

### 14. 中文显示乱码

**解决方案：**

确保所有文件使用UTF-8编码：

```python
# 文件开头添加
# -*- coding: utf-8 -*-
```

### 15. 日志输出过多

**解决方案：**

调整日志级别：

```python
# backend/app.py
uvicorn.run(
    "app:app",
    log_level="warning"  # 从info改为warning
)
```

---

## 组卷网导出/题篮问题

### 16. 导出成功但题篮看不到题目

**现象：**
- 工具返回“成功添加 N 道题目到组卷网题篮”，但打开 `https://zujuan.xkw.com/basket/` 看不到题目/显示为空。

**常见原因与处理：**

1) **`bankId`（题库/学科）不一致**
- 组卷网题篮是按 `bankId` 分隔的；如果网页当前题库不是导出时使用的 `bankId`，题篮页面会看起来“为空”。
- 处理：
  - 在浏览器先打开 `https://zujuan.xkw.com/gzsx/`，确认左上角题库是“高中数学”
  - 再运行 `scripts/登录组卷网.bat` 重新登录保存 Cookie（脚本为自动模式，不需要回车）
  - 重新执行导出

2) **不建议手工改 Cookie 里的 `bankId`**
- `bankId` 通常与登录态/校验 token（如 `zujuan-core`、`__RequestVerificationToken`、`questionBasketVersion` 等）有关联。
- 只改 `bankId` 可能导致 API 返回 200 但实际不写入（返回 `questions: []`），表现为“导出成功但题篮为空”。
- 正确做法是：在网页切到目标题库后重新登录，让站点下发一整套匹配的 Cookie/token。

3) **题篮页可能被反爬/校验拦截**
- 在无浏览器环境直接抓取 `https://zujuan.xkw.com/basket/` 可能出现 404/校验页/空壳页。
- 建议使用 API 自检而不是仅凭页面渲染结果：
  - 读题篮（站点实际使用的读取方式）：`POST https://zujuan.xkw.com/zujuan-api/sync_baskets`，参数 `bankId=xx & syncFlag=8 & basketJson=`
  - 写题篮：同接口 `syncFlag=9 & basketJson=[{...}]`

**开发者排障建议：**
- 优先使用 MCP 的诊断工具（会检查 `.env`、`bankId`、以及 `sync_baskets` 连通性）。
- 若你修改了导出/登录相关代码，需重启 MCP 进程后生效（长驻进程不会自动热更新）。

---

## 获取帮助

如果以上方法都无法解决问题：

1. 查看详细错误信息和堆栈跟踪
2. 搜索GitHub Issues
3. 提供以下信息寻求帮助：
   - 操作系统和版本
   - Python版本
   - 完整的错误信息
   - 重现步骤

## 开发调试技巧

### 启用详细日志

```python
# 在各模块中添加日志
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

logger.debug("调试信息")
logger.info("普通信息")
logger.error("错误信息")
```

### 使用调试器

```bash
# 使用Python调试器
python -m pdb backend/app.py
```

### 测试单个模块

```bash
# 测试爬虫
python -m pytest crawler/test_crawler.py

# 测试API
python -m pytest backend/test_api.py
```
