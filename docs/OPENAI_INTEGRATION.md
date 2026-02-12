# OpenAI 集成指南

通过 OpenAI Function Calling 使用组卷助手功能。

## 架构对比

### Claude 版本（MCP）
```
Claude AI ←→ MCP Server ←→ Crawler ←→ 组卷网
                 ↓
             Database
```

### OpenAI 版本（Function Calling）
```
OpenAI ←→ Function Calling ←→ REST API ←→ Crawler ←→ 组卷网
                                    ↓
                                Database
```

## 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt
pip install openai
python -m playwright install chromium
```

### 2. 启动适配器服务
```bash
python -m uvicorn backend.openai_adapter:app --host 0.0.0.0 --port 8001 --reload
```

### 3. 配置 API Key
```python
import os
openai.api_key = os.getenv("OPENAI_API_KEY", "your-key-here")
```

## Function 定义

```python
functions = [
    {
        "name": "search_questions_by_keyword",
        "description": "通过关键词搜索题目",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词"},
                "subject": {"type": "string", "description": "学科筛选（可选）"},
                "limit": {"type": "integer", "default": 20, "description": "结果数量限制"}
            },
            "required": ["keyword"]
        }
    },
    {
        "name": "search_questions_by_knowledge",
        "description": "通过知识点搜索题目",
        "parameters": {
            "type": "object",
            "properties": {
                "knowledge_point": {"type": "string", "description": "知识点名称"},
                "subject": {"type": "string", "description": "学科"},
                "limit": {"type": "integer", "default": 20}
            },
            "required": ["knowledge_point", "subject"]
        }
    },
    {
        "name": "filter_questions",
        "description": "根据条件筛选题目",
        "parameters": {
            "type": "object",
            "properties": {
                "question_ids": {"type": "array", "items": {"type": "string"}},
                "difficulty": {"type": "string", "enum": ["简单", "中等", "困难"]},
                "question_type": {"type": "string"},
                "limit": {"type": "integer", "default": 10}
            },
            "required": ["question_ids"]
        }
    },
    {
        "name": "get_question_info",
        "description": "获取题目基本信息",
        "parameters": {
            "type": "object",
            "properties": {
                "question_id": {"type": "string"}
            },
            "required": ["question_id"]
        }
    },
    {
        "name": "create_paper",
        "description": "创建试卷",
        "parameters": {
            "type": "object",
            "properties": {
                "paper_name": {"type": "string"},
                "question_ids": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["paper_name", "question_ids"]
        }
    }
]
```

## 使用示例

### 完整对话流程
```python
import openai
import requests
import json

def call_function(function_name, arguments):
    """调用实际的API端点"""
    base_url = "http://localhost:8001"
    
    endpoints = {
        "search_questions_by_keyword": "/api/search-by-keyword",
        "search_questions_by_knowledge": "/api/search-by-knowledge",
        "filter_questions": "/api/filter-questions",
        "get_question_info": "/api/question-info/{question_id}",
        "create_paper": "/api/create-paper"
    }
    
    if function_name == "get_question_info":
        response = requests.get(f"{base_url}{endpoints[function_name].format(**arguments)}")
    else:
        response = requests.post(f"{base_url}{endpoints[function_name]}", json=arguments)
    
    return response.json()

def chat_with_functions(user_message):
    messages = [{"role": "user", "content": user_message}]
    
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=messages,
        functions=functions,
        function_call="auto"
    )
    
    # 处理函数调用
    while response.choices[0].finish_reason == "function_call":
        function_call = response.choices[0].message.function_call
        function_name = function_call.name
        arguments = json.loads(function_call.arguments)
        
        # 调用实际函数
        function_result = call_function(function_name, arguments)
        
        # 将结果返回给AI
        messages.append({
            "role": "function",
            "name": function_name,
            "content": json.dumps(function_result, ensure_ascii=False)
        })
        
        # 继续对话
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=messages,
            functions=functions,
            function_call="auto"
        )
    
    return response.choices[0].message.content
```

### 直接调用 REST API
```python
import requests

# 搜索题目
response = requests.post(
    "http://localhost:8001/api/search-by-keyword",
    json={"keyword": "函数", "subject": "数学", "limit": 10}
)

# 创建试卷
response = requests.post(
    "http://localhost:8001/api/create-paper",
    json={"paper_name": "测试试卷", "question_ids": ["12345", "12346"]}
)
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/search-by-keyword` | POST | 关键词搜索 |
| `/api/search-by-knowledge` | POST | 知识点搜索 |
| `/api/filter-questions` | POST | 筛选题目 |
| `/api/question-info/{id}` | GET | 获取题目信息 |
| `/api/create-paper` | POST | 创建试卷 |
| `/api/papers` | GET | 获取试卷列表 |
| `/docs` | GET | API文档 |

访问 http://localhost:8001/docs 查看完整 API 文档。

## 高级功能

### 筛选参数
搜索接口支持额外筛选参数：
- `difficulty`: 难度筛选
- `year`: 年份筛选
- `source_contains`: 来源筛选
- `difficulty_value_min/max`: 难度系数范围
- `learn_grade/learn_grade_id`: 年级筛选
- `textbook_version`: 教材版本
- `dedup_by_stem`: 去重
- `min_quality_score`: 最低质量分

### 组卷蓝图
```python
# 获取可用筛选项
filters = requests.post("http://localhost:8001/api/available-filters", json={"subject": "高中数学"})

# 按蓝图批量组装
blueprint = {
    "subject": "高中数学",
    "slots": [
        {"type": "选择题", "difficulty": "简单", "count": 5},
        {"type": "填空题", "difficulty": "中等", "count": 3}
    ]
}
result = requests.post("http://localhost:8001/api/compose-blueprint", json=blueprint)
```

## 故障排除

### 常见问题
1. **端口冲突**：修改 `backend/openai_adapter.py` 中的端口
2. **API Key 错误**：检查环境变量或直接设置
3. **函数调用失败**：确认服务运行在 http://localhost:8001
4. **爬虫问题**：参考 `docs/TROUBLESHOOTING.md`

### 调试技巧
```python
# 查看完整响应
print(json.dumps(response, indent=2))

# 测试 API
curl -X POST http://localhost:8001/api/search-by-keyword \
  -H "Content-Type: application/json" \
  -d '{"keyword":"函数","limit":5}'
```

## 生产部署建议

1. 使用环境变量管理 API Key
2. 添加错误处理和重试机制
3. 使用异步调用提高性能
4. 添加请求限流

## 与 Claude 版本区别

| 特性 | Claude | OpenAI |
|------|--------|--------|
| 协议 | MCP | Function Calling |
| 配置 | Claude Desktop | 代码中设置 |
| 通信 | stdio | HTTP REST API |
| 使用 | 直接对话 | 需要编码调用 |
