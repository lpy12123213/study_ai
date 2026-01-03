# OpenAI Codex Function Definitions

这些是OpenAI Function Calling的函数定义，在使用OpenAI API时需要提供这些定义。

## 使用方法

在你的OpenAI API调用中添加这些functions：

```python
import openai

functions = [
    {
        "name": "search_questions_by_keyword",
        "description": "通过关键词搜索题目。返回题目编号列表和元数据。",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词，例如：函数、三角形、化学平衡"
                },
                "subject": {
                    "type": "string",
                    "description": "学科筛选，例如：数学、物理、化学。可选。"
                },
                "limit": {
                    "type": "integer",
                    "description": "返回结果数量限制，默认20",
                    "default": 20
                }
            },
            "required": ["keyword"]
        }
    },
    {
        "name": "search_questions_by_knowledge",
        "description": "通过知识点搜索题目。返回题目编号列表。",
        "parameters": {
            "type": "object",
            "properties": {
                "knowledge_point": {
                    "type": "string",
                    "description": "知识点名称"
                },
                "subject": {
                    "type": "string",
                    "description": "学科，例如：数学、物理"
                },
                "limit": {
                    "type": "integer",
                    "description": "返回结果数量限制，默认20",
                    "default": 20
                }
            },
            "required": ["knowledge_point", "subject"]
        }
    },
    {
        "name": "filter_questions",
        "description": "根据条件筛选题目（难度、题型等）",
        "parameters": {
            "type": "object",
            "properties": {
                "question_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "题目编号列表"
                },
                "difficulty": {
                    "type": "string",
                    "description": "难度等级（简单、中等、困难）",
                    "enum": ["简单", "中等", "困难", ""]
                },
                "question_type": {
                    "type": "string",
                    "description": "题型（选择题、填空题、解答题等）"
                },
                "limit": {
                    "type": "integer",
                    "description": "返回结果数量限制，默认10",
                    "default": 10
                }
            },
            "required": ["question_ids"]
        }
    },
    {
        "name": "get_question_info",
        "description": "获取题目基本信息（不包含题目内容，只有元数据）",
        "parameters": {
            "type": "object",
            "properties": {
                "question_id": {
                    "type": "string",
                    "description": "题目编号"
                }
            },
            "required": ["question_id"]
        }
    },
    {
        "name": "create_paper",
        "description": "创建试卷（保存题目编号组合）",
        "parameters": {
            "type": "object",
            "properties": {
                "paper_name": {
                    "type": "string",
                    "description": "试卷名称"
                },
                "question_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "题目编号列表"
                }
            },
            "required": ["paper_name", "question_ids"]
        }
    }
]

# 在调用OpenAI API时使用
response = openai.ChatCompletion.create(
    model="gpt-4",
    messages=[
        {"role": "user", "content": "帮我搜索关于函数的数学题"}
    ],
    functions=functions,
    function_call="auto"
)
```

## Function调用实现

当OpenAI返回function_call时，需要实际调用API：

```python
import requests

def call_function(function_name, arguments):
    """调用实际的API端点"""
    base_url = "http://localhost:8001"

    if function_name == "search_questions_by_keyword":
        response = requests.post(
            f"{base_url}/api/search-by-keyword",
            json=arguments
        )
        return response.json()

    elif function_name == "search_questions_by_knowledge":
        response = requests.post(
            f"{base_url}/api/search-by-knowledge",
            json=arguments
        )
        return response.json()

    elif function_name == "filter_questions":
        response = requests.post(
            f"{base_url}/api/filter-questions",
            json=arguments
        )
        return response.json()

    elif function_name == "get_question_info":
        question_id = arguments["question_id"]
        response = requests.get(
            f"{base_url}/api/question-info/{question_id}"
        )
        return response.json()

    elif function_name == "create_paper":
        response = requests.post(
            f"{base_url}/api/create-paper",
            json=arguments
        )
        return response.json()

    return {"error": "Unknown function"}


# 完整的对话流程
def chat_with_functions(user_message):
    messages = [{"role": "user", "content": user_message}]

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=messages,
        functions=functions,
        function_call="auto"
    )

    # 如果AI要调用函数
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

## 启动服务

```bash
# 启动OpenAI适配器API（端口8001）
python -m uvicorn backend.openai_adapter:app --host 0.0.0.0 --port 8001 --reload

# API将在 http://localhost:8001 运行
# API文档在 http://localhost:8001/docs
```

## 测试API

```bash
# 测试关键词搜索
curl -X POST http://localhost:8001/api/search-by-keyword \
  -H "Content-Type: application/json" \
  -d '{"keyword":"函数","limit":5}'

# 测试关键词搜索（可选过滤：年份/来源/难度系数范围等）
curl -X POST http://localhost:8001/api/search-by-keyword \
  -H "Content-Type: application/json" \
  -d '{"keyword":"函数","limit":10,"difficulty":"中等","year":2024,"source_contains":"高考","difficulty_value_min":0.4,"difficulty_value_max":0.8}'

# 测试创建试卷
curl -X POST http://localhost:8001/api/create-paper \
  -H "Content-Type: application/json" \
  -d '{"paper_name":"测试试卷","question_ids":["12345","12346"]}'
```

## 新增：筛选项与组卷蓝图接口

OpenAI 适配器（`backend/openai_adapter.py`）已新增并扩展以下能力：

- 同样，主后端（`backend/app.py`，默认端口 `8000`）也暴露 `POST /api/available-filters` 与 `POST /api/compose-blueprint`，便于 Web 前端直接调用（Vite 开发代理 `/api` -> `8000`）。
- `POST /api/available-filters`：获取当前学科可用筛选项（年级/教材版本/题型等）
- `POST /api/compose-blueprint`：按“组卷蓝图”批量检索并组装题目 ID 列表
- `POST /api/search-by-keyword` / `POST /api/search-by-knowledge`：新增支持 `learn_grade/learn_grade_id`、`textbook_version`、`elective_mode`、`dedup_by_stem`、`min_quality_score` 等参数

字段说明与示例见：`docs/SEARCH_FILTERS_AND_BLUEPRINTS.md`
