"""
MCP 服务 - 为 AI 提供题目搜索与组卷工具
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

sys.path.append(str(Path(__file__).parent.parent))
from crawler.zujuan_crawler import ZujuanCrawler  # noqa: E402
from mcp_server.sub_ai_selector import select_best_question  # noqa: E402
from backend.subjects import get_all_subjects, get_subject_config, SUBJECTS  # noqa: E402


class ExamPaperMCPServer:
    def __init__(self):
        self.server = Server("exam-paper-assistant")
        self.crawler: Optional[ZujuanCrawler] = None
        self.current_subject = "高中数学"  # 当前学科
        self._register_handlers()

    def _register_handlers(self):
        """注册 MCP 工具处理器"""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="search_questions_by_keyword",
                    description="""【推荐】通过关键词搜索题目，直接返回完整题目信息。
返回内容包括：题号、题型、难度(含数值)、知识点列表、来源、日期、题干内容。
搜索结果已包含题干，无需再调用 get_question_details。
公式显示为 [公式:xxx.png] 格式。""",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "keyword": {"type": "string", "description": "搜索关键词"},
                            "subject": {
                                "type": "string",
                                "description": "学科全名（如：高中数学、初中物理、小学语文），会自动切换学科",
                                "default": "",
                            },
                            "difficulty": {
                                "type": "string",
                                "description": "难度（可选：简单/中等/困难）",
                                "default": "",
                            },
                            "question_type": {
                                "type": "string",
                                "description": "题型（选择题/填空题/解答题等）",
                                "default": "",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "返回结果数量限制",
                                "default": 10,
                            },
                            "max_pages": {
                                "type": "integer",
                                "description": "最多翻页数（默认 3 页）",
                                "default": 3,
                            },
                        },
                        "required": ["keyword"],
                    },
                ),
                Tool(
                    name="search_questions_by_knowledge",
                    description="""【推荐】通过知识点搜索题目，直接返回完整题目信息。
返回内容包括：题号、题型、难度(含数值)、知识点列表、来源、日期、题干内容。
搜索结果已包含题干，无需再调用 get_question_details。""",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "knowledge_point": {
                                "type": "string",
                                "description": "知识点名称",
                            },
                            "subject": {
                                "type": "string",
                                "description": "学科全名（如：高中数学、初中物理）",
                            },
                            "difficulty": {
                                "type": "string",
                                "description": "难度（可选：简单/中等/困难）",
                                "default": "",
                            },
                            "question_type": {
                                "type": "string",
                                "description": "题型（选择题/填空题/解答题等）",
                                "default": "",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "返回结果数量限制",
                                "default": 10,
                            },
                            "max_pages": {
                                "type": "integer",
                                "description": "最多翻页数（默认 3 页）",
                                "default": 3,
                            },
                        },
                        "required": ["knowledge_point", "subject"],
                    },
                ),
                Tool(
                    name="filter_questions",
                    description="根据已搜索的题目列表进行二次过滤（难度、题型等）。",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "question_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "题目编号列表",
                            },
                            "difficulty": {
                                "type": "string",
                                "description": "难度等级（简单/中等/困难）",
                                "enum": ["简单", "中等", "困难", ""],
                                "default": "",
                            },
                            "question_type": {
                                "type": "string",
                                "description": "题型（选择题/填空题/解答题等）",
                                "default": "",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "返回结果数量限制",
                                "default": 10,
                            },
                        },
                        "required": ["question_ids"],
                    },
                ),
                Tool(
                    name="get_question_info",
                    description="获取单个题目的缓存信息。注意：搜索结果已包含完整信息，通常无需调用此工具。",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "question_id": {
                                "type": "string",
                                "description": "题目编号",
                            }
                        },
                        "required": ["question_id"],
                    },
                ),
                Tool(
                    name="create_paper",
                    description="创建试卷（保存题目编号组合到本地）。",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "question_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "题目编号列表",
                            },
                            "paper_name": {
                                "type": "string",
                                "description": "试卷名称",
                            },
                        },
                        "required": ["question_ids", "paper_name"],
                    },
                ),
                Tool(
                    name="select_best_question",
                    description="""【子AI选题】从搜索结果中选择最符合要求的题目。
直接传入搜索返回的题目ID即可，搜索结果已包含题干信息。
子AI会分析题目内容并给出选择理由。""",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "question_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "候选题目ID列表（2-5个，来自搜索结果）",
                            },
                            "requirement": {
                                "type": "string",
                                "description": "选题要求描述（如：需要一道考查顶点式应用的中等难度题目）",
                            },
                        },
                        "required": ["question_ids", "requirement"],
                    },
                ),
                Tool(
                    name="get_question_details",
                    description="""【备用】单独获取题目详情页信息。
注意：搜索结果已包含题干、难度、知识点等信息，通常无需调用此工具。
仅在需要获取答案解析（需登录）时使用。""",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "question_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "题目编号列表（最多10个）",
                            }
                        },
                        "required": ["question_ids"],
                    },
                ),
                Tool(
                    name="export_to_zujuan",
                    description="""导出题目到组卷网题篮。需要先登录（运行 scripts/登录组卷网.bat）。
导出成功后可在 https://zujuan.xkw.com/basket/ 查看并生成试卷。""",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "question_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "题目编号列表",
                            },
                            "paper_name": {
                                "type": "string",
                                "description": "试卷名称（可选）",
                                "default": "AI组卷",
                            },
                        },
                        "required": ["question_ids"],
                    },
                ),
                Tool(
                    name="list_subjects",
                    description="列出所有支持的学科（小学/初中/高中各科）。",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "edu_level": {
                                "type": "string",
                                "description": "学段筛选（可选：小学/初中/高中）",
                                "default": "",
                            },
                        },
                        "required": [],
                    },
                ),
                Tool(
                    name="set_subject",
                    description="切换当前学科。注意：搜索时传入 subject 参数会自动切换，通常无需单独调用。",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "subject": {
                                "type": "string",
                                "description": "学科全名（如：高中数学、初中物理、小学语文）",
                            },
                        },
                        "required": ["subject"],
                    },
                ),
                Tool(
                    name="get_current_subject",
                    description="获取当前设置的学科。默认为高中数学。",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                ),
                Tool(
                    name="diagnose_export",
                    description="""【诊断工具】诊断导出到组卷网功能的问题。
检查项目：
1. 登录状态（.env文件中的用户ID、Cookie、CSRF Token）
2. Cookie有效性（是否过期）
3. bankId配置（Cookie中 vs 代码配置）
4. sync_baskets API测试
5. 返回详细的诊断报告和修复建议

当导出功能出现问题时调用此工具获取诊断信息。""",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "test_question_id": {
                                "type": "string",
                                "description": "用于测试的题目ID（可选，默认使用70287）",
                                "default": "70287",
                            },
                        },
                        "required": [],
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> Sequence[TextContent]:
            """处理工具调用"""
            async def ensure_crawler_initialized() -> None:
                if self.crawler is None:
                    self.crawler = ZujuanCrawler(subject=self.current_subject)
                await self.crawler.initialize()

            try:
                if name == "search_questions_by_keyword":
                    await ensure_crawler_initialized()
                    # 如果指定了学科，自动切换
                    subject = arguments.get("subject", "")
                    if subject and subject in SUBJECTS:
                        self.current_subject = subject
                        self.crawler.set_subject(subject)
                    elif subject:
                        # 尝试模糊匹配
                        for name_key in SUBJECTS.keys():
                            if subject in name_key:
                                self.current_subject = name_key
                                self.crawler.set_subject(name_key)
                                break

                    result = await self.crawler.search_by_keyword(
                        keyword=arguments["keyword"],
                        subject=self.current_subject,
                        limit=arguments.get("limit", 10),
                        difficulty=arguments.get("difficulty", ""),
                        question_type=arguments.get("question_type", ""),
                        max_pages=arguments.get("max_pages", 3),
                    )
                    # 添加当前学科信息和使用提示
                    result["current_subject"] = self.current_subject
                    result["hint"] = "搜索结果已包含完整题目信息(题干、难度、知识点)，无需调用get_question_details"

                elif name == "search_questions_by_knowledge":
                    await ensure_crawler_initialized()
                    # 如果指定了学科，自动切换
                    subject = arguments.get("subject", "")
                    if subject and subject in SUBJECTS:
                        self.current_subject = subject
                        self.crawler.set_subject(subject)
                    elif subject:
                        # 尝试模糊匹配
                        for name_key in SUBJECTS.keys():
                            if subject in name_key:
                                self.current_subject = name_key
                                self.crawler.set_subject(name_key)
                                break

                    result = await self.crawler.search_by_knowledge(
                        knowledge_point=arguments["knowledge_point"],
                        subject=self.current_subject,
                        limit=arguments.get("limit", 10),
                        difficulty=arguments.get("difficulty", ""),
                        question_type=arguments.get("question_type", ""),
                        max_pages=arguments.get("max_pages", 3),
                    )
                    # 添加当前学科信息和使用提示
                    result["current_subject"] = self.current_subject
                    result["hint"] = "搜索结果已包含完整题目信息(题干、难度、知识点)，无需调用get_question_details"

                elif name == "filter_questions":
                    await ensure_crawler_initialized()
                    result = await self.crawler.filter_questions(
                        question_ids=arguments["question_ids"],
                        difficulty=arguments.get("difficulty", ""),
                        question_type=arguments.get("question_type", ""),
                        limit=arguments.get("limit", 10),
                    )

                elif name == "get_question_info":
                    await ensure_crawler_initialized()
                    result = await self.crawler.get_question_info(
                        question_id=arguments["question_id"]
                    )

                elif name == "create_paper":
                    from database.models import save_paper

                    paper_id = await save_paper(
                        paper_name=arguments["paper_name"],
                        questions=arguments["question_ids"],
                    )
                    result = {
                        "success": True,
                        "paper_id": paper_id,
                        "message": f"试卷 '{arguments['paper_name']}' 创建成功",
                    }

                elif name == "get_question_details":
                    await ensure_crawler_initialized()
                    # 批量获取题目详情
                    question_ids = arguments["question_ids"][:10]  # 限制最多10个
                    details = await self.crawler.batch_get_question_details(question_ids)
                    result = details

                elif name == "select_best_question":
                    await ensure_crawler_initialized()
                    # 子AI选题功能
                    question_ids = arguments["question_ids"][:5]  # 限制最多5个候选
                    requirement = arguments["requirement"]

                    # 先获取题目详情
                    details_result = await self.crawler.batch_get_question_details(question_ids)
                    questions = details_result.get("questions", [])

                    if not questions:
                        result = {"success": False, "error": "无法获取候选题目详情"}
                    else:
                        # 调用子AI选择最佳题目
                        result = await select_best_question(
                            questions=questions,
                            requirement=requirement
                        )

                        # 添加说明信息
                        if result.get("success"):
                            result["message"] = f"子AI已从{len(questions)}道候选题目中选择了最符合要求的题目"

                elif name == "export_to_zujuan":
                    await ensure_crawler_initialized()
                    # 导出到组卷网题篮
                    question_ids = arguments["question_ids"]
                    paper_name = arguments.get("paper_name", "AI组卷")

                    # 先获取题目详情（用于填充题型、难度等信息）
                    details_result = await self.crawler.batch_get_question_details(
                        question_ids[:10]  # 限制最多10个
                    )
                    question_details = details_result.get("questions", [])

                    # 调用导出功能（MCP环境无法弹出GUI，禁用自动登录）
                    result = await self.crawler.export_to_basket(
                        question_ids=question_ids,
                        question_details=question_details,
                        auto_login=False  # MCP环境不支持GUI弹窗
                    )

                    # 如果 cookie 过期，显示友好提示
                    if result.get("cookie_expired"):
                        result["user_action_required"] = True
                        result["message"] = "Cookie 已过期，请按以下步骤重新登录"

                    # 如果需要登录（首次使用），尝试启动独立登录窗口
                    elif result.get("login_required"):
                        # 启动独立进程显示登录窗口
                        login_result = await self.crawler.login_via_subprocess()
                        result["login_window"] = login_result
                        result["login_instructions"] = [
                            "首次使用需要登录组卷网：",
                            "1. 双击运行 scripts/登录组卷网.bat",
                            "2. 在弹出的浏览器中登录",
                            "3. 登录成功后按回车保存",
                            "4. 重新调用此工具导出题目"
                        ]

                    # 如果成功，添加额外提示
                    if result.get("success"):
                        result["next_steps"] = [
                            "1. 打开组卷网题篮页面: https://zujuan.xkw.com/basket/",
                            "2. 检查题目是否已添加",
                            "3. 点击'生成试卷'按钮完成组卷"
                        ]

                elif name == "list_subjects":
                    # 列出所有支持的学科
                    edu_level = arguments.get("edu_level", "")
                    subjects = get_all_subjects()

                    if edu_level:
                        # 按学段筛选
                        subjects = [s for s in subjects if s["name"].startswith(edu_level)]

                    result = {
                        "success": True,
                        "current_subject": self.current_subject,
                        "subjects": subjects,
                        "count": len(subjects),
                        "edu_levels": ["小学", "初中", "高中"]
                    }

                elif name == "set_subject":
                    # 切换学科
                    subject = arguments["subject"]

                    if subject not in SUBJECTS:
                        # 尝试模糊匹配
                        matched = None
                        for name_key in SUBJECTS.keys():
                            if subject in name_key or name_key in subject:
                                matched = name_key
                                break

                        if matched:
                            subject = matched
                        else:
                            result = {
                                "success": False,
                                "error": f"未找到学科: {subject}",
                                "available_subjects": list(SUBJECTS.keys()),
                                "hint": "请使用完整学科名，如：高中数学、初中物理、小学语文"
                            }
                            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

                    # 切换学科
                    self.current_subject = subject
                    if self.crawler is not None:
                        self.crawler.set_subject(subject)
                    config = get_subject_config(subject)

                    result = {
                        "success": True,
                        "message": f"已切换到 {subject}",
                        "current_subject": subject,
                        "bank_id": config["bank_id"],
                        "edu_id": config["edu_id"]
                    }

                elif name == "get_current_subject":
                    # 获取当前学科
                    config = get_subject_config(self.current_subject)
                    result = {
                        "success": True,
                        "current_subject": self.current_subject,
                        "short_name": config.get("short_name", ""),
                        "bank_id": config["bank_id"],
                        "edu_id": config["edu_id"]
                    }

                elif name == "diagnose_export":
                    # 诊断导出功能
                    result = await self._diagnose_export(
                        test_question_id=arguments.get("test_question_id", "70287")
                    )

                else:
                    result = {"error": f"未知工具: {name}"}

                return [
                    TextContent(
                        type="text",
                        text=json.dumps(result, ensure_ascii=False, indent=2),
                    )
                ]

            except Exception as e:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({"error": str(e), "tool": name}, ensure_ascii=False),
                    )
                ]

    async def run(self):
        """启动 MCP 服务器（stdio）"""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )

    async def _diagnose_export(self, test_question_id: str = "70287") -> dict:
        """诊断导出功能"""
        import httpx
        import time

        diagnosis = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "checks": [],
            "issues": [],
            "recommendations": [],
            "raw_data": {}
        }

        # 1. 检查 .env 文件
        env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        env_check = {"name": "ENV文件检查", "status": "unknown", "details": {}}

        if os.path.exists(env_file):
            env_check["status"] = "exists"
            try:
                env_data = {}
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        env_data[key] = value

                user_id = env_data.get("ZUJUAN_USER_ID", "")
                csrf_token = env_data.get("ZUJUAN_CSRF_TOKEN", "")
                cookies = env_data.get("ZUJUAN_COOKIES", "")

                env_check["details"] = {
                    "user_id": user_id if user_id else "❌ 未设置",
                    "csrf_token_length": len(csrf_token) if csrf_token else 0,
                    "cookies_length": len(cookies) if cookies else 0,
                    "has_user_id_in_cookie": "userId=" in cookies,
                }

                if not user_id:
                    diagnosis["issues"].append("❌ .env中未找到ZUJUAN_USER_ID，表示未登录")
                    env_check["status"] = "missing_user_id"
                elif not cookies:
                    diagnosis["issues"].append("❌ .env中未找到ZUJUAN_COOKIES")
                    env_check["status"] = "missing_cookies"
                else:
                    env_check["status"] = "ok"

            except Exception as e:
                env_check["status"] = "error"
                env_check["error"] = str(e)
                diagnosis["issues"].append(f"❌ 读取.env文件失败: {e}")
        else:
            env_check["status"] = "not_found"
            diagnosis["issues"].append("❌ .env文件不存在")

        diagnosis["checks"].append(env_check)

        # 2. 检查Cookie中的bankId
        bank_id_check = {"name": "BankID检查", "status": "unknown", "details": {}}

        if "cookies" in locals() and cookies:
            cookie_bank_id = None
            for part in cookies.split(";"):
                part = part.strip()
                if part.startswith("bankId="):
                    cookie_bank_id = part.split("=", 1)[1].strip()
                    break

            config_bank_id = str(self.crawler.bank_id) if self.crawler else "11"

            # 查找bankId对应的学科名称
            cookie_subject = "未知"
            config_subject = self.current_subject
            for subj_name, subj_config in SUBJECTS.items():
                if str(subj_config["bank_id"]) == cookie_bank_id:
                    cookie_subject = subj_name
                    break

            bank_id_check["details"] = {
                "cookie_bank_id": cookie_bank_id or "❌ 未找到",
                "cookie_subject": cookie_subject,
                "config_bank_id": config_bank_id,
                "config_subject": config_subject,
                "match": cookie_bank_id == config_bank_id if cookie_bank_id else False
            }

            if not cookie_bank_id:
                diagnosis["issues"].append("⚠️ Cookie中未找到bankId")
                bank_id_check["status"] = "missing"
            elif cookie_bank_id != config_bank_id:
                diagnosis["issues"].append(f"⚠️ BankID不匹配: Cookie中是{cookie_subject}(bankId={cookie_bank_id}), 当前配置是{config_subject}(bankId={config_bank_id})")
                bank_id_check["status"] = "mismatch"
                bank_id_check["note"] = f"题目会导出到 {cookie_subject} 的题篮中"
                diagnosis["recommendations"].append(f"💡 题目将导出到 {cookie_subject} 题篮: https://zujuan.xkw.com/basket/")
            else:
                bank_id_check["status"] = "ok"
        else:
            bank_id_check["status"] = "no_cookies"

        diagnosis["checks"].append(bank_id_check)

        # 3. 测试API连通性
        api_check = {"name": "API连通性测试", "status": "unknown", "details": {}}

        if "cookies" in locals() and cookies and "csrf_token" in locals():
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Cookie": cookies,
                        "Accept": "application/json",
                        "Origin": "https://zujuan.xkw.com",
                        "Referer": "https://zujuan.xkw.com/",
                        "RequestVerification": csrf_token,
                    }

                    # 使用cookie中的bankId（如果存在）
                    test_bank_id = cookie_bank_id if "cookie_bank_id" in locals() and cookie_bank_id else "11"

                    # 先测试空篮子同步
                    resp = await client.post(
                        "https://zujuan.xkw.com/zujuan-api/sync_baskets",
                        data={
                            "bankId": test_bank_id,
                            "syncFlag": "9",
                            "basketJson": "[]"
                        },
                        headers=headers
                    )

                    api_check["details"]["empty_sync"] = {
                        "status_code": resp.status_code,
                        "bank_id_used": test_bank_id,
                    }

                    if resp.status_code == 200:
                        try:
                            data = resp.json()
                            api_check["details"]["empty_sync"]["response"] = {
                                "serverVersion": data.get("serverVersion"),
                                "questions_count": len(data.get("questions", []))
                            }
                            diagnosis["raw_data"]["empty_sync_response"] = data
                        except:
                            api_check["details"]["empty_sync"]["response_text"] = resp.text[:200]

                    # 再测试添加题目
                    import time as time_module
                    current_time = int(time_module.time() * 1000)
                    test_basket = [{
                        "questionId": int(test_question_id),
                        "addTime": current_time,
                        "childNum": 1,
                        "quesDiff": 3,
                        "quesTypeId": 2703,
                        "quesTypeName": "填空题",
                        "status": "CHECK",
                    }]

                    resp2 = await client.post(
                        "https://zujuan.xkw.com/zujuan-api/sync_baskets",
                        data={
                            "bankId": test_bank_id,
                            "syncFlag": "9",
                            "basketJson": json.dumps(test_basket, ensure_ascii=False)
                        },
                        headers=headers
                    )

                    api_check["details"]["add_question"] = {
                        "status_code": resp2.status_code,
                        "test_question_id": test_question_id,
                        "bank_id_used": test_bank_id,
                    }

                    if resp2.status_code == 200:
                        try:
                            data2 = resp2.json()
                            server_version = data2.get("serverVersion")
                            questions = data2.get("questions", [])

                            api_check["details"]["add_question"]["response"] = {
                                "serverVersion": server_version,
                                "questions_count": len(questions),
                                "question_ids_returned": [q.get("questionId") for q in questions[:5]]
                            }
                            diagnosis["raw_data"]["add_question_response"] = data2

                            # 检查题目是否成功添加
                            test_qid = int(test_question_id)
                            question_added = any(q.get("questionId") == test_qid for q in questions)

                            if question_added:
                                api_check["status"] = "ok"
                                api_check["details"]["add_question"]["question_added"] = True
                            else:
                                api_check["status"] = "question_not_in_response"
                                api_check["details"]["add_question"]["question_added"] = False
                                diagnosis["issues"].append(f"⚠️ 题目{test_question_id}未出现在响应的questions中")

                        except Exception as e:
                            api_check["details"]["add_question"]["parse_error"] = str(e)
                            api_check["details"]["add_question"]["response_text"] = resp2.text[:200]
                    else:
                        api_check["status"] = "http_error"
                        diagnosis["issues"].append(f"❌ API返回HTTP {resp2.status_code}")

            except Exception as e:
                api_check["status"] = "error"
                api_check["error"] = str(e)
                diagnosis["issues"].append(f"❌ API测试失败: {e}")
        else:
            api_check["status"] = "skipped"
            api_check["reason"] = "缺少cookies或csrf_token"

        diagnosis["checks"].append(api_check)

        # 4. 生成建议
        if not diagnosis["issues"]:
            diagnosis["overall_status"] = "✅ 所有检查通过"
            diagnosis["recommendations"].append("导出功能应该正常工作，如果仍有问题请检查网络连接")
        else:
            diagnosis["overall_status"] = f"⚠️ 发现 {len(diagnosis['issues'])} 个问题"

            if any("未登录" in issue or "ZUJUAN_USER_ID" in issue for issue in diagnosis["issues"]):
                diagnosis["recommendations"].append("🔧 请运行 scripts/登录组卷网.bat 进行登录")

            if any("BankID不匹配" in issue for issue in diagnosis["issues"]):
                diagnosis["recommendations"].append("🔧 如需导出到其他学科题篮，请在浏览器中访问该学科页面后重新登录保存Cookie")
                diagnosis["recommendations"].append("🔧 例如：访问 https://zujuan.xkw.com/gzsx/ (高中数学) 后重新运行登录脚本")

            if any("API" in issue or "HTTP" in issue for issue in diagnosis["issues"]):
                diagnosis["recommendations"].append("🔧 检查网络连接，或尝试重新登录获取新的Cookie")

        # 添加调试信息
        diagnosis["debug_info"] = {
            "current_subject": self.current_subject,
            "crawler_bank_id": self.crawler.bank_id if self.crawler else None,
            "test_question_id": test_question_id,
        }

        return diagnosis


async def main():
    server = ExamPaperMCPServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
