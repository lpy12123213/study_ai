"""
AI 对话服务 - 使用 OpenRouter API 实现工具调用
"""
import json
import asyncio
import httpx
from typing import List, Dict, Any, AsyncGenerator
from backend.config import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    MAIN_MODEL,
    MAIN_MODEL_TEMPERATURE,
    MAIN_MODEL_MAX_TOKENS,
    MAX_TOOL_ITERATIONS,
    API_TIMEOUT
)
from backend.subjects import DEFAULT_DIFFICULTY, normalize_difficulty, resolve_subject
from crawler.zujuan_crawler import ZujuanCrawler

# 系统提示词（带学科占位符）
SYSTEM_PROMPT_TEMPLATE = """你是一个智能组卷助手，具备完全自主的多轮工具调用能力。你可以连续执行多个工具调用，无需用户中间确认，直到完成整个组卷任务。

## 当前学科：{subject}

你当前正在为【{subject}】学科组卷，所有搜索和选题都应该针对这个学科。

## 核心能力
1. **search_questions** - 搜索题目（关键词、难度、题型）
   - 难度参数：'简单'、'中等'、'困难'
   - ⚠️ 重要：难度系数越小越难（困难 < 中等 < 简单）
   - 用户要求"简单题目"时使用难度='简单'，"困难题目"时使用难度='困难'
2. **batch_get_question_details** - 批量获取题目详情（最多10个）
3. **select_best_question** - 【子AI选题】从候选题目中智能选择最符合要求的一道
4. **create_paper** - 创建试卷
5. **get_papers** - 查看已有试卷

## 🔥 子AI选题功能（重要！）

当你需要从多道候选题目中选择最合适的一道时，**必须调用 select_best_question 工具**：

```
调用 select_best_question(
    question_ids=["id1", "id2", "id3"],  # 2-5个候选题目
    requirement="选题要求描述"
)
```

子AI会分析每道题目的内容、难度、知识点，返回最佳选择和理由。

### 每次调用工具后必须说明情况：
- 搜索后：说明找到了多少道题目
- 获取详情后：简述题目内容概况
- **子AI选题后：必须详细说明子AI的选择结果和理由**
- 创建试卷后：汇报成功信息

## 自主多轮执行模式

你可以在一次对话中**连续调用多个工具**，系统支持最多10轮工具调用。**每轮最多调用3个工具**，超过的会被截断。推荐执行流程：

```
搜索题目 → 获取详情 → 子AI选择最佳题目 → (重复多轮) → 创建试卷 → 汇报结果
```

### 执行策略

**第1轮**：搜索题目
- 调用 search_questions 搜索相关题目

**第2轮**：获取详情
- 调用 batch_get_question_details 获取候选题目详情

**第3轮**：子AI智能选题
- 调用 select_best_question，让子AI从候选中选择最符合要求的题目
- **说明子AI的选择结果：选了哪道题、选择理由是什么**

**第4轮+**：继续搜索其他题型/知识点，重复选题过程

**收集完所有题目后**：
- 整理并展示试卷细目表（题号、ID、知识点、题型、难度）
- 询问用户是否确认创建
- 等待用户回复

**用户同意后**：调用 create_paper 创建试卷并汇报结果

## 决策规则

1. **完整规划再执行**：收到组卷需求后，先完成所有题目的搜索和选题工作
2. **必用子AI选题**：每个题型/知识点都应该调用子AI来选择最佳题目
3. **每次说明情况**：工具调用后要告诉用户发生了什么
4. **智能补充**：如果搜索结果不足，自动尝试相关关键词
5. **⚠️ 先展示细目表，征求同意后再创建**：
   - 完成所有题目选择后，整理成表格形式的细目表
   - 细目表必须包含：题号、难度、知识点（可多个）、题目ID
   - 格式示例：
     ```
     【试卷细目表】
     题号 | 难度 | 知识点 | 题目ID
     1    | 容易 | 磁现象和磁场 | 12345678
     2    | 适中 | 机械振动、机械波 | 23456789
     ...
     ```
   - 展示后询问："以上是试卷细目表，是否确认创建？"
   - **只有在用户明确同意（如"确认"、"可以"、"好的"等）后才调用 create_paper 工具**
   - 如果用户不同意或要求修改，询问具体调整需求

## 典型场景示例

用户："帮我出一份关于{subject_topic}的测试，3道选择题"

执行过程：
1. 搜索{subject_topic}相关选择题（第1题） → "找到15道候选题目"
2. 获取前5道题目详情
3. 调用子AI选题 → "子AI选择了题目ID:xxx，理由：..."
4. 搜索{subject_topic}相关选择题（第2题） → "找到12道候选题目"
5. 获取详情并调用子AI选题 → "子AI选择了题目ID:yyy，理由：..."
6. 搜索{subject_topic}相关选择题（第3题） → "找到10道候选题目"
7. 获取详情并调用子AI选题 → "子AI选择了题目ID:zzz，理由：..."
8. **展示试卷细目表**：
   ```
   【试卷细目表】
   题号 | 难度 | 知识点 | 题目ID
   1    | 容易 | {subject_topic}的基本概念 | xxx
   2    | 适中 | {subject_topic}的应用 | yyy
   3    | 较难 | {subject_topic}的综合运用 | zzz
   ```
9. **询问用户确认** → "以上是试卷细目表，是否确认创建？"
10. **等待用户回复**
11. 如果用户同意（"确认"/"可以"/"好的"）→ 创建试卷 → "已创建试卷《{subject_topic}测试》"
12. 如果用户不同意 → 询问需要调整哪些题目

注意：题干中的[公式:<svg...>]是数学公式，子AI能够识别这些SVG矢量图中的数学符号。"""

def get_system_prompt(subject: str) -> str:
    """根据学科生成系统提示词"""
    # 获取学科相关的示例话题
    topic_map = {
        "高中数学": "函数",
        "高中语文": "古诗词鉴赏",
        "高中英语": "阅读理解",
        "高中物理": "力学",
        "高中化学": "化学反应",
        "高中生物": "细胞",
        "高中政治": "哲学",
        "高中历史": "近代史",
        "高中地理": "自然地理",
        "初中数学": "方程",
        "初中语文": "现代文阅读",
        "初中英语": "语法",
        "初中物理": "电学",
        "初中化学": "元素化合物",
        "初中生物": "生态系统",
        "初中道德与法治": "法律常识",
        "初中历史": "中国古代史",
        "初中地理": "中国地理",
        "小学数学": "四则运算",
        "小学语文": "阅读理解",
        "小学英语": "单词",
    }
    topic = topic_map.get(subject, "相关知识点")
    return SYSTEM_PROMPT_TEMPLATE.format(subject=subject, subject_topic=topic)

# 工具定义
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_questions",
            "description": "搜索题目。根据关键词、难度、题型等条件搜索组卷网上的题目。返回题目ID列表和基本信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词，如'函数'、'导数'、'三角函数'等"
                    },
                    "edu_level": {
                        "type": "string",
                        "enum": ["小学", "初中", "高中", ""],
                        "description": "学段筛选，可选：小学/初中/高中（指定后将严格校验）",
                        "default": ""
                    },
                    "difficulty": {
                        "type": "string",
                        "enum": ["简单", "中等", "困难", ""],
                        "description": "难度等级筛选，可选。重要：难度系数越小越难（困难 < 中等 < 简单）。如果用户要求简单题目，使用'简单'；困难题目使用'困难'"
                    },
                    "question_type": {
                        "type": "string",
                        "description": "题型，如'选择题'、'填空题'、'解答题'等，可选"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回题目数量，默认10",
                        "default": 10
                    }
                },
                "required": ["keyword"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_paper",
            "description": "创建试卷。将选定的题目保存为一份试卷。",
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
                        "description": "题目ID列表"
                    }
                },
                "required": ["paper_name", "question_ids"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_papers",
            "description": "获取已创建的试卷列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制，默认10",
                        "default": 10
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_question_detail",
            "description": "根据题目ID获取题目详情。用于逐一判断题目是否符合组卷需求。返回题目的完整信息包括题干、选项、答案、解析等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question_id": {
                        "type": "string",
                        "description": "题目ID，如 '12345678'"
                    }
                },
                "required": ["question_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "batch_get_question_details",
            "description": "批量获取多个题目的详情。用于一次性获取多道题目进行筛选判断。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "题目ID列表，最多10个"
                    }
                },
                "required": ["question_ids"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "select_best_question",
            "description": "【子AI选题】从多个候选题目中智能选择最符合要求的一道。会调用子AI分析题目内容、难度、知识点，返回最佳选择和选择理由。每次选题都应该使用这个工具让子AI来决策。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "候选题目ID列表（2-5个）"
                    },
                    "requirement": {
                        "type": "string",
                        "description": "选题要求描述，如'需要一道考查函数单调性的中等难度选择题'"
                    }
                },
                "required": ["question_ids", "requirement"]
            }
        }
    }
]


class ChatService:
    def __init__(self):
        self.crawler = None
        self.current_subject = "高中数学"
        self.question_cache = {}  # 缓存题目详情 {question_id: question_data}

    async def _get_crawler(self, subject: str = None):
        """获取爬虫实例，支持学科切换"""
        subject = resolve_subject(subject or self.current_subject, strict=True)
        self.current_subject = subject
        if self.crawler is None:
            self.crawler = ZujuanCrawler(subject=subject)
            await self.crawler.initialize()
        elif self.crawler.subject != subject:
            # 切换学科
            self.crawler.set_subject(subject)
        return self.crawler

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行工具调用"""
        try:
            if tool_name == "search_questions":
                crawler = await self._get_crawler()
                edu_level = (arguments.get("edu_level") or "").strip()
                difficulty = normalize_difficulty(
                    arguments.get("difficulty") or DEFAULT_DIFFICULTY,
                    strict=True,
                )
                result = await crawler.search_by_keyword(
                    keyword=arguments.get("keyword", ""),
                    edu_level=edu_level,
                    difficulty=difficulty,
                    question_type=arguments.get("question_type", ""),
                    limit=arguments.get("limit", 10),
                    require_difficulty=True,
                    strict_subject=True,
                )
                if edu_level:
                    result["applied_edu_level"] = edu_level
                return result

            elif tool_name == "create_paper":
                from database.models import save_paper
                questions = [{"question_id": qid} for qid in arguments.get("question_ids", [])]
                paper_id = await save_paper(
                    paper_name=arguments.get("paper_name", "未命名试卷"),
                    questions=questions
                )
                return {
                    "success": True,
                    "paper_id": paper_id,
                    "message": f"试卷创建成功，ID: {paper_id}"
                }

            elif tool_name == "get_papers":
                from database.models import list_papers
                papers = await list_papers(limit=arguments.get("limit", 10))
                return {
                    "success": True,
                    "papers": papers,
                    "count": len(papers)
                }

            elif tool_name == "get_question_detail":
                crawler = await self._get_crawler()
                result = await crawler.get_question_detail(
                    question_id=arguments.get("question_id", "")
                )
                return result

            elif tool_name == "batch_get_question_details":
                crawler = await self._get_crawler()
                result = await crawler.batch_get_question_details(
                    question_ids=arguments.get("question_ids", [])
                )
                # 缓存获取到的题目详情
                for q in result.get("questions", []):
                    qid = q.get("question_id")
                    if qid:
                        self.question_cache[qid] = q
                return result

            elif tool_name == "select_best_question":
                # 子AI选题功能
                from mcp_server.sub_ai_selector import select_best_question as sub_ai_select

                question_ids = arguments.get("question_ids", [])[:5]
                requirement = arguments.get("requirement", "")

                # 优先从缓存获取题目详情
                questions = []
                missing_ids = []
                for qid in question_ids:
                    if qid in self.question_cache:
                        questions.append(self.question_cache[qid])
                    else:
                        missing_ids.append(qid)

                # 如果有缺失的题目，再去获取
                if missing_ids:
                    crawler = await self._get_crawler()
                    details_result = await crawler.batch_get_question_details(missing_ids)
                    for q in details_result.get("questions", []):
                        qid = q.get("question_id")
                        if qid:
                            self.question_cache[qid] = q
                            questions.append(q)

                if not questions:
                    return {"success": False, "error": "无法获取候选题目详情"}

                # 调用子AI选择最佳题目（传递完整题目信息，包括题干）
                result = await sub_ai_select(
                    questions=questions,
                    requirement=requirement
                )

                # 添加说明信息
                if result.get("success"):
                    result["message"] = f"子AI已从{len(questions)}道候选题目中选择了最符合要求的题目"

                return result

            else:
                return {"success": False, "error": f"未知工具: {tool_name}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _generate_fallback_response(self, tool_results: List[Dict]) -> str:
        """当API返回空内容时，根据工具结果生成回复"""
        if not tool_results:
            return "操作已完成。"

        responses = []
        for tr in tool_results:
            try:
                result = json.loads(tr.get("content", "{}"))
                tool_id = tr.get("tool_call_id", "")

                # search_questions 结果
                if "questions" in result:
                    questions = result.get("questions", [])
                    total = result.get("total", len(questions))
                    if questions:
                        responses.append(f"搜索到 {total} 道题目，已展示 {len(questions)} 道。")
                    else:
                        responses.append("未找到符合条件的题目，请尝试其他关键词。")

                # get_question_detail 结果
                elif "stem" in result:
                    responses.append("已获取题目详情。")

                # batch_get_question_details 结果
                elif "questions" in result and "count" in result:
                    count = result.get("count", 0)
                    responses.append(f"已获取 {count} 道题目的详情。")

                # create_paper 结果
                elif "paper_id" in result:
                    paper_id = result.get("paper_id")
                    responses.append(f"试卷创建成功！试卷ID: {paper_id}")

                # get_papers 结果
                elif "papers" in result:
                    count = result.get("count", 0)
                    responses.append(f"找到 {count} 份已保存的试卷。")

                # 错误情况
                elif result.get("success") == False:
                    error = result.get("error", "未知错误")
                    responses.append(f"操作失败: {error}")

            except json.JSONDecodeError:
                pass

        if responses:
            return "\n\n".join(responses) + "\n\n请查看上方的详细结果。如需继续操作，请告诉我。"
        else:
            return "操作已完成，请查看上方的工具执行结果。"

    def _build_messages(self, history: List[Dict], user_message: str, subject: str = "高中数学") -> List[Dict]:
        """构建消息列表"""
        system_prompt = get_system_prompt(subject)
        messages = [{"role": "system", "content": system_prompt}]

        # 添加历史消息
        for msg in history:
            if msg["role"] == "user":
                messages.append({"role": "user", "content": msg["content"]})
            elif msg["role"] == "assistant":
                msg_data = {"role": "assistant", "content": msg["content"]}
                if msg.get("tool_calls"):
                    msg_data["tool_calls"] = msg["tool_calls"]
                messages.append(msg_data)
            elif msg["role"] == "tool":
                messages.append({
                    "role": "tool",
                    "tool_call_id": msg.get("tool_call_id", ""),
                    "content": msg["content"]
                })

        # 添加当前用户消息
        messages.append({"role": "user", "content": user_message})
        return messages

    async def _call_api(self, client: httpx.AsyncClient, messages: List[Dict], include_tools: bool = True, max_retries: int = 3) -> Dict:
        """调用 OpenRouter API，带重试机制"""
        last_error = None
        for attempt in range(max_retries):
            try:
                payload = {
                    "model": MAIN_MODEL,
                    "messages": messages,
                    "max_tokens": MAIN_MODEL_MAX_TOKENS,
                    "temperature": MAIN_MODEL_TEMPERATURE
                }
                if include_tools:
                    payload["tools"] = TOOLS
                    payload["tool_choice"] = "auto"

                response = await client.post(
                    f"{OPENROUTER_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "http://localhost:8000",
                        "X-Title": "Exam Paper Assistant"
                    },
                    json=payload
                )

                if response.status_code == 200:
                    return {"success": True, "data": response.json()}
                else:
                    last_error = f"API错误: {response.status_code}"
            except httpx.ConnectError as e:
                last_error = f"连接失败: {str(e)}"
            except httpx.RemoteProtocolError as e:
                last_error = f"协议错误: {str(e)}"
            except Exception as e:
                last_error = f"请求错误: {str(e)}"

            # 等待后重试
            if attempt < max_retries - 1:
                await asyncio.sleep(1 * (attempt + 1))

        return {"success": False, "error": last_error}

    async def _call_api_streaming(self, client: httpx.AsyncClient, messages: List[Dict]):
        """流式调用 OpenRouter API，用于最终文本回复"""
        payload = {
            "model": MAIN_MODEL,
            "messages": messages,
            "max_tokens": MAIN_MODEL_MAX_TOKENS,
            "temperature": MAIN_MODEL_TEMPERATURE,
            "stream": True
        }

        try:
            async with client.stream(
                "POST",
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:8000",
                    "X-Title": "Exam Paper Assistant"
                },
                json=payload
            ) as response:
                if response.status_code != 200:
                    yield {"type": "error", "content": f"API错误: {response.status_code}"}
                    return

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield {"type": "text_delta", "content": content}
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            yield {"type": "error", "content": f"流式请求错误: {str(e)}"}

    async def chat(self, history: List[Dict], user_message: str, subject: str = "高中数学") -> AsyncGenerator[Dict, None]:
        """
        处理对话，支持多轮工具调用
        AI可以连续调用多个工具直到完成任务
        返回生成器，逐步返回响应
        """
        # 更新当前学科
        self.current_subject = subject

        if not OPENROUTER_API_KEY:
            yield {
                "type": "error",
                "content": "未配置 OpenRouter API Key"
            }
            return

        messages = self._build_messages(history, user_message, subject=subject)
        iteration = 0
        all_tool_results = []  # 收集所有工具结果用于fallback

        async with httpx.AsyncClient(timeout=httpx.Timeout(API_TIMEOUT, connect=30.0)) as client:
            while iteration < MAX_TOOL_ITERATIONS:
                iteration += 1

                # 通知前端当前是第几轮
                if iteration > 1:
                    yield {
                        "type": "iteration",
                        "round": iteration,
                        "message": f"AI 正在进行第 {iteration} 轮操作..."
                    }

                # 调用API（始终包含工具，让AI自主决定是否使用）
                result = await self._call_api(client, messages, include_tools=True)

                if not result["success"]:
                    yield {
                        "type": "error",
                        "content": result["error"]
                    }
                    return

                data = result["data"]
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})
                finish_reason = choice.get("finish_reason", "")

                # 检查是否有工具调用
                tool_calls = message.get("tool_calls")

                if tool_calls:
                    # 限制每轮最多执行3个工具调用
                    if len(tool_calls) > 3:
                        tool_calls = tool_calls[:3]
                    
                    # 返回助手消息（包含工具调用意图）
                    assistant_content = message.get("content") or ""
                    yield {
                        "type": "assistant",
                        "content": assistant_content,
                        "tool_calls": tool_calls,
                        "iteration": iteration
                    }

                    # 执行每个工具调用（最多3个）
                    tool_results = []
                    for tool_call in tool_calls:
                        tool_name = tool_call["function"]["name"]
                        try:
                            tool_args = json.loads(tool_call["function"]["arguments"])
                        except json.JSONDecodeError:
                            tool_args = {}
                        tool_id = tool_call["id"]

                        # 通知前端工具开始执行
                        yield {
                            "type": "tool_start",
                            "tool_call_id": tool_id,
                            "tool_name": tool_name,
                            "arguments": tool_args,
                            "iteration": iteration
                        }

                        # 执行工具
                        tool_result = await self.execute_tool(tool_name, tool_args)

                        # 通知前端工具执行完成
                        yield {
                            "type": "tool_result",
                            "tool_call_id": tool_id,
                            "tool_name": tool_name,
                            "result": tool_result,
                            "iteration": iteration
                        }

                        tool_result_msg = {
                            "tool_call_id": tool_id,
                            "role": "tool",
                            "content": json.dumps(tool_result, ensure_ascii=False)
                        }
                        tool_results.append(tool_result_msg)
                        all_tool_results.append(tool_result_msg)

                    # 将助手消息和工具结果添加到消息列表，继续下一轮
                    messages.append(message)
                    messages.extend(tool_results)

                    # 继续循环，让AI决定下一步
                    continue

                else:
                    # 没有工具调用，AI已完成任务
                    # 如果之前有工具调用，使用流式输出最终回复
                    if all_tool_results:
                        # 通知前端开始流式输出
                        yield {
                            "type": "stream_start",
                            "iteration": iteration
                        }

                        # 使用流式API获取最终回复
                        final_content = ""
                        async for chunk in self._call_api_streaming(client, messages):
                            if chunk["type"] == "text_delta":
                                final_content += chunk["content"]
                                yield chunk
                            elif chunk["type"] == "error":
                                yield chunk
                                return

                        # 如果流式输出为空，使用fallback
                        if not final_content:
                            final_content = self._generate_fallback_response(all_tool_results)
                            yield {"type": "text_delta", "content": final_content}

                        yield {
                            "type": "assistant_final",
                            "content": final_content,
                            "total_iterations": iteration
                        }
                    else:
                        # 没有工具调用，直接返回（简单对话场景）
                        final_content = message.get("content", "")

                        # 也使用流式输出
                        if final_content:
                            yield {"type": "stream_start", "iteration": iteration}
                            # 模拟流式输出（分段发送）
                            chunk_size = 10
                            for i in range(0, len(final_content), chunk_size):
                                yield {"type": "text_delta", "content": final_content[i:i+chunk_size]}
                                await asyncio.sleep(0.02)  # 小延迟模拟打字效果
                            yield {
                                "type": "assistant_final",
                                "content": final_content,
                                "total_iterations": iteration
                            }
                        else:
                            yield {
                                "type": "assistant_final",
                                "content": "",
                                "total_iterations": iteration
                            }
                    return

            # 达到最大轮数限制
            yield {
                "type": "assistant_final",
                "content": f"已完成 {MAX_TOOL_ITERATIONS} 轮操作。" + self._generate_fallback_response(all_tool_results),
                "total_iterations": iteration,
                "max_reached": True
            }


# 单例
chat_service = ChatService()
