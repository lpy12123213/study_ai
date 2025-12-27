# OpenAI Codex 集成指南

## 概述

由于OpenAI Codex不支持MCP协议，我们为项目添加了OpenAI Function Calling适配器，让你可以通过OpenAI API使用组卷助手。

## 架构对比

### 原始架构（Claude + MCP）
```
Claude AI ←→ MCP Server ←→ Crawler ←→ 组卷网
                 ↓
             Database
```

### OpenAI架构（Codex + Function Calling）
```
OpenAI Codex ←→ Function Calling ←→ REST API ←→ Crawler ←→ 组卷网
                                        ↓
                                    Database
```

## 快速开始

### 第1步：安装依赖

```bash
cd exam_paper_assistant

# 安装基础依赖
pip install -r requirements.txt

# 安装OpenAI SDK
pip install openai

# 安装Playwright浏览器
playwright install chromium
```

### 第2步：初始化数据库

```bash
python database/models.py
```

### 第3步：启动OpenAI适配器API

```bash
python -m uvicorn backend.openai_adapter:app --host 0.0.0.0 --port 8001 --reload
```

服务将在 `http://localhost:8001` 启动。

### 第4步：配置OpenAI API Key

编辑 `examples/openai_example.py`，设置你的API Key：

```python
openai.api_key = "your-api-key-here"
```

### 第5步：运行示例

```bash
python examples/openai_example.py
```

## 使用方式

### 方式1：使用示例脚本（推荐新手）

直接运行提供的示例脚本：

```bash
python examples/openai_example.py
```

脚本会启动交互模式，你可以直接对话：

```
你: 帮我搜索关于函数的数学题
助手: 正在搜索... 找到20道题目
```

### 方式2：在你自己的代码中集成

```python
import openai
import requests
import json

# 1. 设置API Key
openai.api_key = "your-api-key"

# 2. 定义函数
functions = [
    {
        "name": "search_questions_by_keyword",
        "description": "搜索题目",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string"},
                "limit": {"type": "integer"}
            },
            "required": ["keyword"]
        }
    }
]

# 3. 调用OpenAI
response = openai.ChatCompletion.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "搜索函数相关题目"}],
    functions=functions,
    function_call="auto"
)

# 4. 处理函数调用
if response.choices[0].finish_reason == "function_call":
    function_call = response.choices[0].message.function_call
    arguments = json.loads(function_call.arguments)

    # 调用实际API
    result = requests.post(
        "http://localhost:8001/api/search-by-keyword",
        json=arguments
    ).json()

    # 将结果返回给OpenAI继续对话
    ...
```

完整代码参考：`examples/openai_example.py`

### 方式3：直接调用REST API

如果不想使用OpenAI Function Calling，也可以直接调用REST API：

```python
import requests

# 搜索题目
response = requests.post(
    "http://localhost:8001/api/search-by-keyword",
    json={
        "keyword": "函数",
        "subject": "数学",
        "limit": 10
    }
)

questions = response.json()
print(questions)

# 创建试卷
response = requests.post(
    "http://localhost:8001/api/create-paper",
    json={
        "paper_name": "测试试卷",
        "question_ids": ["12345", "12346"]
    }
)

result = response.json()
print(result)
```

## API端点列表

所有端点都在 `http://localhost:8001`：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/search-by-keyword` | POST | 关键词搜索 |
| `/api/search-by-knowledge` | POST | 知识点搜索 |
| `/api/filter-questions` | POST | 筛选题目 |
| `/api/question-info/{id}` | GET | 获取题目信息 |
| `/api/create-paper` | POST | 创建试卷 |
| `/api/papers` | GET | 获取试卷列表 |
| `/api/papers/{id}` | GET | 获取试卷详情 |
| `/docs` | GET | API文档 |

详细API文档访问：http://localhost:8001/docs

## 完整工作流程

```
1. 用户输入: "帮我搜索函数相关的数学题"
        ↓
2. OpenAI理解意图，决定调用 search_questions_by_keyword
        ↓
3. 你的代码调用 http://localhost:8001/api/search-by-keyword
        ↓
4. API调用Playwright爬虫搜索组卷网
        ↓
5. 返回题目编号和元数据
        ↓
6. 将结果返回给OpenAI
        ↓
7. OpenAI生成自然语言回复给用户
```

## 示例对话

**用户：** 帮我搜索关于"二次函数"的数学题，要10道

**系统调用：**
```json
{
  "function": "search_questions_by_keyword",
  "arguments": {
    "keyword": "二次函数",
    "subject": "数学",
    "limit": 10
  }
}
```

**API返回：**
```json
{
  "success": true,
  "count": 10,
  "questions": [
    {
      "question_id": "12345",
      "question_type": "选择题",
      "difficulty": "中等",
      ...
    }
  ]
}
```

**助手回复：** 我找到了10道关于二次函数的数学题...

---

**用户：** 把这些题目创建成一份试卷

**系统调用：**
```json
{
  "function": "create_paper",
  "arguments": {
    "paper_name": "二次函数练习",
    "question_ids": ["12345", "12346", ...]
  }
}
```

**助手回复：** 试卷创建成功！你可以在网页查看...

## 与Claude版本的区别

| 特性 | Claude版本 | OpenAI版本 |
|------|-----------|-----------|
| 协议 | MCP | Function Calling |
| 配置 | Claude Desktop配置文件 | 代码中设置API Key |
| 通信 | stdio | HTTP REST API |
| 部署 | MCP Server进程 | REST API服务器 |
| 使用 | Claude Desktop直接对话 | 需要编写代码调用 |

## 费用说明

### OpenAI API费用
- GPT-4: 约$0.03/1K tokens（输入）+ $0.06/1K tokens（输出）
- GPT-3.5-turbo: 约$0.001/1K tokens

### 本地服务
- 爬虫、数据库、API服务器都是本地运行，免费

## 故障排除

### 问题1：API无法启动

```bash
# 检查端口是否被占用
netstat -ano | findstr :8001

# 修改端口
# 编辑 backend/openai_adapter.py，修改 port=8001 为其他端口
```

### 问题2：OpenAI API调用失败

- 检查API Key是否正确
- 检查网络连接
- 查看OpenAI账户余额

### 问题3：函数调用失败

- 确认API服务器正在运行（http://localhost:8001）
- 检查函数定义与API端点是否匹配
- 查看API文档：http://localhost:8001/docs

### 问题4：爬虫无法获取题目

- 参考主文档的故障排除：`docs/TROUBLESHOOTING.md`
- 检查组卷网是否可访问
- 可能需要更新CSS选择器

## 开发调试

### 查看API日志

API会输出详细日志，包括：
- 收到的请求
- 爬虫执行情况
- 返回的结果

### 测试API

访问 http://localhost:8001/docs 使用Swagger UI测试API

### 调试OpenAI调用

在代码中添加日志：

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# 查看完整的OpenAI响应
print(json.dumps(response, indent=2))
```

## 生产部署建议

1. **使用环境变量管理API Key**
```python
import os
openai.api_key = os.getenv("OPENAI_API_KEY")
```

2. **添加错误处理和重试**
```python
from tenacity import retry, stop_after_attempt

@retry(stop=stop_after_attempt(3))
def call_openai_api(...):
    ...
```

3. **使用异步调用提高性能**
```python
import asyncio
import aiohttp

async def async_call_api(...):
    async with aiohttp.ClientSession() as session:
        ...
```

4. **添加请求限流**
```python
from ratelimit import limits

@limits(calls=10, period=60)  # 每分钟10次
def call_openai_api(...):
    ...
```

## 下一步

1. 运行示例脚本熟悉功能
2. 查看完整API文档
3. 根据需求修改和扩展
4. 部署到生产环境

## 相关文档

- `OPENAI_INTEGRATION.md` - 本文档
- `docs/API.md` - 完整API文档
- `examples/openai_example.py` - 示例代码
- `backend/openai_adapter.py` - API服务器源码

祝你使用愉快！🚀
