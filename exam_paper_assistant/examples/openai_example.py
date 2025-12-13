"""
OpenAI Codex 使用示例
展示如何在Python中使用OpenAI API调用组卷助手
"""
import openai
import requests
import json

# 设置OpenAI API Key
openai.api_key = "your-api-key-here"

# API基础URL
API_BASE_URL = "http://localhost:8001"


# OpenAI Function定义
FUNCTIONS = [
    {
        "name": "search_questions_by_keyword",
        "description": "通过关键词搜索题目。返回题目编号列表和元数据。",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词"
                },
                "subject": {
                    "type": "string",
                    "description": "学科筛选（可选）"
                },
                "limit": {
                    "type": "integer",
                    "description": "返回结果数量限制",
                    "default": 20
                }
            },
            "required": ["keyword"]
        }
    },
    {
        "name": "create_paper",
        "description": "创建试卷",
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


def call_api_function(function_name: str, arguments: dict) -> dict:
    """调用实际的API端点"""

    if function_name == "search_questions_by_keyword":
        response = requests.post(
            f"{API_BASE_URL}/api/search-by-keyword",
            json=arguments
        )
        return response.json()

    elif function_name == "create_paper":
        response = requests.post(
            f"{API_BASE_URL}/api/create-paper",
            json=arguments
        )
        return response.json()

    return {"error": f"Unknown function: {function_name}"}


def chat_with_assistant(user_message: str) -> str:
    """与OpenAI助手对话，支持函数调用"""

    messages = [
        {
            "role": "system",
            "content": """你是一个智能组卷助手。你可以帮助用户从组卷网搜索题目。

注意：
1. 只存储题目编号，不存储题目内容
2. 引导用户到组卷网官网下载题目
3. 提供题目的元数据信息（题型、难度、知识点）"""
        },
        {
            "role": "user",
            "content": user_message
        }
    ]

    print(f"用户: {user_message}\n")

    # 第一次调用OpenAI
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=messages,
        functions=FUNCTIONS,
        function_call="auto",
        temperature=0.7
    )

    # 处理函数调用循环
    max_iterations = 5
    iteration = 0

    while iteration < max_iterations:
        choice = response.choices[0]

        if choice.finish_reason == "function_call":
            # AI想要调用函数
            function_call = choice.message.function_call
            function_name = function_call.name
            arguments = json.loads(function_call.arguments)

            print(f"🔧 调用函数: {function_name}")
            print(f"   参数: {json.dumps(arguments, ensure_ascii=False)}\n")

            # 调用实际API
            try:
                function_result = call_api_function(function_name, arguments)
                print(f"✅ 函数返回: {json.dumps(function_result, ensure_ascii=False, indent=2)}\n")
            except Exception as e:
                function_result = {"error": str(e)}
                print(f"❌ 函数调用失败: {e}\n")

            # 将函数调用和结果添加到消息历史
            messages.append({
                "role": "assistant",
                "content": None,
                "function_call": {
                    "name": function_name,
                    "arguments": function_call.arguments
                }
            })

            messages.append({
                "role": "function",
                "name": function_name,
                "content": json.dumps(function_result, ensure_ascii=False)
            })

            # 继续对话
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=messages,
                functions=FUNCTIONS,
                function_call="auto",
                temperature=0.7
            )

        elif choice.finish_reason == "stop":
            # AI完成回答
            assistant_message = choice.message.content
            print(f"助手: {assistant_message}\n")
            return assistant_message

        else:
            break

        iteration += 1

    return "对话结束"


# 使用示例
if __name__ == "__main__":
    print("="*60)
    print("智能组卷助手 - OpenAI Codex版本")
    print("="*60)
    print()

    # 示例1：简单搜索
    print("【示例1：搜索题目】")
    print("-"*60)
    chat_with_assistant("帮我搜索关于'二次函数'的数学题，要5道")

    print("\n" + "="*60 + "\n")

    # 示例2：创建试卷
    print("【示例2：创建试卷】")
    print("-"*60)
    chat_with_assistant("""
    帮我创建一份测试卷：
    1. 先搜索关于'函数'的数学题，要10道
    2. 创建一份名为'高一数学函数测试'的试卷
    """)

    print("\n" + "="*60 + "\n")

    # 交互模式
    print("【交互模式】")
    print("-"*60)
    print("输入 'quit' 退出\n")

    while True:
        try:
            user_input = input("你: ").strip()
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("再见！")
                break

            if not user_input:
                continue

            chat_with_assistant(user_input)
            print()

        except KeyboardInterrupt:
            print("\n\n再见！")
            break
        except Exception as e:
            print(f"错误: {e}\n")
