"""MCP stdio tool-call handlers.

Split out of `backend/mcp/stdio_server.py` to keep the stdio entrypoint small and testable.
"""

from __future__ import annotations

import json
import os
from typing import Any, Sequence

from mcp.types import TextContent

from backend.agent.memory import MemoryStore
from backend.core.settings import (
    LESSON_PLAN_API_KEY,
    LESSON_PLAN_MODEL,
    MOONSHOT_API_KEY,
    SUB_MODEL,
)
from backend.crawler.interface import CrawlerInterface
from backend.crawler.manager import get_crawler
from backend.mcp.search.bigmodel import web_search_with_bigmodel_mcp
from backend.mcp.tools.python_scientific_compute import python_scientific_compute
from backend.mcp.tools.reviewer import review_questions_with_openrouter
from backend.mcp.tools.stdio_llm import call_llm_text, extract_json_obj, pick_questions
from backend.mcp.core.sub_ai_selector import select_best_question
from backend.core.subjects import (
    DEFAULT_DIFFICULTY,
    DIFFICULTY_LEVELS,
    EDU_LEVELS,
    SUBJECTS,
    get_all_subjects,
    get_subject_config,
    normalize_difficulty,
    resolve_subject,
)


async def handle_tool_call(server: Any, name: str, arguments: Any) -> Sequence[TextContent]:
    """处理工具调用"""

    async def ensure_crawler_initialized(*, subject: str = "", edu_level: str = "") -> CrawlerInterface:
        subj = str(subject or server.current_subject or "").strip() or str(server.current_subject or "").strip()
        edu_level_clean = str(edu_level or "").strip()
        if getattr(server, "crawler", None) is None or str(getattr(server, "current_subject", "") or "").strip() != subj:
            server.current_subject = subj
            server.crawler = await get_crawler(subject=subj, edu_level=edu_level_clean, strict=True)
        return server.crawler

    try:
        if name == "search_questions_by_keyword":
            edu_level = (arguments.get("edu_level") or "").strip()
            subject_input = (arguments.get("subject") or "").strip()
            try:
                resolved_subject = resolve_subject(
                    subject_input or server.current_subject,
                    edu_level=edu_level,
                    strict=True,
                )
                difficulty = normalize_difficulty(
                    arguments.get("difficulty") or DEFAULT_DIFFICULTY,
                    strict=True,
                )
            except ValueError as exc:
                result = {
                    "success": False,
                    "error": str(exc),
                    "current_subject": server.current_subject,
                    "available_subjects": list(SUBJECTS.keys()),
                    "allowed_difficulties": sorted(DIFFICULTY_LEVELS),
                    "allowed_edu_levels": list(EDU_LEVELS.keys()),
                }
                return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

            await ensure_crawler_initialized(subject=resolved_subject, edu_level=edu_level)

            result = await server.crawler.search_by_keyword(
                keyword=arguments["keyword"],
                subject=resolved_subject,
                edu_level=edu_level,
                limit=arguments.get("limit", 10),
                difficulty=difficulty,
                question_type=arguments.get("question_type", ""),
                learn_grade=arguments.get("learn_grade", ""),
                learn_grade_id=arguments.get("learn_grade_id", 0),
                textbook_version=arguments.get("textbook_version", ""),
                max_pages=arguments.get("max_pages", 2),
                year=arguments.get("year", 0),
                province=arguments.get("province", ""),
                province_id=arguments.get("province_id", -1),
                paper_type_id=arguments.get("paper_type_id", 0),
                term=arguments.get("term", 0),
                order_by=arguments.get("order_by", 2),
                source_contains=arguments.get("source_contains", ""),
                stem_contains=arguments.get("stem_contains", ""),
                knowledge_contains=arguments.get("knowledge_contains", ""),
                exclude_elective=bool(arguments.get("exclude_elective", False)),
                elective_mode=arguments.get("elective_mode", ""),
                elective_keywords=arguments.get("elective_keywords"),
                dedup_by_stem=bool(arguments.get("dedup_by_stem", False)),
                min_quality_score=arguments.get("min_quality_score", 0),
                with_quality=bool(arguments.get("with_quality", True)),
                difficulty_value_min=arguments.get("difficulty_value_min"),
                difficulty_value_max=arguments.get("difficulty_value_max"),
                require_difficulty=True,
                strict_subject=True,
            )
            # 添加当前学科信息和使用提示
            result["current_subject"] = server.current_subject
            result["applied_difficulty"] = difficulty
            if edu_level:
                result["applied_edu_level"] = edu_level
            result["hint"] = "搜索结果已包含完整题目信息(题干、难度、知识点)，公式已转换为LaTeX"

        elif name == "search_questions_by_knowledge":
            edu_level = (arguments.get("edu_level") or "").strip()
            subject_input = (arguments.get("subject") or "").strip()
            try:
                resolved_subject = resolve_subject(
                    subject_input or server.current_subject,
                    edu_level=edu_level,
                    strict=True,
                )
                difficulty = normalize_difficulty(
                    arguments.get("difficulty") or DEFAULT_DIFFICULTY,
                    strict=True,
                )
            except ValueError as exc:
                result = {
                    "success": False,
                    "error": str(exc),
                    "current_subject": server.current_subject,
                    "available_subjects": list(SUBJECTS.keys()),
                    "allowed_difficulties": sorted(DIFFICULTY_LEVELS),
                    "allowed_edu_levels": list(EDU_LEVELS.keys()),
                }
                return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

            await ensure_crawler_initialized(subject=resolved_subject, edu_level=edu_level)

            result = await server.crawler.search_by_knowledge(
                knowledge_point=arguments["knowledge_point"],
                subject=resolved_subject,
                edu_level=edu_level,
                limit=arguments.get("limit", 10),
                difficulty=difficulty,
                question_type=arguments.get("question_type", ""),
                learn_grade=arguments.get("learn_grade", ""),
                learn_grade_id=arguments.get("learn_grade_id", 0),
                textbook_version=arguments.get("textbook_version", ""),
                max_pages=arguments.get("max_pages", 2),
                year=arguments.get("year", 0),
                province=arguments.get("province", ""),
                province_id=arguments.get("province_id", -1),
                paper_type_id=arguments.get("paper_type_id", 0),
                term=arguments.get("term", 0),
                order_by=arguments.get("order_by", 2),
                source_contains=arguments.get("source_contains", ""),
                stem_contains=arguments.get("stem_contains", ""),
                knowledge_contains=arguments.get("knowledge_contains", ""),
                exclude_elective=bool(arguments.get("exclude_elective", False)),
                elective_mode=arguments.get("elective_mode", ""),
                elective_keywords=arguments.get("elective_keywords"),
                dedup_by_stem=bool(arguments.get("dedup_by_stem", False)),
                min_quality_score=arguments.get("min_quality_score", 0),
                with_quality=bool(arguments.get("with_quality", True)),
                difficulty_value_min=arguments.get("difficulty_value_min"),
                difficulty_value_max=arguments.get("difficulty_value_max"),
                require_difficulty=True,
                strict_subject=True,
            )
            # 添加当前学科信息和使用提示
            result["current_subject"] = server.current_subject
            result["applied_difficulty"] = difficulty
            if edu_level:
                result["applied_edu_level"] = edu_level
            result["hint"] = "搜索结果已包含完整题目信息(题干、难度、知识点)，公式已转换为LaTeX"

        elif name == "filter_questions":
            await ensure_crawler_initialized()
            result = await server.crawler.filter_questions(
                question_ids=arguments["question_ids"],
                difficulty=arguments.get("difficulty", ""),
                question_type=arguments.get("question_type", ""),
                limit=arguments.get("limit", 10),
            )

        elif name == "get_question_info":
            await ensure_crawler_initialized()
            result = await server.crawler.get_question_info(question_id=arguments["question_id"])

        elif name == "create_paper":
            from backend.database.repositories.question.papers import save_paper

            paper_id = await save_paper(
                user_id="1",
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
            details = await server.crawler.batch_get_question_details(question_ids)
            result = details

        elif name == "select_best_question":
            await ensure_crawler_initialized()
            # 子AI选题功能
            question_ids = arguments["question_ids"][:5]  # 限制最多5个候选
            requirement = arguments["requirement"]

            # 先获取题目详情
            details_result = await server.crawler.batch_get_question_details(question_ids)
            questions = details_result.get("questions", [])

            if not questions:
                result = {"success": False, "error": "无法获取候选题目详情"}
            else:
                # 调用子AI选择最佳题目
                result = await select_best_question(questions=questions, requirement=requirement)

                # 添加说明信息
                if result.get("success"):
                    result["message"] = f"子AI已从{len(questions)}道候选题目中选择了最符合要求的题目"

        elif name == "export_to_zujuan":
            await ensure_crawler_initialized()
            # 导出到组卷网题篮
            question_ids = arguments["question_ids"]
            paper_name = arguments.get("paper_name", "AI组卷")
            export_subject = (arguments.get("subject") or "").strip()

            if export_subject:
                # 复用 set_subject 的模糊匹配逻辑
                if export_subject not in SUBJECTS:
                    matched = None
                    for name_key in SUBJECTS.keys():
                        if export_subject in name_key or name_key in export_subject:
                            matched = name_key
                            break
                    if matched:
                        export_subject = matched
                    else:
                        result = {
                            "success": False,
                            "error": f"未找到学科: {export_subject}",
                            "available_subjects": list(SUBJECTS.keys()),
                            "hint": "请使用完整学科名，如：高中数学、初中物理、小学语文",
                        }
                        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

                server.current_subject = export_subject
                await ensure_crawler_initialized(subject=export_subject)

            # 先获取题目详情（用于填充题型、难度等信息）
            details_result = await server.crawler.batch_get_question_details(
                question_ids[:10]  # 限制最多10个
            )
            question_details = details_result.get("questions", [])

            # 调用导出功能（MCP环境无法弹出GUI，禁用自动登录）
            result = await server.crawler.export_to_basket(
                question_ids=question_ids,
                question_details=question_details,
                auto_login=False,  # MCP环境不支持GUI弹窗
            )

            # 如果 cookie 过期，显示友好提示
            if result.get("cookie_expired"):
                result["user_action_required"] = True
                result["message"] = "Cookie 已过期，请按以下步骤重新登录"

            # 如果需要登录（首次使用），尝试启动独立登录窗口
            elif result.get("login_required"):
                # 启动独立进程显示登录窗口
                login_result = await server.crawler.login_via_subprocess()
                result["login_window"] = login_result
                result["login_instructions"] = [
                    "首次使用需要登录组卷网：",
                    f'1. 双击运行 scripts/登录组卷网.bat "{server.current_subject}"',
                    "2. 在弹出的浏览器中登录",
                    "3. 登录成功后按回车保存",
                    "4. 重新调用此工具导出题目",
                ]

            # 如果成功，添加额外提示
            if result.get("success"):
                result["next_steps"] = [
                    "1. 打开组卷网题篮页面: https://zujuan.xkw.com/basket/",
                    "2. 检查题目是否已添加",
                    "3. 点击'生成试卷'按钮完成组卷",
                ]

        elif name == "review_paper":
            await ensure_crawler_initialized()

            # 可选切换学科
            target_subject = (arguments.get("subject") or "").strip()
            if target_subject:
                if target_subject not in SUBJECTS:
                    matched = None
                    for name_key in SUBJECTS.keys():
                        if target_subject in name_key or name_key in target_subject:
                            matched = name_key
                            break
                    if matched:
                        target_subject = matched
                    else:
                        result = {
                            "success": False,
                            "error": f"未找到学科: {target_subject}",
                            "available_subjects": list(SUBJECTS.keys()),
                            "hint": "请使用完整学科名，如：高中数学、初中物理、小学语文",
                        }
                        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

                server.current_subject = target_subject
                await ensure_crawler_initialized(subject=target_subject)

            paper_id = arguments.get("paper_id")
            question_ids = arguments.get("question_ids") or []
            paper_name = (arguments.get("paper_name") or "").strip()
            focus = (arguments.get("focus") or "").strip()
            strictness = int(arguments.get("strictness", 3) or 3)
            max_questions = int(arguments.get("max_questions", 20) or 20)
            if max_questions < 1:
                max_questions = 1
            if max_questions > 50:
                max_questions = 50

            paper_meta = None
            if paper_id is not None:
                from backend.database.repositories.question.papers import get_paper

                paper = await get_paper(user_id="1", paper_id=int(paper_id))
                if not paper:
                    result = {"success": False, "error": f"未找到试卷 paper_id={paper_id}"}
                    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

                paper_meta = paper
                if not paper_name:
                    paper_name = paper.get("paper_name", "") or ""
                question_ids = [q.get("question_id") for q in paper.get("questions", []) if q.get("question_id")]

            if not question_ids:
                result = {
                    "success": False,
                    "error": "review_paper 需要 paper_id 或 question_ids",
                    "hint": "传入 paper_id（create_paper 的返回）或直接传入题目ID列表",
                }
                return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

            question_ids = [str(x) for x in question_ids][:max_questions]

            # 拉取题干等信息（batch_get_question_details 单次最多10个，这里分批拉取）
            details_all = []
            for i in range(0, len(question_ids), 10):
                chunk = question_ids[i : i + 10]
                chunk_res = await server.crawler.batch_get_question_details(chunk)
                details_all.extend(chunk_res.get("questions", []))

            # 保持顺序
            detail_map = {str(q.get("question_id")): q for q in details_all if q.get("question_id")}
            ordered_questions = [detail_map.get(qid, {"question_id": qid}) for qid in question_ids]

            result = await review_questions_with_openrouter(
                questions=ordered_questions,
                paper_name=paper_name,
                subject=server.current_subject,
                focus=focus,
                strictness=strictness,
            )
            if paper_meta:
                result["paper_meta"] = {
                    "paper_id": paper_meta.get("paper_id"),
                    "paper_name": paper_meta.get("paper_name"),
                    "question_count": len(paper_meta.get("questions", []) or []),
                }

        elif name == "list_subjects":
            # 列出所有支持的学科
            edu_level = arguments.get("edu_level", "")
            subjects = get_all_subjects()

            if edu_level:
                # 按学段筛选
                subjects = [s for s in subjects if s["name"].startswith(edu_level)]

            result = {
                "success": True,
                "current_subject": server.current_subject,
                "subjects": subjects,
                "count": len(subjects),
                "edu_levels": ["小学", "初中", "高中"],
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
                        "hint": "请使用完整学科名，如：高中数学、初中物理、小学语文",
                    }
                    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

            # 切换学科
            await ensure_crawler_initialized(subject=subject)
            config = get_subject_config(subject)

            result = {
                "success": True,
                "message": f"已切换到 {subject}",
                "current_subject": subject,
                "bank_id": config["bank_id"],
                "edu_id": config["edu_id"],
            }

        elif name == "get_current_subject":
            # 获取当前学科
            config = get_subject_config(server.current_subject)
            result = {
                "success": True,
                "current_subject": server.current_subject,
                "short_name": config.get("short_name", ""),
                "bank_id": config["bank_id"],
                "edu_id": config["edu_id"],
            }

        elif name == "get_available_filters":
            edu_level = (arguments.get("edu_level") or "").strip()
            subject_input = (arguments.get("subject") or "").strip()
            try:
                resolved_subject = resolve_subject(
                    subject_input or server.current_subject,
                    edu_level=edu_level,
                    strict=True,
                )
            except ValueError as exc:
                result = {
                    "success": False,
                    "error": str(exc),
                    "current_subject": server.current_subject,
                    "available_subjects": list(SUBJECTS.keys()),
                    "allowed_edu_levels": list(EDU_LEVELS.keys()),
                }
                return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

            await ensure_crawler_initialized(subject=resolved_subject, edu_level=edu_level)

            result = await server.crawler.get_available_filters()
            result["current_subject"] = server.current_subject

        elif name == "compose_paper_blueprint":
            edu_level = (arguments.get("edu_level") or "").strip()
            subject_input = (arguments.get("subject") or "").strip()
            try:
                resolved_subject = resolve_subject(
                    subject_input or server.current_subject,
                    edu_level=edu_level,
                    strict=True,
                )
            except ValueError as exc:
                result = {
                    "success": False,
                    "error": str(exc),
                    "current_subject": server.current_subject,
                    "available_subjects": list(SUBJECTS.keys()),
                    "allowed_edu_levels": list(EDU_LEVELS.keys()),
                }
                return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

            await ensure_crawler_initialized(subject=resolved_subject, edu_level=edu_level)

            result = await server.crawler.compose_paper_blueprint(
                blueprint=arguments.get("blueprint") or [],
                subject=resolved_subject,
                edu_level=edu_level,
                learn_grade=arguments.get("learn_grade", ""),
                learn_grade_id=arguments.get("learn_grade_id", 0),
                textbook_version=arguments.get("textbook_version", ""),
                elective_mode=arguments.get("elective_mode", ""),
                elective_keywords=arguments.get("elective_keywords"),
                exclude_elective=bool(arguments.get("exclude_elective", False)),
                year=arguments.get("year", 0),
                province=arguments.get("province", ""),
                province_id=arguments.get("province_id", -1),
                paper_type_id=arguments.get("paper_type_id", 0),
                term=arguments.get("term", 0),
                order_by=arguments.get("order_by", 2),
                max_pages=arguments.get("max_pages", 2),
                per_slot_expand=arguments.get("per_slot_expand", 3),
                min_quality_score=arguments.get("min_quality_score", 0),
                dedup_by_stem=bool(arguments.get("dedup_by_stem", True)),
                strict_subject=bool(arguments.get("strict_subject", True)),
            )
            result["current_subject"] = server.current_subject

        elif name == "retrieve_knowledge":
            topic = (arguments.get("topic") or "").strip()
            subject_input = (arguments.get("subject") or "").strip()
            difficulty = (arguments.get("difficulty") or DEFAULT_DIFFICULTY).strip() or DEFAULT_DIFFICULTY
            if not topic:
                result = {"success": False, "error": "missing_topic"}
            elif not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
                result = {
                    "success": True,
                    "topic": topic,
                    "subject": subject_input or server.current_subject,
                    "difficulty": difficulty,
                    "definition": "",
                    "key_points": [],
                    "prerequisites": [],
                    "common_mistakes": [],
                    "methods": [],
                    "source": "fallback",
                    "note": "未配置 LESSON_PLAN_API_KEY，返回为空。",
                }
            else:
                prompt = f"""请为“{subject_input or server.current_subject}”的知识点“{topic}”生成事实性要点。\n\n要求：\n- 输出严格 JSON（不要 Markdown、不要代码块）\n- 字段：definition(str), key_points(str[]), prerequisites(str[]), common_mistakes(str[]), methods(str[])\n- 难度参考：{difficulty}\n"""
                text = await call_llm_text(
                    messages=[
                        {"role": "system", "content": "你是严谨的学科老师，输出必须是JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    model=SUB_MODEL,
                    temperature=0.2,
                    max_tokens=900,
                )
                obj = extract_json_obj(text)
                result = {
                    "success": True,
                    "topic": topic,
                    "subject": subject_input or server.current_subject,
                    "difficulty": difficulty,
                    "definition": str(obj.get("definition") or ""),
                    "key_points": list(obj.get("key_points") or []),
                    "prerequisites": list(obj.get("prerequisites") or []),
                    "common_mistakes": list(obj.get("common_mistakes") or []),
                    "methods": list(obj.get("methods") or []),
                    "source": "llm",
                }

        elif name == "search_examples":
            topic = (arguments.get("topic") or "").strip()
            subject_input = (arguments.get("subject") or "").strip()
            difficulty_input = (arguments.get("difficulty") or DEFAULT_DIFFICULTY).strip()
            limit = int(arguments.get("limit", 3) or 3)
            limit = max(1, min(5, limit))
            try:
                resolved_subject = resolve_subject(subject_input or server.current_subject, strict=True)
                difficulty = normalize_difficulty(difficulty_input or DEFAULT_DIFFICULTY, strict=True)
            except ValueError as exc:
                result = {"success": False, "error": str(exc)}
                return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
            await ensure_crawler_initialized(subject=resolved_subject)
            res = await server.crawler.search_by_keyword(
                keyword=topic,
                subject=resolved_subject,
                limit=max(12, limit * 4),
                difficulty=difficulty,
                max_pages=2,
                dedup_by_stem=True,
                min_quality_score=10,
                with_quality=True,
                require_difficulty=True,
                strict_subject=True,
            )
            questions = list(res.get("questions") or [])
            result = {
                "success": True,
                "topic": topic,
                "subject": resolved_subject,
                "difficulty": difficulty,
                "examples": pick_questions(questions, limit=limit),
            }

        elif name == "search_exercises":
            topic = (arguments.get("topic") or "").strip()
            subject_input = (arguments.get("subject") or "").strip()
            difficulty_input = (arguments.get("difficulty") or DEFAULT_DIFFICULTY).strip()
            limit = int(arguments.get("limit", 10) or 10)
            limit = max(5, min(30, limit))
            try:
                resolved_subject = resolve_subject(subject_input or server.current_subject, strict=True)
                difficulty = normalize_difficulty(difficulty_input or DEFAULT_DIFFICULTY, strict=True)
            except ValueError as exc:
                result = {"success": False, "error": str(exc)}
                return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
            await ensure_crawler_initialized(subject=resolved_subject)
            res = await server.crawler.search_by_keyword(
                keyword=topic,
                subject=resolved_subject,
                limit=max(20, limit * 3),
                difficulty=difficulty,
                max_pages=2,
                dedup_by_stem=True,
                min_quality_score=10,
                with_quality=True,
                require_difficulty=True,
                strict_subject=True,
            )
            questions = list(res.get("questions") or [])
            result = {
                "success": True,
                "topic": topic,
                "subject": resolved_subject,
                "difficulty": difficulty,
                "exercises": pick_questions(questions, limit=limit),
            }

        elif name == "analyze_topic":
            topic = (arguments.get("topic") or "").strip()
            subject_input = (arguments.get("subject") or "").strip()
            if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
                result = {
                    "success": True,
                    "topic": topic,
                    "subject": subject_input,
                    "outline": ["概念与定义", "方法小结", "例题精讲", "分层练习"],
                    "confusions": [],
                    "source": "fallback",
                }
            else:
                payload = {
                    "topic": topic,
                    "subject": subject_input or server.current_subject,
                    "required_output": {
                        "outline": "string[]",
                        "confusions": "string[]",
                        "teaching_order": "string[]",
                    },
                }
                text = await call_llm_text(
                    messages=[
                        {"role": "system", "content": "你是严谨的教学设计专家，输出必须是JSON。"},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    model=LESSON_PLAN_MODEL,
                    temperature=0.2,
                    max_tokens=900,
                )
                obj = extract_json_obj(text)
                result = {
                    "success": True,
                    "topic": topic,
                    "subject": subject_input or server.current_subject,
                    "outline": list(obj.get("outline") or []),
                    "confusions": list(obj.get("confusions") or []),
                    "teaching_order": list(obj.get("teaching_order") or []),
                    "source": "llm",
                }

        elif name == "generate_explanation":
            topic = (arguments.get("topic") or "").strip()
            subject_input = (arguments.get("subject") or "").strip()
            knowledge = arguments.get("knowledge") if isinstance(arguments.get("knowledge"), dict) else {}
            analysis = arguments.get("analysis") if isinstance(arguments.get("analysis"), dict) else {}
            if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
                result = {
                    "success": True,
                    "markdown": f"## 一、知识点讲解：{topic}\n\n（未配置模型，无法生成详细讲解。）\n",
                    "source": "fallback",
                }
            else:
                prompt = {
                    "topic": topic,
                    "subject": subject_input or server.current_subject,
                    "knowledge": knowledge,
                    "analysis": analysis,
                    "instructions": "请生成 Markdown 章节：知识点讲解。包含：定义、关键点、常见误区、方法小结。不要输出练习题。",
                }
                text = await call_llm_text(
                    messages=[
                        {"role": "system", "content": "你是严谨的自学资料编写老师，输出必须是Markdown。"},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                    model=LESSON_PLAN_MODEL,
                    temperature=0.4,
                    max_tokens=1500,
                )
                result = {"success": True, "markdown": (text or "").strip(), "source": "llm"}

        elif name == "generate_solution":
            stem = (arguments.get("stem") or "").strip()
            subject_input = (arguments.get("subject") or "").strip()
            topic = (arguments.get("topic") or "").strip()
            if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
                result = {"success": True, "markdown": "（未配置模型，无法生成解答。）", "source": "fallback"}
            else:
                prompt = f"""请为下面题目写出详细分步解答（Markdown）。\n\n要求：\n- 每一步说明在做什么\n- 如果题干信息不足，请说明需要补充什么\n\n学科：{subject_input or server.current_subject}\n知识点：{topic or "（未指定）"}\n\n题目：\n{stem}\n"""
                text = await call_llm_text(
                    messages=[
                        {"role": "system", "content": "你是严谨的解题老师，输出必须是Markdown。"},
                        {"role": "user", "content": prompt},
                    ],
                    model=LESSON_PLAN_MODEL,
                    temperature=0.3,
                    max_tokens=1200,
                )
                result = {"success": True, "markdown": (text or "").strip(), "source": "llm"}

        elif name == "review_content":
            topic = (arguments.get("topic") or "").strip()
            markdown = (arguments.get("markdown") or "").strip()
            if not markdown:
                result = {"success": False, "error": "missing_markdown"}
            elif not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
                result = {"success": True, "passed": True, "issues": [], "suggestions": [], "source": "fallback"}
            else:
                prompt = f"""请审查下面这份自学资料 Markdown，找出：\n1) 逻辑跳跃/不清晰处\n2) 可能的错误或表述不严谨\n3) 建议改进点（最多5条）\n\n要求：输出严格 JSON（不要 Markdown）。字段：passed(bool), issues(string[]), suggestions(string[])\n\n主题：{topic}\n\nMarkdown:\n{markdown}\n"""
                text = await call_llm_text(
                    messages=[
                        {"role": "system", "content": "你是严谨的审稿人，输出必须是JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    model=LESSON_PLAN_MODEL,
                    temperature=0.1,
                    max_tokens=900,
                )
                obj = extract_json_obj(text)
                result = {
                    "success": True,
                    "passed": bool(obj.get("passed")) if "passed" in obj else True,
                    "issues": list(obj.get("issues") or []),
                    "suggestions": list(obj.get("suggestions") or []),
                    "source": "llm",
                }

        elif name == "get_user_profile":
            user_id = (arguments.get("user_id") or "").strip()
            store = MemoryStore()
            profile = await store.get_user_profile(user_id=user_id or "anonymous")
            result = {"success": True, "profile": profile.to_dict()}

        elif name == "update_user_profile":
            user_id = (arguments.get("user_id") or "").strip()
            patch = arguments.get("patch") if isinstance(arguments.get("patch"), dict) else {}
            store = MemoryStore()
            profile = await store.update_user_profile(user_id=user_id or "anonymous", patch=patch)
            result = {"success": True, "profile": profile.to_dict()}

        elif name == "compress_context":
            messages = arguments.get("messages") if isinstance(arguments.get("messages"), list) else []
            target_chars = int(arguments.get("target_chars", 220) or 220)
            target_chars = max(80, min(2000, target_chars))
            if not messages:
                result = {"success": True, "summary": ""}
            elif not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
                parts = []
                for m in messages[-6:]:
                    role = str((m or {}).get("role") or "unknown")
                    content = str((m or {}).get("content") or "")[:120]
                    if content:
                        parts.append(f"{role}: {content}")
                summary = " | ".join(parts)[:target_chars]
                result = {"success": True, "summary": summary, "source": "fallback"}
            else:
                prompt = f"""请将下面的对话/记录压缩为一段简洁摘要（约{target_chars}字左右），保留：\n- 用户主要目标与约束\n- 关键决策\n- 重要工具结果/错误\n\n输出：纯文本摘要（不要Markdown）。\n\n记录：\n{json.dumps(messages, ensure_ascii=False)}\n"""
                text = await call_llm_text(
                    messages=[
                        {"role": "system", "content": "你是上下文压缩器，输出必须是纯文本摘要。"},
                        {"role": "user", "content": prompt},
                    ],
                    model=SUB_MODEL,
                    temperature=0.2,
                    max_tokens=400,
                )
                result = {"success": True, "summary": (text or "").strip(), "source": "llm"}

        elif name == "web_search":
            query = (arguments.get("query") or "").strip()
            limit = max(1, min(int(arguments.get("limit", 5) or 5), 10))
            provider_in = str(arguments.get("provider") or "auto").strip().lower() or "auto"
            if provider_in not in {"auto", "exa", "bigmodel"}:
                provider_in = "auto"
            mode_in = str(arguments.get("mode") or "trending").strip()
            if mode_in not in {"trending", "patterns"}:
                mode_in = "trending"
            recency_days = max(1, min(int(arguments.get("recency_days", 180) or 180), 3650))

            if provider_in == "auto":
                try:
                    from backend.mcp.search.exa import EXA_API_KEY as _EXA_API_KEY

                    provider_in = "exa" if bool(str(_EXA_API_KEY or "").strip()) else "bigmodel"
                except Exception:
                    provider_in = "bigmodel"

            if provider_in == "exa":
                try:
                    from datetime import datetime, timedelta

                    from backend.mcp.search.exa import exa_search

                    category: Optional[str] = None
                    start_published_date: Optional[str] = None
                    end_published_date: Optional[str] = None
                    if mode_in == "trending":
                        category = "news"
                        today = datetime.now().date()
                        end_published_date = today.isoformat()
                        start_published_date = (today - timedelta(days=recency_days)).isoformat()

                    res = await exa_search(
                        query=query,
                        num_results=limit,
                        category=category,
                        start_published_date=start_published_date,
                        end_published_date=end_published_date,
                        include_text=False,
                        include_summary=True,
                        include_highlights=True,
                    )
                except Exception as exc:
                    result = {"success": False, "provider": "exa", "query": query, "error": f"exa_search_failed: {exc}", "results": []}
                else:
                    if not isinstance(res, dict) or not res.get("success"):
                        result = {
                            "success": False,
                            "provider": str((res or {}).get("provider") or "exa"),
                            "query": query,
                            "error": str((res or {}).get("error") or "exa_search_failed"),
                            "results": [],
                        }
                    else:
                        results_in = res.get("results") if isinstance(res.get("results"), list) else []
                        results_out: List[Dict[str, Any]] = []
                        for item in results_in[:limit]:
                            if not isinstance(item, dict):
                                continue
                            title = str(item.get("title") or "").strip()
                            url = str(item.get("url") or "").strip()
                            published = str(item.get("published_date") or "").strip()
                            snippet = str(item.get("summary") or "").strip()
                            if not snippet:
                                highlights = item.get("highlights") if isinstance(item.get("highlights"), list) else []
                                snippet = str(highlights[0] if highlights else "").strip()
                            if len(snippet) > 900:
                                snippet = snippet[:900].rstrip() + "…"
                            results_out.append(
                                {"title": title, "url": url, "snippet": snippet, "published_date": published}
                            )
                        result = {
                            "success": True,
                            "provider": "exa",
                            "query": query,
                            "mode": mode_in,
                            "recency_days": recency_days,
                            "results": results_out,
                        }
            else:
                model = (arguments.get("model") or "").strip()
                result = await web_search_with_bigmodel_mcp(
                    query=query,
                    limit=limit,
                    model=model,
                )
                if isinstance(result, dict):
                    result = {
                        **result,
                        "mode": str(result.get("mode") or mode_in),
                        "recency_days": int(result.get("recency_days") or recency_days),
                    }

        elif name == "python_scientific_compute":
            code = (arguments.get("code") or "").strip()
            purpose = (arguments.get("purpose") or "").strip()
            timeout_seconds = int(arguments.get("timeout_seconds") or 5)
            result = await python_scientific_compute(
                code=code,
                purpose=purpose,
                timeout_seconds=timeout_seconds,
            )

        elif name == "zhihu_fetch":
            url = (arguments.get("url") or "").strip()
            cookies = (arguments.get("cookies") or "").strip() or (os.getenv("ZHIHU_COOKIES") or "").strip()
            timeout_seconds = int(arguments.get("timeout_seconds") or 30)
            timeout_seconds = max(5, min(timeout_seconds, 60))

            if not url:
                result = {"success": False, "error": "url 不能为空"}
            else:
                try:
                    from backend.mcp.search.zhihu import ZhihuFetcher

                    fetcher = ZhihuFetcher(cookies=cookies, timeout_seconds=timeout_seconds)
                    res = await fetcher.fetch(url, cookies=cookies)
                    result = res.to_dict()
                    if result.get("success") is False and result.get("error") == "cookies_required" and not cookies:
                        result["note"] = "需要登录态：请在环境变量或 .env 配置 ZHIHU_COOKIES，或通过参数 cookies 传入"
                except Exception as exc:
                    result = {"success": False, "error": f"zhihu_fetch failed: {exc}"}

        elif name == "diagnose_export":
            # 诊断导出功能
            result = await server._diagnose_export(test_question_id=arguments.get("test_question_id", "70287"))

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
