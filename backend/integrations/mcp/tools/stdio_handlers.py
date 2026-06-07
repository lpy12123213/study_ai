"""MCP stdio tool-call handlers.

Split out of `backend/mcp/stdio_server.py` to keep the stdio entrypoint small and testable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional, Sequence

from mcp.types import TextContent

from backend.agent.memory import MemoryStore
from backend.core.logging_utils import get_logger
from backend.core.settings import (
    LESSON_PLAN_API_KEY,
    LESSON_PLAN_MODEL,
    MOONSHOT_API_KEY,
    SUB_MODEL,
)
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
from backend.integrations.crawler.interface import CrawlerInterface
from backend.integrations.crawler.manager import get_crawler
from backend.generation.agentic.prompts import create_default_prompt_registry
from backend.integrations.mcp.core.sub_ai_selector import select_best_question
from backend.integrations.mcp.search.bigmodel import web_search_with_bigmodel_mcp
from backend.integrations.mcp.tools.python_scientific_compute import python_scientific_compute
from backend.integrations.mcp.tools.reviewer import review_questions_with_openrouter
from backend.integrations.mcp.tools.stdio_llm import call_llm_text, extract_json_obj, pick_questions

logger = get_logger(__name__)


def _prompt(prompt_id: str) -> str:
    return create_default_prompt_registry().render(prompt_id).content


def _render_prompt(prompt_id: str, **values: Any) -> str:
    return create_default_prompt_registry().render(prompt_id, **values).content


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
                login_script = str(login_result.get("login_script") or "scripts/登录组卷网.bat")
                login_command = str(login_result.get("login_command") or f'"{login_script}" "{server.current_subject}"')
                result["login_script"] = login_script
                result["login_command"] = login_command
                result["login_instructions"] = [
                    "首次使用需要登录组卷网：",
                    f"1. 运行 {login_command}",
                    "2. 在弹出的浏览器中登录",
                    "3. 登录成功后等待脚本自动保存",
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
                prompt = _render_prompt(
                    "mcp.retrieve_knowledge.user.v1",
                    topic=topic,
                    subject=subject_input or server.current_subject,
                    difficulty=difficulty,
                )
                text = await call_llm_text(
                    messages=[
                        {"role": "system", "content": _prompt("mcp.knowledge_facts.v1")},
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
                        {"role": "system", "content": _prompt("lesson_plan.activity_planner.v1")},
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
                    "instructions": "Generate a Markdown section for knowledge-point explanation. Include definition, key points, common misconceptions, and method summary. Do not output exercises. Match the user's/topic language.",
                }
                text = await call_llm_text(
                    messages=[
                        {"role": "system", "content": _prompt("mcp.study_section.v1")},
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
                prompt = f"""Write a detailed step-by-step solution for the problem below in Markdown.\n\nRequirements:\n- Explain what each step is doing.\n- If the problem statement lacks information, state what needs to be added.\n- Match the language of the problem statement unless the caller explicitly requires another language.\n\nSubject: {subject_input or server.current_subject}\nKnowledge point: {topic or "(unspecified)"}\n\nProblem:\n{stem}\n"""
                text = await call_llm_text(
                    messages=[
                        {"role": "system", "content": _prompt("mcp.solve_stepwise.v1")},
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
                prompt = f"""Review the self-study Markdown below and identify:\n1) Logical jumps or unclear parts.\n2) Possible errors or imprecise wording.\n3) Improvement suggestions, up to 5.\n\nRequirements: output strict JSON only, not Markdown. Fields: passed(bool), issues(string[]), suggestions(string[]). Match issue/suggestion language to the material language.\n\nTopic: {topic}\n\nMarkdown:\n{markdown}\n"""
                text = await call_llm_text(
                    messages=[
                        {"role": "system", "content": _prompt("mcp.review_study_material.v1")},
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
                prompt = f"""Compress the conversation/log below into one concise summary of about {target_chars} characters. Preserve:\n- The user's main goals and constraints.\n- Key decisions.\n- Important tool results or errors.\n\nOutput a plain-text summary only, not Markdown. Match the dominant conversation language.\n\nLog:\n{json.dumps(messages, ensure_ascii=False)}\n"""
                text = await call_llm_text(
                    messages=[
                        {"role": "system", "content": _prompt("mcp.context_summarize.v1")},
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
            if provider_in not in {"auto", "tavily", "exa", "bigmodel"}:
                provider_in = "auto"
            mode_in = str(arguments.get("mode") or "trending").strip()
            if mode_in not in {"trending", "patterns"}:
                mode_in = "trending"
            recency_days = max(1, min(int(arguments.get("recency_days", 180) or 180), 3650))

            if provider_in == "auto":
                has_tavily = False
                has_exa = False
                try:
                    from backend.integrations.mcp.search.tavily import TAVILY_API_KEY as _TAVILY_API_KEY

                    has_tavily = bool(str(_TAVILY_API_KEY or "").strip())
                except ImportError:
                    has_tavily = False
                try:
                    from backend.integrations.mcp.search.exa import EXA_API_KEY as _EXA_API_KEY

                    has_exa = bool(str(_EXA_API_KEY or "").strip())
                except ImportError:
                    has_exa = False
                provider_in = "tavily" if has_tavily else "exa" if has_exa else "bigmodel"

            if provider_in == "tavily":
                try:
                    from backend.integrations.mcp.search.tavily import tavily_search

                    res = await tavily_search(
                        query=query,
                        max_results=limit,
                        search_depth="basic",
                        include_answer=False,
                        include_raw_content=False,
                        topic="news" if mode_in == "trending" else "general",
                        days=recency_days if mode_in == "trending" else None,
                    )
                except Exception as exc:
                    logger.warning("stdio_tavily_search_failed", extra={"tool": name}, exc_info=True)
                    result = {
                        "success": False,
                        "provider": "tavily",
                        "query": query,
                        "error": f"tavily_search_failed: {exc}",
                        "results": [],
                    }
                else:
                    if not isinstance(res, dict) or not res.get("success"):
                        result = {
                            "success": False,
                            "provider": str((res or {}).get("provider") or "tavily"),
                            "query": query,
                            "error": str((res or {}).get("error") or "tavily_search_failed"),
                            "results": [],
                        }
                    else:
                        results_in = res.get("results") if isinstance(res.get("results"), list) else []
                        results_out: List[Dict[str, Any]] = []
                        for item in results_in[:limit]:
                            if not isinstance(item, dict):
                                continue
                            snippet = str(item.get("snippet") or item.get("text") or "").strip()
                            if len(snippet) > 900:
                                snippet = snippet[:900].rstrip() + "…"
                            results_out.append(
                                {
                                    "title": str(item.get("title") or "").strip(),
                                    "url": str(item.get("url") or "").strip(),
                                    "snippet": snippet,
                                    "published_date": str(item.get("published_date") or "").strip(),
                                }
                            )
                        result = {
                            "success": True,
                            "provider": "tavily",
                            "query": query,
                            "mode": mode_in,
                            "recency_days": recency_days,
                            "results": results_out,
                        }
            elif provider_in == "exa":
                try:
                    from datetime import datetime, timedelta

                    from backend.integrations.mcp.search.exa import exa_search

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
                    logger.warning("stdio_exa_search_failed", extra={"tool": name}, exc_info=True)
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
                    from backend.integrations.mcp.search.zhihu import ZhihuFetcher

                    fetcher = ZhihuFetcher(cookies=cookies, timeout_seconds=timeout_seconds)
                    res = await fetcher.fetch(url, cookies=cookies)
                    result = res.to_dict()
                    if result.get("success") is False and result.get("error") == "cookies_required" and not cookies:
                        result["note"] = "需要登录态：请在环境变量或 .env 配置 ZHIHU_COOKIES，或通过参数 cookies 传入"
                except Exception as exc:
                    logger.warning("stdio_zhihu_fetch_failed", extra={"tool": name}, exc_info=True)
                    result = {"success": False, "error": f"zhihu_fetch failed: {exc}"}

        elif name == "solve_paper":
            await ensure_crawler_initialized()

            target_subject = (arguments.get("subject") or "").strip()
            if target_subject and target_subject in SUBJECTS:
                server.current_subject = target_subject
                await ensure_crawler_initialized(subject=target_subject)

            paper_id = arguments.get("paper_id")
            question_ids = arguments.get("question_ids") or []
            max_questions = max(1, min(int(arguments.get("max_questions", 30) or 30), 60))
            concurrency = max(1, min(int(arguments.get("concurrency", 3) or 3), 6))

            if paper_id is not None:
                from backend.database.repositories.question.papers import get_paper

                paper = await get_paper(user_id="1", paper_id=int(paper_id))
                if not paper:
                    result = {"success": False, "error": f"未找到试卷 paper_id={paper_id}"}
                    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
                question_ids = [q.get("question_id") for q in paper.get("questions", []) if q.get("question_id")]

            if not question_ids:
                result = {"success": False, "error": "solve_paper 需要 paper_id 或 question_ids"}
                return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

            question_ids = [str(x) for x in question_ids][:max_questions]

            details_all: List[Dict[str, Any]] = []
            for i in range(0, len(question_ids), 10):
                chunk_res = await server.crawler.batch_get_question_details(question_ids[i : i + 10])
                details_all.extend(chunk_res.get("questions", []))
            detail_map = {str(q.get("question_id")): q for q in details_all if q.get("question_id")}

            if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
                result = {
                    "success": False,
                    "error": "missing_llm_config",
                    "hint": "LESSON_PLAN_API_KEY 或 MOONSHOT_API_KEY 未配置，无法批解",
                }
            else:
                sem = asyncio.Semaphore(concurrency)
                solve_prompt = _prompt("mcp.solve_stepwise.v1")
                subj = server.current_subject

                async def _solve_one(qid: str) -> Dict[str, Any]:
                    async with sem:
                        q = detail_map.get(qid, {})
                        stem = str(q.get("stem") or "").strip()
                        if not stem:
                            return {"question_id": qid, "success": False, "error": "missing_stem"}
                        topic = ""
                        kps = q.get("knowledge_points")
                        if isinstance(kps, list) and kps:
                            topic = str(kps[0] or "").strip()
                        if not topic:
                            topic = str(q.get("knowledge_point") or "").strip()
                        user_prompt = (
                            f"Write a detailed step-by-step solution for the problem below in Markdown.\n\n"
                            f"Requirements:\n- Explain what each step is doing.\n"
                            f"- If the problem statement lacks information, state what needs to be added.\n"
                            f"- Match the language of the problem statement unless the caller explicitly requires another language.\n\n"
                            f"Subject: {subj}\nKnowledge point: {topic or '(unspecified)'}\n\nProblem:\n{stem}\n"
                        )
                        try:
                            text = await call_llm_text(
                                messages=[
                                    {"role": "system", "content": solve_prompt},
                                    {"role": "user", "content": user_prompt},
                                ],
                                model=LESSON_PLAN_MODEL,
                                temperature=0.3,
                                max_tokens=1200,
                            )
                        except Exception as exc:
                            logger.warning("solve_paper_solve_failed", extra={"qid": qid}, exc_info=True)
                            return {"question_id": qid, "success": False, "error": f"solve_failed: {exc}"}
                        return {
                            "question_id": qid,
                            "success": True,
                            "markdown": (text or "").strip(),
                            "question_type": q.get("question_type") or q.get("type") or "",
                            "knowledge_point": topic,
                        }

                solutions = await asyncio.gather(*[_solve_one(qid) for qid in question_ids])
                ok_count = sum(1 for s in solutions if s.get("success"))
                result = {
                    "success": True,
                    "subject": subj,
                    "paper_id": paper_id,
                    "total": len(solutions),
                    "solved": ok_count,
                    "failed": len(solutions) - ok_count,
                    "solutions": solutions,
                }

        elif name == "align_to_curriculum":
            stem = (arguments.get("stem") or "").strip()
            if not stem:
                result = {"success": False, "error": "missing_stem"}
            else:
                from backend.generation.question_library.curriculum_context import (
                    build_curriculum_context,
                    get_static_curriculum_baseline,
                )

                target_subject = (arguments.get("subject") or "").strip() or str(
                    getattr(server, "current_subject", "") or ""
                ).strip()
                topic = (arguments.get("topic") or "").strip()
                kps_in = arguments.get("knowledge_points")
                knowledge_points = [str(x).strip() for x in kps_in if str(x or "").strip()] if isinstance(kps_in, list) else []
                grade_id = str(arguments.get("grade_id") or "").strip()
                textbook_version_id = str(arguments.get("textbook_version_id") or "").strip()

                if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
                    ctx = get_static_curriculum_baseline(target_subject)
                    if knowledge_points:
                        ctx["knowledge_scope"] = {"in_scope": knowledge_points, "out_of_scope": []}
                    result = {
                        "success": True,
                        "source": "fallback",
                        "subject": target_subject,
                        "curriculum_standard": ctx.get("curriculum_standard"),
                        "in_scope": (ctx.get("knowledge_scope") or {}).get("in_scope") or [],
                        "out_of_scope": (ctx.get("knowledge_scope") or {}).get("out_of_scope") or [],
                        "question_requirements": ctx.get("question_requirements") or [],
                        "core_competencies": ctx.get("core_competencies") or [],
                        "prerequisites": ctx.get("prerequisites") or [],
                        "judgment": "unknown_without_llm",
                    }
                else:
                    try:
                        ctx = await build_curriculum_context(
                            subject=target_subject,
                            topic=topic or stem[:80],
                            knowledge_points=knowledge_points,
                            grade_id=grade_id,
                            textbook_version_id=textbook_version_id,
                            study_markdown=stem,
                        )
                    except Exception as exc:
                        logger.warning("align_to_curriculum_failed", exc_info=True)
                        result = {"success": False, "error": f"curriculum_failed: {exc}"}
                    else:
                        scope = ctx.get("knowledge_scope") or {}
                        out_of_scope = list(scope.get("out_of_scope") or [])
                        in_scope = list(scope.get("in_scope") or [])
                        # naive judgment: flag if any knowledge_point appears in out_of_scope
                        offending = []
                        for kp in knowledge_points:
                            if any(kp and (kp in s or s in kp) for s in out_of_scope):
                                offending.append(kp)
                        judgment = "out_of_scope" if offending else ("in_scope" if in_scope else "uncertain")
                        result = {
                            "success": True,
                            "source": "llm",
                            "subject": target_subject,
                            "curriculum_standard": ctx.get("curriculum_standard"),
                            "in_scope": in_scope,
                            "out_of_scope": out_of_scope,
                            "question_requirements": ctx.get("question_requirements") or [],
                            "core_competencies": ctx.get("core_competencies") or [],
                            "prerequisites": ctx.get("prerequisites") or [],
                            "judgment": judgment,
                            "offending_knowledge_points": offending,
                        }

        elif name == "paper_diff":
            await ensure_crawler_initialized()

            from backend.database.repositories.question.papers import get_paper
            from backend.database.repositories.question.question_cache import get_question_cache
            from backend.generation.paper_compose.workflow_support import _stem_fingerprint

            paper_id = arguments.get("paper_id")
            question_ids = arguments.get("question_ids") or []
            reference_paper_ids = arguments.get("reference_paper_ids") or []
            similarity_threshold = float(arguments.get("similarity_threshold", 0.6) or 0.6)
            similarity_threshold = max(0.0, min(1.0, similarity_threshold))
            max_questions = max(1, min(int(arguments.get("max_questions", 60) or 60), 120))

            if not reference_paper_ids:
                result = {"success": False, "error": "reference_paper_ids 必填且非空"}
                return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

            target_paper_meta: Optional[Dict[str, Any]] = None
            target_qids: List[str] = []
            if paper_id is not None:
                paper = await get_paper(user_id="1", paper_id=int(paper_id))
                if not paper:
                    result = {"success": False, "error": f"未找到目标试卷 paper_id={paper_id}"}
                    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
                target_paper_meta = paper
                target_qids = [str(q.get("question_id")) for q in paper.get("questions", []) if q.get("question_id")]
            elif question_ids:
                target_qids = [str(x) for x in question_ids if str(x or "").strip()]
            if not target_qids:
                result = {"success": False, "error": "paper_diff 需要 paper_id 或 question_ids"}
                return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

            target_qids = target_qids[:max_questions]

            ref_qid_to_paper: Dict[str, int] = {}
            ref_paper_names: Dict[int, str] = {}
            for ref_id in reference_paper_ids:
                try:
                    ref = await get_paper(user_id="1", paper_id=int(ref_id))
                except (TypeError, ValueError):
                    continue
                if not ref:
                    continue
                ref_paper_names[int(ref_id)] = ref.get("paper_name") or ""
                for q in ref.get("questions", []) or []:
                    qid = str(q.get("question_id") or "").strip()
                    if qid:
                        ref_qid_to_paper.setdefault(qid, int(ref_id))

            all_qids = list(set(target_qids) | set(ref_qid_to_paper.keys()))
            cached = await get_question_cache(question_ids=all_qids)

            async def _enrich_via_crawler(missing: List[str]) -> Dict[str, Dict[str, Any]]:
                enriched: Dict[str, Dict[str, Any]] = {}
                for i in range(0, len(missing), 10):
                    chunk_res = await server.crawler.batch_get_question_details(missing[i : i + 10])
                    for q in chunk_res.get("questions", []) or []:
                        qid = str(q.get("question_id") or "").strip()
                        if qid:
                            enriched[qid] = q
                return enriched

            missing_ids = [qid for qid in all_qids if not (cached.get(qid) or {}).get("stem")]
            crawler_extra = await _enrich_via_crawler(missing_ids) if missing_ids else {}

            def _stem_for(qid: str) -> str:
                item = cached.get(qid) or {}
                stem = str(item.get("stem") or "").strip()
                if stem:
                    return stem
                extra = crawler_extra.get(qid) or {}
                return str(extra.get("stem") or "").strip()

            def _kps_for(qid: str) -> List[str]:
                item = cached.get(qid) or {}
                kps_json = item.get("knowledge_points_json")
                if kps_json:
                    try:
                        parsed = json.loads(kps_json)
                        if isinstance(parsed, list):
                            out = [str(x).strip() for x in parsed if str(x or "").strip()]
                            if out:
                                return out
                    except (TypeError, ValueError):
                        pass
                single = str(item.get("knowledge_point") or "").strip()
                if single:
                    return [single]
                extra = crawler_extra.get(qid) or {}
                kps = extra.get("knowledge_points")
                if isinstance(kps, list):
                    return [str(x).strip() for x in kps if str(x or "").strip()]
                return []

            def _shingles(stem: str) -> set[str]:
                s = re.sub(r"\s+", "", (stem or "").lower())[:1500]
                if len(s) < 3:
                    return set()
                return {s[i : i + 3] for i in range(len(s) - 2)}

            def _jaccard(a: set[str], b: set[str]) -> float:
                if not a or not b:
                    return 0.0
                inter = len(a & b)
                union = len(a | b)
                return (inter / union) if union else 0.0

            target_data = [
                {
                    "qid": qid,
                    "stem": _stem_for(qid),
                    "fp": _stem_fingerprint(_stem_for(qid)),
                    "kps": _kps_for(qid),
                }
                for qid in target_qids
            ]
            ref_data = [
                {
                    "qid": qid,
                    "stem": _stem_for(qid),
                    "fp": _stem_fingerprint(_stem_for(qid)),
                    "kps": _kps_for(qid),
                    "paper_id": ref_qid_to_paper.get(qid),
                }
                for qid in ref_qid_to_paper.keys()
            ]
            ref_data = [r for r in ref_data if r["stem"]]

            ref_fp_set = {r["fp"] for r in ref_data if r["fp"]}
            ref_shingles = [(r, _shingles(r["stem"])) for r in ref_data]

            exact_dups: List[Dict[str, Any]] = []
            similar_pairs: List[Dict[str, Any]] = []
            for t in target_data:
                if not t["stem"]:
                    continue
                if t["fp"] and t["fp"] in ref_fp_set:
                    matched_refs = [r for r in ref_data if r["fp"] == t["fp"]]
                    exact_dups.append(
                        {
                            "target_qid": t["qid"],
                            "ref_qids": [r["qid"] for r in matched_refs],
                            "ref_paper_ids": sorted({r["paper_id"] for r in matched_refs if r["paper_id"] is not None}),
                        }
                    )
                    continue
                ts = _shingles(t["stem"])
                if not ts:
                    continue
                best = (0.0, None)
                for r, rs in ref_shingles:
                    if r["fp"] == t["fp"]:
                        continue
                    j = _jaccard(ts, rs)
                    if j > best[0]:
                        best = (j, r)
                if best[0] >= similarity_threshold and best[1]:
                    similar_pairs.append(
                        {
                            "target_qid": t["qid"],
                            "ref_qid": best[1]["qid"],
                            "ref_paper_id": best[1]["paper_id"],
                            "similarity": round(best[0], 3),
                        }
                    )

            target_kps_set: set[str] = set()
            for t in target_data:
                target_kps_set.update(t["kps"])
            ref_kps_set: set[str] = set()
            for r in ref_data:
                ref_kps_set.update(r["kps"])

            result = {
                "success": True,
                "target_paper_id": paper_id,
                "target_paper_name": (target_paper_meta or {}).get("paper_name") or "",
                "target_question_count": len(target_data),
                "reference_paper_ids": list(ref_paper_names.keys()),
                "reference_paper_names": ref_paper_names,
                "reference_question_count": len(ref_data),
                "similarity_threshold": similarity_threshold,
                "exact_dup_count": len(exact_dups),
                "exact_dups": exact_dups,
                "similar_pair_count": len(similar_pairs),
                "similar_pairs": similar_pairs,
                "unique_kp_in_target": sorted(target_kps_set - ref_kps_set),
                "missing_kp_from_target": sorted(ref_kps_set - target_kps_set),
                "shared_kp": sorted(target_kps_set & ref_kps_set),
            }

        elif name == "plot_function":
            from backend.generation.question_library.diagram_utils import render_matplotlib_2d_to_url

            expr = str(arguments.get("expr") or "").strip()
            if not expr:
                result = {"success": False, "error": "expr 不能为空"}
            else:
                x_range = arguments.get("x_range") or [-5, 5]
                y_range = arguments.get("y_range")
                title = str(arguments.get("title") or "").strip()
                label = str(arguments.get("label") or "").strip()
                alt = str(arguments.get("alt") or "plot").strip() or "plot"
                spec: Dict[str, Any] = {
                    "x_range": x_range,
                    "title": title,
                    "curves": [{"expr": expr, **({"label": label} if label else {})}],
                }
                if isinstance(y_range, list) and len(y_range) == 2:
                    spec["y_range"] = y_range
                published = await render_matplotlib_2d_to_url(spec=spec, user_id="1", alt=alt)
                if published.get("success"):
                    result = {
                        "success": True,
                        "url": str(published.get("url") or ""),
                        "markdown": str(published.get("markdown") or ""),
                        "filename": str(published.get("filename") or ""),
                        "cached": bool(published.get("cached")),
                        "bytes": int(published.get("bytes") or 0),
                    }
                else:
                    result = {
                        "success": False,
                        "error": str(published.get("error") or "plot_failed"),
                        "warnings": published.get("warnings") or [],
                    }

        elif name == "render_tikz":
            from backend.generation.question_library.diagram_utils import render_tikz_to_url

            tikz = str(arguments.get("tikz") or "").strip()
            if not tikz:
                result = {"success": False, "error": "tikz 不能为空"}
            else:
                preamble = str(arguments.get("preamble") or "").strip()
                alt = str(arguments.get("alt") or "diagram").strip() or "diagram"
                published = await render_tikz_to_url(tikz=tikz, user_id="1", alt=alt, preamble=preamble)
                if published.get("success"):
                    result = {
                        "success": True,
                        "url": str(published.get("url") or ""),
                        "markdown": str(published.get("markdown") or ""),
                        "filename": str(published.get("filename") or ""),
                        "cached": bool(published.get("cached")),
                        "bytes": int(published.get("bytes") or 0),
                    }
                else:
                    result = dict(published)

        elif name == "render_chemistry":
            from backend.generation.question_library.diagram_utils import render_chemistry_to_url

            expression = str(arguments.get("expression") or "").strip()
            if not expression:
                result = {"success": False, "error": "expression 不能为空"}
            else:
                alt = str(arguments.get("alt") or "化学方程式").strip() or "化学方程式"
                published = await render_chemistry_to_url(expression=expression, user_id="1", alt=alt)
                if published.get("success"):
                    result = {
                        "success": True,
                        "url": str(published.get("url") or ""),
                        "markdown": str(published.get("markdown") or ""),
                        "filename": str(published.get("filename") or ""),
                        "cached": bool(published.get("cached")),
                        "bytes": int(published.get("bytes") or 0),
                    }
                else:
                    result = dict(published)

        elif name == "render_graphviz":
            from backend.generation.question_library.diagram_utils import render_graphviz_to_url

            dot_code = str(arguments.get("dot") or "").strip()
            if not dot_code:
                result = {"success": False, "error": "dot 不能为空"}
            else:
                engine = str(arguments.get("engine") or "dot").strip().lower() or "dot"
                alt = str(arguments.get("alt") or "流程图").strip() or "流程图"
                published = await render_graphviz_to_url(dot_code=dot_code, user_id="1", alt=alt, engine=engine)
                if published.get("success"):
                    result = {
                        "success": True,
                        "url": str(published.get("url") or ""),
                        "markdown": str(published.get("markdown") or ""),
                        "filename": str(published.get("filename") or ""),
                        "engine": engine,
                        "cached": bool(published.get("cached")),
                        "bytes": int(published.get("bytes") or 0),
                    }
                else:
                    result = dict(published)

        elif name == "verify_diagram":
            url = str(arguments.get("url") or "").strip()
            description = str(arguments.get("description") or "").strip()
            strictness = max(1, min(int(arguments.get("strictness") or 3), 5))
            if not url or not description:
                result = {"success": False, "error": "url 和 description 都必填"}
            elif not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
                result = {
                    "success": False,
                    "error": "missing_llm_config",
                    "hint": "verify_diagram 依赖 vision-capable LLM，需要 LESSON_PLAN_API_KEY 或 MOONSHOT_API_KEY",
                }
            else:
                try:
                    from backend.generation.question_library.verify_diagram import verify_diagram_with_vision

                    verdict = await verify_diagram_with_vision(
                        diagram_url=url,
                        description=description,
                        strictness=strictness,
                    )
                    result = {"success": True, **verdict}
                except ImportError:
                    result = {
                        "success": False,
                        "error": "verify_diagram_module_missing",
                        "hint": "backend.generation.question_library.verify_diagram 尚未启用",
                    }
                except Exception as exc:
                    logger.warning("verify_diagram_failed", exc_info=True)
                    result = {"success": False, "error": f"verify_failed: {exc}"}

        elif name == "render_asy":
            from backend.generation.question_library.diagram_utils import render_asy_to_url

            asy_code = str(arguments.get("asy") or "").strip()
            if not asy_code:
                result = {"success": False, "error": "asy 不能为空"}
            else:
                alt = str(arguments.get("alt") or "diagram").strip() or "diagram"
                published = await render_asy_to_url(asy=asy_code, user_id="1", alt=alt)
                if published.get("success"):
                    result = {
                        "success": True,
                        "url": str(published.get("url") or ""),
                        "markdown": str(published.get("markdown") or ""),
                        "filename": str(published.get("filename") or ""),
                        "cached": bool(published.get("cached")),
                        "bytes": int(published.get("bytes") or 0),
                    }
                else:
                    result = dict(published)

        elif name == "render_circuit":
            from backend.generation.question_library.diagram_utils import render_circuit_to_url

            circuit_body = str(arguments.get("circuit_body") or "").strip()
            if not circuit_body:
                result = {"success": False, "error": "circuit_body 不能为空"}
            else:
                alt = str(arguments.get("alt") or "电路图").strip() or "电路图"
                published = await render_circuit_to_url(circuit_code=circuit_body, user_id="1", alt=alt)
                if published.get("success"):
                    result = {
                        "success": True,
                        "url": str(published.get("url") or ""),
                        "markdown": str(published.get("markdown") or ""),
                        "filename": str(published.get("filename") or ""),
                        "cached": bool(published.get("cached")),
                        "bytes": int(published.get("bytes") or 0),
                    }
                else:
                    result = dict(published)

        elif name == "render_matplotlib_3d":
            from backend.generation.question_library.diagram_utils import render_matplotlib_3d_to_url

            spec = arguments.get("spec")
            if not isinstance(spec, dict) or not spec:
                result = {"success": False, "error": "spec 必须是非空对象"}
            else:
                alt = str(arguments.get("alt") or "plot").strip() or "plot"
                published = await render_matplotlib_3d_to_url(spec=spec, user_id="1", alt=alt)
                if published.get("success"):
                    result = {
                        "success": True,
                        "url": str(published.get("url") or ""),
                        "markdown": str(published.get("markdown") or ""),
                        "filename": str(published.get("filename") or ""),
                        "cached": bool(published.get("cached")),
                        "bytes": int(published.get("bytes") or 0),
                    }
                else:
                    result = dict(published)

        elif name == "render_svg_diagram":
            from backend.generation.question_library.diagram_utils import render_svg_to_url

            spec = arguments.get("spec")
            if not isinstance(spec, dict) or not spec:
                result = {"success": False, "error": "spec 必须是非空对象"}
            else:
                alt = str(arguments.get("alt") or "diagram").strip() or "diagram"
                published = await render_svg_to_url(spec=spec, user_id="1", alt=alt)
                if published.get("success"):
                    result = {
                        "success": True,
                        "url": str(published.get("url") or ""),
                        "markdown": str(published.get("markdown") or ""),
                        "filename": str(published.get("filename") or ""),
                        "cached": bool(published.get("cached")),
                        "bytes": int(published.get("bytes") or 0),
                    }
                else:
                    result = dict(published)

        elif name == "render_schematic":
            from backend.generation.question_library.diagram_utils import render_schematic_to_url

            spec = arguments.get("spec")
            if not isinstance(spec, dict) or not spec:
                result = {"success": False, "error": "spec 必须是非空对象"}
            else:
                alt = str(arguments.get("alt") or "diagram").strip() or "diagram"
                published = await render_schematic_to_url(spec=spec, user_id="1", alt=alt)
                if published.get("success"):
                    result = {
                        "success": True,
                        "url": str(published.get("url") or ""),
                        "markdown": str(published.get("markdown") or ""),
                        "filename": str(published.get("filename") or ""),
                        "cached": bool(published.get("cached")),
                        "bytes": int(published.get("bytes") or 0),
                    }
                else:
                    result = dict(published)

        elif name == "generate_image":
            from backend.media.image_generate import generate_image_via_seedream

            prompt = str(arguments.get("prompt") or "").strip()
            if not prompt:
                result = {"success": False, "error": "prompt 不能为空"}
            else:
                alt = str(arguments.get("alt") or "image").strip() or "image"
                caption = str(arguments.get("caption") or "").strip()
                model_override = str(arguments.get("model") or "").strip()
                size = str(arguments.get("size") or "").strip()
                response_format = str(arguments.get("response_format") or "").strip()
                try:
                    n_val = int(arguments.get("n") or 1)
                except (TypeError, ValueError):
                    n_val = 1
                result = await generate_image_via_seedream(
                    prompt=prompt,
                    user_id="1",
                    alt=alt,
                    caption=caption,
                    model=model_override,
                    size=size,
                    n=n_val,
                    response_format=response_format,
                )

        elif name == "revise_diagram":
            filename = str(arguments.get("filename") or "").strip()
            user_request = str(arguments.get("user_request") or "").strip()
            alt_override = str(arguments.get("alt") or "").strip()
            if not filename or not user_request:
                result = {"success": False, "error": "filename 和 user_request 都必填"}
            else:
                try:
                    from backend.generation.question_library.diagram_revise import revise_diagram_source

                    result = await revise_diagram_source(
                        filename=filename,
                        user_request=user_request,
                        user_id="1",
                        alt=alt_override or None,
                    )
                except ImportError:
                    result = {
                        "success": False,
                        "error": "diagram_revise_module_missing",
                        "hint": "backend.generation.question_library.diagram_revise 尚未启用",
                    }
                except Exception as exc:
                    logger.warning("revise_diagram_failed", exc_info=True)
                    result = {"success": False, "error": f"revise_failed: {exc}"}

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
        logger.exception("stdio_tool_call_failed", extra={"tool": name})
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": str(e), "tool": name}, ensure_ascii=False),
            )
        ]
